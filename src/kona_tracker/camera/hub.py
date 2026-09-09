"""One camera, many viewers.

A USB webcam can be opened by exactly one process, and two iPhones (Chris and
their sister) may watch at once. The hub owns a single capture thread that
keeps only the latest frame; each viewer reads that buffer at its own pace,
so a slow phone never backs up the camera. The thread starts on the first
viewer and stops a few seconds after the last one leaves, so the webcam LED
goes off when nobody is watching.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import AsyncIterator, Callable

from kona_tracker.camera.source import FrameSource

BOUNDARY = "kona-frame"


class CameraHub:
    def __init__(
        self,
        open_source: Callable[[], FrameSource],
        idle_stop_seconds: float = 5.0,
        max_fps: float = 15.0,
    ):
        self._open_source = open_source
        self._idle_stop = idle_stop_seconds
        self._min_interval = 1.0 / max_fps
        self._lock = threading.Condition()
        self._frame: bytes | None = None
        self._seq = 0
        self._viewers = 0
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_viewer_left = 0.0
        self.error: str | None = None
        self.opens = 0  # how many times the source was opened (tests)

    # -- lifecycle ----------------------------------------------------------

    def _ensure_running(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self.error = None
            self._thread = threading.Thread(target=self._run, name="kona-camera", daemon=True)
            self._thread.start()

    def _run(self) -> None:
        try:
            source = self._open_source()
        except Exception as e:  # camera missing, busy, wrong index...
            with self._lock:
                self.error = f"{type(e).__name__}: {e}"
                self._lock.notify_all()
            return
        self.opens += 1
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                jpeg = source.read_jpeg()
                if jpeg:
                    with self._lock:
                        self._frame = jpeg
                        self._seq += 1
                        self._lock.notify_all()
                with self._lock:
                    idle = self._viewers == 0 and (
                        time.monotonic() - self._last_viewer_left > self._idle_stop
                    )
                if idle:
                    break
                elapsed = time.monotonic() - started
                if elapsed < self._min_interval:
                    time.sleep(self._min_interval - elapsed)
        finally:
            source.close()
            with self._lock:
                self._frame = None
                self._lock.notify_all()

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._lock.notify_all()  # wake waiting viewers so their streams end
        t = self._thread
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
        """Block until a frame numbered above `after_seq` exists (or timeout/error).
        Frames are numbered from 1, so `after_seq=0` means any frame."""
        deadline = time.monotonic() + timeout
        with self._lock:
            while self._seq <= after_seq and self.error is None and not self._stop.is_set():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None, after_seq
                self._lock.wait(remaining)
            return self._frame, self._seq

    def snapshot(self, timeout: float = 3.0) -> bytes | None:
        self._add_viewer()
        try:
            frame, _ = self._wait_frame(after_seq=0, timeout=timeout)
            return frame
        finally:
            self._remove_viewer()

    async def mjpeg(self, max_frames: int | None = None) -> AsyncIterator[bytes]:
        """Yield multipart/x-mixed-replace chunks. Ends on client disconnect
        (the generator is closed), on camera error, or after `max_frames`."""
        self._add_viewer()
        loop = asyncio.get_running_loop()
        seq = 0  # frames are numbered from 1; 0 means 'any frame'
        sent = 0
        try:
            while max_frames is None or sent < max_frames:
                frame, seq = await loop.run_in_executor(None, self._wait_frame, seq, 5.0)
                if frame is None:
                    if self.error or self._stop.is_set():
                        break
                    continue  # timeout without error: keep waiting
                yield (
                    (
                        f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(frame)}\r\n\r\n"
                    ).encode()
                    + frame
                    + b"\r\n"
                )
                sent += 1
        finally:
            self._remove_viewer()
