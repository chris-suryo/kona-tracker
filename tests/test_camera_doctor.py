"""The diagnostic that answers *why* the picture is black.

`camera-test` is a health check and fails on an unusable picture, which is
correct and leaves you with no way to tell a closed shutter from a dark
room. Those need opposite fixes, so the doctor reports pixels instead of
judging them.
"""

import numpy as np
import pytest
from typer.testing import CliRunner

from kona_tracker.camera.source import inspect_cameras
from kona_tracker.cli import app


class FakeCap:
    """Stands in for cv2.VideoCapture with a scripted frame."""

    def __init__(self, frame, opened=True):
        self._frame = frame
        self._opened = opened
        self.released = False

    def isOpened(self):  # noqa: N802 - mirrors the OpenCV name
        return self._opened

    def get(self, prop):
        return {3: 1280, 4: 720}.get(prop, 0)

    def read(self):
        if self._frame is None:
            return False, None
        return True, self._frame

    def release(self):
        self.released = True


class FakeCv2:
    CAP_DSHOW = 700
    CAP_MSMF = 1400
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self, frames_by_index):
        self._frames = frames_by_index
        self.caps: list[FakeCap] = []

    def VideoCapture(self, index, backend=None):  # noqa: N802 - mirrors OpenCV
        frame = self._frames.get(index)
        cap = FakeCap(frame, opened=index in self._frames)
        self.caps.append(cap)
        return cap


def black():
    return np.zeros((8, 8, 3), dtype=np.uint8)


def dark_but_noisy():
    rng = np.random.default_rng(0)
    return rng.integers(0, 6, size=(8, 8, 3), dtype=np.uint8)


def real_picture():
    rng = np.random.default_rng(1)
    return rng.integers(40, 200, size=(8, 8, 3), dtype=np.uint8)


def test_all_zero_pixels_are_not_a_dark_room():
    """The distinction the whole diagnostic exists for.

    A closed shutter gives pixels that are identically zero. A real sensor in
    an unlit room still has read noise. Same "it looks black", opposite fix.
    """
    shutter = inspect_cameras(range(0, 1), 3, FakeCv2({0: black()}))
    assert {r.verdict for r in shutter} == {"all-zero"}
    assert all(r.stats.maximum == 0 and r.stats.stddev == 0 for r in shutter)
    assert "shutter closed" in shutter[0].detail

    unlit = inspect_cameras(range(0, 1), 3, FakeCv2({0: dark_but_noisy()}))
    assert {r.verdict for r in unlit} == {"very dark"}
    assert all(r.stats.stddev > 0 for r in unlit)
    assert "Turn a light on" in unlit[0].detail


def test_a_real_picture_is_called_usable():
    reports = inspect_cameras(range(0, 1), 3, FakeCv2({0: real_picture()}))
    assert {r.verdict for r in reports} == {"usable"}
    assert all(r.width == 1280 and r.height == 720 and r.frames == 3 for r in reports)


def test_every_index_and_backend_is_tried_and_devices_are_released():
    cv2 = FakeCv2({2: real_picture()})
    reports = inspect_cameras(range(0, 3), 2, cv2)
    assert len(reports) == 9, "3 indexes x 3 backends"
    assert {r.backend for r in reports} == {"CAP_DSHOW", "CAP_MSMF", "default"}
    assert [r.verdict for r in reports if r.index == 2] == ["usable"] * 3
    assert all(r.verdict == "no device" for r in reports if r.index != 2)
    assert all(c.released for c in cv2.caps), "a probe must never hold the camera open"


def test_a_diagnostic_never_raises():
    """Whatever OpenCV does, the table still prints. A diagnostic that dies
    on the interesting case is worse than none."""

    class Exploding(FakeCv2):
        def VideoCapture(self, index, backend=None):  # noqa: N802
            raise RuntimeError("MSMF backend exploded")

    reports = inspect_cameras(range(0, 2), 2, Exploding({}))
    assert len(reports) == 6
    assert all(r.verdict == "error" for r in reports)
    assert "MSMF backend exploded" in reports[0].detail

    opened_but_silent = inspect_cameras(range(0, 1), 2, FakeCv2({0: None}))
    assert opened_but_silent == [] or all(r.frames == 0 for r in opened_but_silent)


@pytest.mark.parametrize(
    "frame,expected_exit,expected_text",
    [
        (real_picture(), 0, "Set KONA_CAMERA_INDEX=0"),
        (black(), 1, "shutter closed"),
        (dark_but_noisy(), 1, "Turn a light on"),
    ],
)
def test_the_command_says_what_to_do_next(monkeypatch, frame, expected_exit, expected_text):
    import kona_tracker.camera.source as source

    monkeypatch.setattr(source, "_import_cv2", lambda: FakeCv2({0: frame}))
    result = CliRunner().invoke(app, ["camera-doctor", "--indexes", "1", "--frames", "2"])
    assert result.exit_code == expected_exit, result.output
    assert expected_text in result.output
    assert "sd" in result.output, "the column that distinguishes the two failures"


def test_the_command_reports_nothing_plugged_in(monkeypatch):
    import kona_tracker.camera.source as source

    monkeypatch.setattr(source, "_import_cv2", lambda: FakeCv2({}))
    result = CliRunner().invoke(app, ["camera-doctor", "--indexes", "2"])
    assert result.exit_code == 1
    assert "another program owns it" in result.output
