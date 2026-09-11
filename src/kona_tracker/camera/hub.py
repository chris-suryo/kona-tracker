"""One camera, many viewers, and honesty about whether the picture is live.

A USB webcam or an RTSP camera can be opened by exactly one process, and two
iPhones (Chris and their sister) may watch at once. The hub owns the single
connection and fans the latest frame out to every viewer at its own pace.

What a network camera adds is failure: the camera reboots, Wi-Fi drops, or a
TCP read blocks forever inside FFmpeg. An MJPEG <img> then shows the LAST
frame indefinitely, which looks exactly like a calm dog. So the hub is built
as a supervisor over disposable reader threads:

- the reader (one per connection "generation") opens the source and reads;
- the supervisor watches frame timestamps. No frame for `hang_after` means
  the reader is stuck; it is abandoned (a thread blocked in C cannot be
  killed; it releases the camera when it eventually returns and sees it is
  no longer current) and a new generation is started after a backoff;
- viewers get the real frame while it is fresh, and a "NO SIGNAL" placeholder
  frame once per second while it is not, so the picture visibly changes;
- `status()` tells the page whether it is live, stale, or disconnected.

Capture starts on the first viewer and stops after an idle grace so the
camera is not held open (and a webcam LED goes off) when nobody is watching.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from kona_tracker.camera.placeholder import NO_SIGNAL_JPEG
from kona_tracker.camera.redact import redact_url
from kona_tracker.camera.source import CameraFrameError, FrameSource

BOUNDARY = "kona-frame"

log = logging.getLogger("kona_tracker.camera")

IDLE = "idle"
CONNECTING = "connecting"
LIVE = "live"
STALE = "stale"
DISCONNECTED = "disconnected"


class CameraHub:
    def __init__(
        self,
        open_source: Callable[[], FrameSource],
        idle_stop_seconds: float = 5.0,
        max_fps: float = 15.0,
        stale_after: float = 3.0,
        hang_after: float = 10.0,
        max_misses: int = 10,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        placeholder: bytes = NO_SIGNAL_JPEG,
    ):
        self._open_source = open_source
        self._idle_stop = idle_stop_seconds
        self._min_interval = 1.0 / max_fps
        self.stale_after = stale_after
        self._hang_after = hang_after
        self._max_misses = max_misses
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._placeholder = placeholder

        self._lock = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._last_frame_at = 0.0
        self._viewers = 0
        self._last_viewer_left = 0.0
        self._supervisor: threading.Thread | None = None
        self._stop = threading.Event()
        self._generation = 0
        self._reader_alive = False
        self._reader_started_at = 0.0
        self._backoff = backoff_base
        self._fails = 0  # bumps whenever a reader dies; wakes waiting viewers

        self.opens = 0  # successful source opens (tests, status)
        self.reconnects = 0  # reconnect attempts after the first connection
        self.last_error: str | None = None  # always redacted
        self.last_error_kind: str | None = None

    # -- status -------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            supervising = bool(self._supervisor and self._supervisor.is_alive())
            age = (time.monotonic() - self._last_frame_at) if self._frame else None
            if not supervising:
                state = IDLE
            elif not self._reader_alive:
                state = DISCONNECTED
            elif self._frame is None or age is None:
                state = CONNECTING
            elif age < self.stale_after:
                state = LIVE
            else:
                state = STALE
            return {
                "state": state,
                "last_frame_age": None if age is None else round(age, 2),
                "generation": self._generation,
                "opens": self.opens,
                "reconnects": self.reconnects,
                "last_error": self.last_error,
                "last_error_kind": self.last_error_kind,
            }

    # -- lifecycle ----------------------------------------------------------

    def _ensure_running(self) -> None:
        with self._lock:
            if self._supervisor and self._supervisor.is_alive():
                return
            self._stop.clear()
            self._backoff = self._backoff_base
            self._supervisor = threading.Thread(
                target=self._supervise, name="kona-camera-supervisor", daemon=True
            )
            self._supervisor.start()

    def _idle(self) -> bool:
        with self._lock:
            return self._viewers == 0 and (
                time.monotonic() - self._last_viewer_left > self._idle_stop
            )

    def _supervise(self) -> None:
        first = True
        try:
            while not self._stop.is_set() and not self._idle():
                if not first:
                    self.reconnects += 1
                    # Interruptible backoff so stop() never waits on a sleep.
                    if self._stop.wait(self._backoff):
                        break
                    if self._idle():
                        break
                    self._backoff = min(self._backoff * 2, self._backoff_max)
                first = False
                with self._lock:
                    self._generation += 1
                    gen = self._generation
                    self._reader_alive = True
                    self._reader_started_at = time.monotonic()
                    self._lock.notify_all()
                threading.Thread(
                    target=self._read, args=(gen,), name=f"kona-camera-reader-{gen}", daemon=True
                ).start()
                # Watch this generation until it dies or hangs.
                while not self._stop.is_set() and not self._idle():
                    with self._lock:
                        alive = self._reader_alive
                        last = self._last_frame_at
                        started = self._reader_started_at
                    if not alive:
                        break
                    now = time.monotonic()
                    reference = last if last > started else started
                    if now - reference > self._hang_after:
                        with self._lock:
                            self._reader_alive = False  # abandon; reader sees gen != current
                            self.last_error = f"no frames for {self._hang_after:.0f}s; reconnecting"
                            self.last_error_kind = "hung"
                            log.warning("camera hung: %s", self.last_error)
                            self._fails += 1
                            self._lock.notify_all()
                        break
                    time.sleep(0.1)
        finally:
            with self._lock:
                self._generation += 1  # invalidates any lingering reader
                self._reader_alive = False
                self._frame = None
                self._lock.notify_all()

    def _current(self, gen: int) -> bool:
        with self._lock:
            return gen == self._generation and self._reader_alive and not self._stop.is_set()

    def _read(self, gen: int) -> None:
        try:
            source = self._open_source()
        except Exception as e:  # missing camera, bad URL, auth refused...
            with self._lock:
                if gen == self._generation:
                    self.last_error = redact_url(f"{type(e).__name__}: {e}")
                    self.last_error_kind = "open"
                    log.warning("camera open: %s", self.last_error)
                    self._reader_alive = False
                    self._fails += 1
                    self._lock.notify_all()
            return
        self.opens += 1
        misses = 0
        try:
            while self._current(gen):
                started = time.monotonic()
                try:
                    jpeg = source.read_jpeg()
                except Exception as e:
                    with self._lock:
                        self.last_error = redact_url(f"{type(e).__name__}: {e}")
                        self.last_error_kind = (
                            "black_frame" if isinstance(e, CameraFrameError) else "read"
                        )
                        log.warning("camera %s: %s", self.last_error_kind, self.last_error)
                    break
                if jpeg:
                    misses = 0
                    with self._lock:
                        if gen != self._generation:
                            break  # abandoned while we were blocked; drop the frame
                        self._frame = jpeg
                        self._seq += 1
                        self._last_frame_at = time.monotonic()
                        self._backoff = self._backoff_base  # healthy again
                        self._lock.notify_all()
                else:
                    misses += 1
                    if misses >= self._max_misses:
                        with self._lock:
                            self.last_error = f"{misses} consecutive empty reads"
                            self.last_error_kind = "empty_frames"
                            log.warning("camera empty_frames: %s", self.last_error)
                        break
                    time.sleep(0.05)
                elapsed = time.monotonic() - started
                if elapsed < self._min_interval:
                    time.sleep(self._min_interval - elapsed)
        finally:
            try:
                source.close()
            except Exception:
                pass
            with self._lock:
                if gen == self._generation:
                    self._reader_alive = False
                    self._fails += 1
                    self._lock.notify_all()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._lock.notify_all()  # wake waiting viewers so their streams end
        t = self._supervisor
        if t and t.is_alive():
            t.join(timeout=5)

    # -- viewers ------------------------------------------------------------

    def _add_viewer(self) -> None:
        with self._lock:
            self._viewers += 1
        self._ensure_running()

    def _remove_viewer(self) -> None:
        with self._lock:
            self._viewers -= 1
            if self._viewers == 0:
                self._last_viewer_left = time.monotonic()

    def _wait_frame(self, after_seq: int, timeout: float) -> tuple[bytes | None, int]:
        """Block until a frame numbered above `after_seq` exists, the reader
        dies, or timeout. Frames are numbered from 1, so `after_seq=0` means
        any frame. Returning on reader death keeps a viewer from sitting on a
        dead camera for the whole timeout."""
        deadline = time.monotonic() + timeout
        with self._lock:
            fails = self._fails
            while self._seq <= after_seq and not self._stop.is_set() and self._fails == fails:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, after_seq
                self._lock.wait(remaining)
            if self._seq > after_seq:
                return self._frame, self._seq
            return None, after_seq  # stopped, or the reader died: caller shows the placeholder

    def snapshot(self, timeout: float = 3.0) -> tuple[bytes, str]:
        """(jpeg, state). A fresh frame if there is one within `timeout`,
        else the placeholder with the honest state."""
        self._add_viewer()
        try:
            with self._lock:
                fresh = (
                    self._frame is not None
                    and time.monotonic() - self._last_frame_at < self.stale_after
                )
                frame, seq = self._frame, self._seq
            if not fresh:
                frame, _ = self._wait_frame(after_seq=seq, timeout=timeout)
            if frame is None:
                return self._placeholder, self.status()["state"]
            return frame, LIVE
        finally:
            self._remove_viewer()

    @staticmethod
    def _part(jpeg: bytes, state: str) -> bytes:
        return (
            (
                f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nX-Kona-State: {state}\r\n"
                f"Content-Length: {len(jpeg)}\r\n\r\n"
            ).encode()
            + jpeg
            + b"\r\n"
        )

    async def mjpeg(self, max_frames: int | None = None) -> AsyncIterator[bytes]:
        """Yield multipart/x-mixed-replace parts. Real frames while fresh; the
        placeholder once per second while stale or disconnected. Ends on
        client disconnect (generator closed), on stop(), or after `max_frames`
        parts (placeholders count)."""
        self._add_viewer()
        loop = asyncio.get_running_loop()
        seq = 0  # frames are numbered from 1; 0 means 'any frame'
        sent = 0
        showing_placeholder = False
        try:
            while max_frames is None or sent < max_frames:
                wait = 1.0 if showing_placeholder else self.stale_after
                frame, new_seq = await loop.run_in_executor(None, self._wait_frame, seq, wait)
                if self._stop.is_set():
                    break
                if frame is None:
                    state = self.status()["state"]
                    yield self._part(self._placeholder, state)
                    showing_placeholder = True
                else:
                    seq = new_seq
                    yield self._part(frame, LIVE)
                    showing_placeholder = False
                sent += 1
        finally:
            self._remove_viewer()
