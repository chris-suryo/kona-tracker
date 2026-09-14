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

That grace used to be five hard-coded seconds, which meant a glance at the
Activity tab closed the webcam and coming back reopened it. A USB webcam
that is closed and reopened in quick succession is the textbook way to
wedge it on Windows: it opens cleanly, lights its LED and delivers nothing
until it is physically replugged (docs/device-capabilities.md). So the
grace is now a setting with a long default, and every close is followed by
a cooldown before the next open, whatever caused the close. Neither is a
proven fix for the black screen Chris sees; both remove a way for this app
to manufacture that fault itself, and only his hardware can say more.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import AsyncIterator, Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, NamedTuple

from kona_tracker.camera.placeholder import NO_SIGNAL_JPEG
from kona_tracker.camera.redact import redact_url
from kona_tracker.camera.source import CameraFrameError, FrameSource

BOUNDARY = "kona-frame"

#: Concurrent MJPEG streams the hub will carry. The phone polls /snapshot.jpg
#: now; what is left of streaming is curl and a desktop, and a household
#: never needs more than this. It is also the size of the pool the stream
#: waits run on: the two must match, or the (cap+1)th viewer queues on the
#: pool, which is exactly the silent hang this exists to prevent.
MAX_STREAMS = 4

log = logging.getLogger("kona_tracker.camera")

IDLE = "idle"
CONNECTING = "connecting"
LIVE = "live"
STALE = "stale"
DISCONNECTED = "disconnected"


class Snapshot(NamedTuple):
    """One answer from `CameraHub.snapshot()`: the pixels and, read at the
    same instant, the words the page may put beside them. `seq` is the
    frame's number, monotonic for the life of the process, so a client can
    ask for "the one after this" and the server does the waiting."""

    jpeg: bytes
    state: str
    seq: int
    frame_age: float | None
    error_kind: str | None


class CameraHub:
    def __init__(
        self,
        open_source: Callable[[], FrameSource],
        idle_stop_seconds: float = 120.0,
        reopen_cooldown_seconds: float = 2.0,
        max_fps: float = 15.0,
        stale_after: float = 3.0,
        hang_after: float = 10.0,
        max_misses: int = 10,
        backoff_base: float = 1.0,
        backoff_max: float = 30.0,
        placeholder: bytes = NO_SIGNAL_JPEG,
        name: str = "camera",
    ):
        # Two hubs (the house camera and the robot) log through the same
        # logger; the name is what tells their lines and threads apart. The
        # default keeps every existing line byte-identical.
        self.name = name
        self._open_source = open_source
        self._idle_stop = idle_stop_seconds
        self._reopen_cooldown = reopen_cooldown_seconds
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
        # When a source was last released, so the next open can keep its
        # distance; and whether the supervisor is in that pause right now,
        # which the status reports as connecting rather than as a failure.
        self._last_close_at = 0.0
        self._reopening = False
        # A blocked C call cannot be killed. Permit one replacement, then
        # wait for a slot instead of leaking a thread on every retry forever.
        self._readers: set[threading.Thread] = set()
        self._backoff = backoff_base
        self._fails = 0  # bumps whenever a reader dies; wakes waiting viewers
        # Stream waits get their own bounded pool rather than asyncio's default
        # executor. A stream a phone abandoned without closing keeps its
        # generator alive; on the shared executor enough of those starved
        # everything, including new streams, while ordinary endpoints kept
        # answering from anyio's separate pool. Fenced off, they can only
        # starve each other, and the cap turns that into a loud 503.
        self._streams = 0
        self._stream_pool = ThreadPoolExecutor(
            max_workers=MAX_STREAMS, thread_name_prefix="kona-stream"
        )

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
            elif self._reopening:
                state = CONNECTING
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
                "readers": len(self._readers),
                # `viewers` counts every caller inside snapshot() or mjpeg()
                # right now and bounces with pollers; `streams` counts the
                # long-lived generators, the number that would have made the
                # 2026-09-11 hang a ten-minute diagnosis.
                "viewers": self._viewers,
                "streams": self._streams,
            }

    # -- lifecycle ----------------------------------------------------------

    def _ensure_running(self) -> None:
        with self._lock:
            if self._supervisor and self._supervisor.is_alive():
                return
            self._stop.clear()
            self._backoff = self._backoff_base
            self._supervisor = threading.Thread(
                target=self._supervise, name=f"kona-{self.name}-supervisor", daemon=True
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
                with self._lock:
                    if len(self._readers) >= 2:
                        self.last_error = (
                            "camera readers are stuck; unplug USB or restart the server"
                        )
                        self.last_error_kind = "reader_limit"
                        self._lock.wait(timeout=0.1)
                        continue
                if not first:
                    self.reconnects += 1
                    # Interruptible backoff so stop() never waits on a sleep.
                    if self._stop.wait(self._backoff):
                        break
                    if self._idle():
                        break
                    self._backoff = min(self._backoff * 2, self._backoff_max)
                first = False
                # A close is always followed by a pause before the next open,
                # whether the close was idle, a failure or an abandoned
                # reader finally returning. Interruptible, like the backoff.
                with self._lock:
                    pause = self._reopen_cooldown - (time.monotonic() - self._last_close_at)
                    self._reopening = pause > 0
                if pause > 0:
                    try:
                        if self._stop.wait(pause) or self._idle():
                            break
                    finally:
                        with self._lock:
                            self._reopening = False
                with self._lock:
                    self._generation += 1
                    gen = self._generation
                    self._reader_alive = True
                    self._frame = None  # a previous generation is never live
                    self._reader_started_at = time.monotonic()
                    reader = threading.Thread(
                        target=self._reader_task,
                        args=(gen,),
                        name=f"kona-{self.name}-reader-{gen}",
                        daemon=True,
                    )
                    self._readers.add(reader)
                    reader.start()
                    self._lock.notify_all()
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
                            log.warning("%s hung: %s", self.name, self.last_error)
                            self._fails += 1
                            self._lock.notify_all()
                        break
                    time.sleep(0.1)
        finally:
            with self._lock:
                self._generation += 1  # invalidates any lingering reader
                self._reader_alive = False
                self._reopening = False
                self._frame = None
                self._supervisor = None
                self._lock.notify_all()
                # A viewer may arrive between the last idle check and here.
                # It must not inherit a supervisor that is about to exit.
                if self._viewers and not self._stop.is_set():
                    self._ensure_running()

    def _reader_task(self, gen: int) -> None:
        try:
            self._read(gen)
        finally:
            with self._lock:
                self._readers.discard(threading.current_thread())
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
                    log.warning("%s open: %s", self.name, self.last_error)
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
                        if not self._current(gen):
                            break
                        self.last_error = redact_url(f"{type(e).__name__}: {e}")
                        self.last_error_kind = (
                            "black_frame" if isinstance(e, CameraFrameError) else "read"
                        )
                        log.warning("%s %s: %s", self.name, self.last_error_kind, self.last_error)
                    break
                if jpeg:
                    misses = 0
                    with self._lock:
                        if not self._current(gen):
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
                            if not self._current(gen):
                                break
                            self.last_error = f"{misses} consecutive empty reads"
                            self.last_error_kind = "empty_frames"
                            log.warning("%s empty_frames: %s", self.name, self.last_error)
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
                self._last_close_at = time.monotonic()
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
        # Let cooperative readers release the device before lifespan exits.
        # A native hang must not turn this cleanup into another endless wait.
        deadline = time.monotonic() + 1.0
        with self._lock:
            readers = tuple(self._readers)
        for reader in readers:
            reader.join(timeout=max(0.0, deadline - time.monotonic()))
        # Waits still queued belong to streams whose clients are gone.
        self._stream_pool.shutdown(wait=False, cancel_futures=True)

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
                fresh = (
                    self._reader_alive
                    and not self._stop.is_set()
                    and time.monotonic() - self._last_frame_at < self.stale_after
                )
                return self._frame if fresh else None, self._seq
            return None, after_seq  # stopped, or the reader died: caller shows the placeholder

    def snapshot(self, after_seq: int = 0, timeout: float | None = None) -> Snapshot:
        """A frame newer than `after_seq`, or the placeholder with the honest state.

        `after_seq=0` (the capture button, a page's first poll) returns the
        current frame at once when it is fresh. A client that sends back the
        seq it last received is held until a newer frame exists, which is
        what makes polling cost one request per frame rather than one per
        guess, and lets a slow link fall behind by skipping frames instead of
        queueing them.

        `timeout` defaults to `stale_after` on purpose, as `mjpeg()` already
        does. The page relies on "placeholder body => state is not live",
        and that only holds when a caller waits at least as long as a frame
        may be called fresh; a shorter wait could hand back the placeholder
        while a frame under `stale_after` old still made the state `live`.

        `after_seq` is clamped to the current seq. Seq restarts at 0 with the
        process, so a phone that kept its page open across a `kona serve`
        restart would otherwise wait the whole timeout for a number that will
        not exist again for hours, and receive placeholders marked live.
        """
        wait = self.stale_after if timeout is None else timeout
        self._add_viewer()
        try:
            with self._lock:
                after = min(after_seq, self._seq)
                fresh = (
                    self._frame is not None
                    and self._reader_alive
                    and not self._stop.is_set()
                    and time.monotonic() - self._last_frame_at < self.stale_after
                )
                frame, seq = self._frame, self._seq
            if after > 0:
                frame, seq = self._wait_frame(after_seq=after, timeout=wait)
            elif not fresh:
                frame, seq = self._wait_frame(after_seq=seq, timeout=wait)
            # One reading of the status, so the words describe the same
            # instant as the pixels. A real frame is live by construction.
            status = self.status()
            return Snapshot(
                jpeg=self._placeholder if frame is None else frame,
                state=status["state"] if frame is None else LIVE,
                seq=seq,
                frame_age=status["last_frame_age"],
                error_kind=status["last_error_kind"],
            )
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
        with self._lock:
            self._streams += 1
        loop = asyncio.get_running_loop()
        seq = 0  # frames are numbered from 1; 0 means 'any frame'
        sent = 0
        showing_placeholder = False
        try:
            while max_frames is None or sent < max_frames:
                if self._stop.is_set():
                    break  # stop() shuts the pool; never submit to it after
                wait = 1.0 if showing_placeholder else self.stale_after
                frame, new_seq = await loop.run_in_executor(
                    self._stream_pool, self._wait_frame, seq, wait
                )
                if self._stop.is_set():
                    break
                seq = new_seq
                if frame is None:
                    state = self.status()["state"]
                    yield self._part(self._placeholder, state)
                    showing_placeholder = True
                else:
                    yield self._part(frame, LIVE)
                    showing_placeholder = False
                sent += 1
        finally:
            with self._lock:
                self._streams -= 1
            self._remove_viewer()
