"""Frame sources: where JPEG frames come from.

`OpenCVSource` is the real webcam (USB on the PC today, the same camera on
the Pi tomorrow). `FakeSource` is a deterministic test pattern so the whole
web app can be exercised with no hardware: in tests, in CI, and in the cloud
sandbox where this code is written. cv2 is imported lazily so nothing but
the real source ever loads the OpenCV wheel.
"""

from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Any, Protocol

from kona_tracker.camera.redact import redact_url, with_credentials


class FrameSource(Protocol):
    def read_jpeg(self) -> bytes | None:
        """Return one JPEG-encoded frame, or None if the camera gave nothing."""
        ...

    def close(self) -> None: ...


class CameraOpenError(RuntimeError):
    """The camera (USB index or network URL) could not be opened."""


class CameraFrameError(RuntimeError):
    """The camera opened, but its frames cannot be presented as a picture."""


def frame_is_unusable(frame: Any) -> bool:
    """True for an effectively all-black image, including a few hot pixels."""
    return float(frame.mean()) <= 0.25


@dataclass(frozen=True)
class FrameStats:
    """Raw pixel statistics for one frame, on the usual 0-255 scale."""

    mean: float
    minimum: float
    maximum: float
    stddev: float


@dataclass(frozen=True)
class CameraReport:
    """What one (index, backend) pair actually did. Never an exception."""

    index: int
    backend: str
    opened: bool
    width: int = 0
    height: int = 0
    frames: int = 0
    stats: FrameStats | None = None
    verdict: str = ""
    detail: str = ""


#: Backends to try, most reliable on Windows first. `None` = OpenCV's choice.
_BACKENDS = ("CAP_DSHOW", "CAP_MSMF", None)


def _classify(stats: FrameStats) -> tuple[str, str]:
    """Name what the pixels are, and say what it implies.

    The load-bearing distinction is **stddev**, not mean. A closed privacy
    shutter, or a driver handing back an empty buffer, produces pixels that
    are identically zero: no variation at all. A real sensor in a genuinely
    dark room still has read noise, so its mean is low but its stddev is
    not. Telling those apart is the difference between "open the cover" and
    "turn on a light", and the app could not distinguish them before.
    """
    if stats.maximum == 0:
        return (
            "all-zero",
            "every pixel is exactly 0: shutter closed, or the driver is handing "
            "back an empty buffer. Not a dark room -- a dark room has noise.",
        )
    if stats.stddev < 1.0:
        return (
            "flat",
            "almost no pixel-to-pixel variation. Lens blocked, or the sensor is "
            "returning a constant. Check for a cover or a finger over the lens.",
        )
    if stats.mean < 8.0:
        return (
            "very dark",
            "real sensor noise is present, so the camera is working -- there "
            "is just almost no light. Turn a light on and re-run.",
        )
    return ("usable", "a real picture.")


def inspect_cameras(
    indexes: range = range(0, 5), frames_per: int = 5, cv2_module: Any = None
) -> list[CameraReport]:
    """Try every index against every backend and report what came back.

    A diagnostic must never fail: `camera-test` raises on black frames, which
    is right for a health check and useless when the question is *why* the
    frames are black. This one catches everything and always returns rows.
    """
    cv2 = cv2_module if cv2_module is not None else _import_cv2()
    reports: list[CameraReport] = []
    for index in indexes:
        for name in _BACKENDS:
            flag = getattr(cv2, name, None) if name else None
            label = name or "default"
            cap = None
            try:
                cap = cv2.VideoCapture(index) if flag is None else cv2.VideoCapture(index, flag)
                if not cap.isOpened():
                    reports.append(
                        CameraReport(
                            index, label, False, verdict="no device", detail="did not open"
                        )
                    )
                    continue
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                best: FrameStats | None = None
                read = 0
                for _ in range(frames_per):
                    ok, frame = cap.read()
                    if not ok or frame is None:
                        continue
                    read += 1
                    stats = FrameStats(
                        mean=round(float(frame.mean()), 3),
                        minimum=round(float(frame.min()), 3),
                        maximum=round(float(frame.max()), 3),
                        stddev=round(float(frame.std()), 3),
                    )
                    # Keep the liveliest frame: a camera warming up often
                    # delivers a black frame or two before a real one.
                    if best is None or stats.stddev > best.stddev:
                        best = stats
                if best is None:
                    reports.append(
                        CameraReport(
                            index,
                            label,
                            True,
                            width,
                            height,
                            0,
                            verdict="opens, no frames",
                            detail="the device opened but never delivered an image",
                        )
                    )
                    continue
                verdict, detail = _classify(best)
                reports.append(
                    CameraReport(index, label, True, width, height, read, best, verdict, detail)
                )
            except Exception as e:  # a diagnostic that raises is not a diagnostic
                reports.append(
                    CameraReport(
                        index, label, False, verdict="error", detail=f"{type(e).__name__}: {e}"
                    )
                )
            finally:
                if cap is not None:
                    cap.release()
    return reports


def _import_cv2():
    """Import OpenCV with FFmpeg tuned for network cameras.

    Env vars must be set before the first import: TCP transport avoids UDP
    packet-loss artifacts on Wi-Fi, `timeout` (microseconds) makes a dead
    socket error out instead of blocking forever, and the log level keeps
    FFmpeg from printing connection strings (which carry credentials).
    """
    os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")
    os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "-8")
    os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")
    import cv2

    return cv2


class OpenCVSource:
    """USB / built-in webcam via OpenCV.

    On Windows, DirectShow (CAP_DSHOW) opens reliably where the default MSMF
    backend sometimes hangs for seconds; we try it first and fall back.
    """

    def __init__(
        self, index: int = 0, width: int = 1280, height: int = 720, fps: int = 15, quality: int = 80
    ):
        cv2 = _import_cv2()  # lazy: tests and CI never need the wheel loaded

        self._cv2 = cv2
        self._quality = quality
        self._black_frames = 0
        cap = None
        backends = [getattr(cv2, "CAP_DSHOW", None), None]
        for backend in backends:
            cap = cv2.VideoCapture(index) if backend is None else cv2.VideoCapture(index, backend)
            if cap.isOpened():
                break
            cap.release()
            cap = None
        if cap is None:
            raise CameraOpenError(f"no camera opened at index {index}; try `kona cameras`")
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
        self._cap = cap
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    def read_jpeg(self) -> bytes | None:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        # DirectShow can successfully deliver a stream of all-zero pixels
        # when a webcam privacy shutter is closed. That is transport-live but
        # not a usable picture, and must never earn the green LIVE badge.
        if frame_is_unusable(frame):
            self._black_frames += 1
            if self._black_frames >= 3:
                raise CameraFrameError("camera image is fully black")
            return None
        self._black_frames = 0
        ok, buf = self._cv2.imencode(
            ".jpg", frame, [int(self._cv2.IMWRITE_JPEG_QUALITY), self._quality]
        )
        return buf.tobytes() if ok else None

    def close(self) -> None:
        self._cap.release()


class RtspSource:
    """Network camera (RTSP, or any URL FFmpeg can open, e.g. an HTTP MJPEG
    stream). Credentials go into the URL because that is the only form
    OpenCV/FFmpeg accept; `repr()` and every error string are redacted.
    """

    def __init__(
        self,
        url: str,
        user: str = "",
        password: str = "",
        transport: str = "tcp",
        quality: int = 80,
    ):
        if transport and transport != "tcp":
            # Honour an explicit UDP request; default stays TCP (set in _import_cv2).
            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS", f"rtsp_transport;{transport}|timeout;5000000"
            )
        cv2 = _import_cv2()
        self._cv2 = cv2
        self._quality = quality
        # Messages are built from the BARE url only (redacted in case the
        # caller embedded credentials anyway); the credentialed string exists
        # solely to hand to FFmpeg.
        self.display_url = redact_url(url)
        full = with_credentials(url, user, password)
        cap = cv2.VideoCapture(full, cv2.CAP_FFMPEG)
        del full
        if not cap.isOpened():
            cap.release()
            raise CameraOpenError(f"could not open {self.display_url}")
        self._cap = cap
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    def __repr__(self) -> str:
        return f"RtspSource({self.display_url})"

    def read_jpeg(self) -> bytes | None:
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None
        ok, buf = self._cv2.imencode(
            ".jpg", frame, [int(self._cv2.IMWRITE_JPEG_QUALITY), self._quality]
        )
        return buf.tobytes() if ok else None

    def close(self) -> None:
        self._cap.release()


def probe_camera_indexes(candidates: range = range(0, 5)) -> list[int]:
    """Which indexes open? Used by `kona cameras` so nobody guesses."""
    cv2 = _import_cv2()

    found: list[int] = []
    for i in candidates:
        cap = cv2.VideoCapture(i, getattr(cv2, "CAP_DSHOW", 0))
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found


# --- Fake source -----------------------------------------------------------
# A real 32x32 JPEG (dark grey with a teal block) encoded once by OpenCV and
# embedded here, so the fake needs neither OpenCV nor Pillow at runtime.
# Each frame gets a COM (comment) segment carrying a counter, so consecutive
# frames differ byte-wise while decoders show the same still image.

_BASE_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb0043000d090a0b0a080d0b0a0b0e0e0d0f13201513121213271c"
    "1e17202e2931302e292d2c333a4a3e333646372c2d405741464c4e525352323e5a615a50604a51524fffdb0043010e0e"
    "0e131113261515264f352d354f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f4f"
    "4f4f4f4f4f4f4f4f4f4f4f4f4f4fffc00011080020002003012200021101031101ffc4001f0000010501010101010100"
    "000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d010203000411051221"
    "31410613516107227114328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a"
    "434445464748494a535455565758595a636465666768696a737475767778797a838485868788898a9293949596979899"
    "9aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1"
    "f2f3f4f5f6f7f8f9faffc4001f0100030101010101010101010000000000000102030405060708090a0bffc400b51100"
    "020102040403040705040400010277000102031104052131061241510761711322328108144291a1b1c109233352f015"
    "6272d10a162434e125f11718191a262728292a35363738393a434445464748494a535455565758595a63646566676869"
    "6a737475767778797a82838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4"
    "c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda000c03010002110311003f00e2"
    "68a2ba0ad210e730af5fd95b4bdce7e8ae82b9fa270e40a15fdadf4b582ba0ae7e8a213e40af43dadb5b58e82b9fa28a"
    "273e70a143d95f5bdcffd9"
)


# Synthetic scene for the steerable fake. Wider than the viewport so there
# is somewhere to pan to, with landmarks at intervals so movement is
# obvious at a glance.
SCENE_SIZE = (1600, 700)  # width, height
VIEW_SIZE = (480, 270)  # 16:9 viewport cropped out of the scene


def _render_scene():
    """The room the fake camera looks at. Built once, deterministic."""
    import cv2
    import numpy as np

    w, h = SCENE_SIZE
    scene = np.zeros((h, w, 3), np.uint8)

    # Wall: vertical gradient. Floor: flat, below the horizon.
    horizon = int(h * 0.62)
    for y in range(horizon):
        shade = 78 + int(52 * (y / horizon))
        scene[y, :] = (shade - 12, shade - 6, shade)
    scene[horizon:, :] = (62, 80, 100)
    cv2.line(scene, (0, horizon), (w, horizon), (95, 110, 125), 2, cv2.LINE_AA)

    # Landmarks along the wall so panning is unmistakable.
    marks = [
        (200, (74, 122, 201), "window"),
        (520, (120, 190, 140), "plant"),
        (900, (150, 150, 160), "door"),
        (1300, (90, 170, 220), "shelf"),
    ]
    for x, color, kind in marks:
        if kind == "window":
            cv2.rectangle(scene, (x - 90, 90), (x + 90, 300), color, -1, cv2.LINE_AA)
            cv2.line(scene, (x, 90), (x, 300), (30, 40, 55), 3, cv2.LINE_AA)
        elif kind == "plant":
            cv2.circle(scene, (x, horizon - 90), 62, color, -1, cv2.LINE_AA)
            cv2.rectangle(scene, (x - 14, horizon - 40), (x + 14, horizon), (60, 80, 110), -1)
        elif kind == "door":
            cv2.rectangle(scene, (x - 80, 60), (x + 80, horizon), color, -1, cv2.LINE_AA)
        else:
            for i in range(3):
                y = 140 + i * 70
                cv2.rectangle(scene, (x - 100, y), (x + 100, y + 16), color, -1, cv2.LINE_AA)

    # A dog bed on the floor, because that is what we are all here for.
    cv2.ellipse(scene, (760, horizon + 46), (150, 58), 0, 0, 360, (70, 95, 165), -1, cv2.LINE_AA)
    cv2.ellipse(scene, (760, horizon + 40), (112, 40), 0, 0, 360, (95, 125, 200), -1, cv2.LINE_AA)
    return scene


class FakeSource:
    """Deterministic frames, no hardware.

    With no `control` this returns the same tiny embedded JPEG it always
    has, needing neither OpenCV nor a font. Given a control, it renders a
    viewport onto a wider synthetic scene offset by the control's pan and
    tilt, so the on-screen pad actually moves the picture and the control
    surface can be judged before hardware exists.
    """

    def __init__(self, fps: int = 15, fail_after: int | None = None, control=None):
        self._n = 0
        self._interval = 1.0 / fps
        self._fail_after = fail_after
        self._control = control
        self._scene = None
        self.closed = False

    def _steered_jpeg(self) -> bytes | None:
        import cv2

        if self._scene is None:
            self._scene = _render_scene()
        pan, tilt = self._control.position()
        vw, vh = VIEW_SIZE
        sh, sw = self._scene.shape[:2]
        # -1..1 maps across the slack between the scene and the viewport.
        x = int(round((pan + 1) / 2 * (sw - vw)))
        y = int(round((tilt + 1) / 2 * (sh - vh)))
        view = self._scene[y : y + vh, x : x + vw]
        ok, buf = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes() if ok else None

    def read_jpeg(self) -> bytes | None:
        if self._fail_after is not None and self._n >= self._fail_after:
            return None
        self._n += 1
        if self._control is not None:
            frame = self._steered_jpeg()
            if frame is None:
                return None
        else:
            frame = _BASE_JPEG
        comment = f"kona-fake-frame-{self._n}".encode()
        seg = b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
        frame = frame[:2] + seg + frame[2:]  # COM right after SOI
        time.sleep(self._interval)
        return frame

    def close(self) -> None:
        self.closed = True


def frame_number(jpeg: bytes) -> int | None:
    """Recover FakeSource's counter from a frame (test helper)."""
    marker = b"kona-fake-frame-"
    i = jpeg.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    digits = bytearray()
    while j < len(jpeg) and 48 <= jpeg[j] <= 57:
        digits.append(jpeg[j])
        j += 1
    return int(digits.decode()) if digits else None
