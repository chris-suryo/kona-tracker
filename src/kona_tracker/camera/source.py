"""Frame sources: where JPEG frames come from.

`OpenCVSource` is the real webcam (USB on the PC today, the same camera on
the Pi tomorrow). `FakeSource` is a deterministic test pattern so the whole
web app can be exercised with no hardware: in tests, in CI, and in the cloud
sandbox where this code is written. cv2 is imported lazily so nothing but
the real source ever loads the OpenCV wheel.
"""

from __future__ import annotations

import struct
import time
from typing import Protocol


class FrameSource(Protocol):
    def read_jpeg(self) -> bytes | None:
        """Return one JPEG-encoded frame, or None if the camera gave nothing."""
        ...

    def close(self) -> None: ...


class CameraOpenError(RuntimeError):
    """The camera at the requested index could not be opened."""


class OpenCVSource:
    """USB / built-in webcam via OpenCV.

    On Windows, DirectShow (CAP_DSHOW) opens reliably where the default MSMF
    backend sometimes hangs for seconds; we try it first and fall back.
    """

    def __init__(
        self, index: int = 0, width: int = 1280, height: int = 720, fps: int = 15, quality: int = 80
    ):
        import cv2  # lazy: tests and CI never need the wheel loaded

        self._cv2 = cv2
        self._quality = quality
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
    import cv2

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


class FakeSource:
    """Deterministic frames, no hardware."""

    def __init__(self, fps: int = 15, fail_after: int | None = None):
        self._n = 0
        self._interval = 1.0 / fps
        self._fail_after = fail_after
        self.closed = False

    def read_jpeg(self) -> bytes | None:
        if self._fail_after is not None and self._n >= self._fail_after:
            return None
        self._n += 1
        comment = f"kona-fake-frame-{self._n}".encode()
        seg = b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment
        frame = _BASE_JPEG[:2] + seg + _BASE_JPEG[2:]  # COM right after SOI
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
