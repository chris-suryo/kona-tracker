"""Hub behaviour under a scripted source: normal streaming, dropped reads,
exceptions, a hung read, and the stale/disconnected placeholder."""

import asyncio
import threading
import time

import pytest

from kona_tracker.camera.hub import (
    BOUNDARY,
    CONNECTING,
    DISCONNECTED,
    IDLE,
    LIVE,
    STALE,
    CameraHub,
)
from kona_tracker.camera.placeholder import NO_SIGNAL_JPEG
from kona_tracker.camera.source import FakeSource, frame_number


class ScriptedSource:
    """Plays a script per read: int n -> n good frames; None -> empty read;
    Exception instance -> raise; ('block', s) -> hang for s seconds;
    'forever' -> hang until released (simulates a stuck C call)."""

    def __init__(self, script, fps=100):
        self._script = list(script)
        self._inner = FakeSource(fps=fps)
        self.closed = False
        self.release = threading.Event()

    def read_jpeg(self):
        if not self._script:
            return self._inner.read_jpeg()
        step = self._script[0]
        if isinstance(step, int) and step > 0:
            self._script[0] = step - 1
            if self._script[0] == 0:
                self._script.pop(0)
            return self._inner.read_jpeg()
        self._script.pop(0)
        if step is None:
            return None
        if isinstance(step, Exception):
            raise step
        if step == "forever":
            self.release.wait()
            return None
        if isinstance(step, tuple) and step[0] == "block":
            time.sleep(step[1])
            return None
        raise ValueError(step)

    def close(self):
        self.closed = True


def make_hub(scripts, **kw):
    """Each connection attempt pops the next script; records sources."""
    sources = []
    scripts = list(scripts)

    def open_source():
        script = scripts.pop(0) if scripts else []
        if isinstance(script, Exception):
            raise script
        s = ScriptedSource(script)
        sources.append(s)
        return s

    defaults = dict(
        idle_stop_seconds=0.2,
        stale_after=0.3,
        hang_after=0.6,
        max_misses=3,
        backoff_base=0.05,
        backoff_max=0.2,
    )
    defaults.update(kw)
    return CameraHub(open_source, **defaults), sources


def wait_for(pred, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def collect(hub, n):
    async def go():
        out = []
        async for chunk in hub.mjpeg(max_frames=n):
            out.append(chunk)
        return out

    return asyncio.run(go())


def part_state(chunk: bytes) -> str:
    head = chunk.split(b"\r\n\r\n", 1)[0].decode()
    return next(line.split(": ", 1)[1] for line in head.split("\r\n") if line.startswith("X-Kona"))


def part_body(chunk: bytes) -> bytes:
    return chunk.split(b"\r\n\r\n", 1)[1][:-2]


def test_snapshot_live_then_idle_stop():
    hub, sources = make_hub([[]])
    assert hub.status()["state"] == IDLE
    frame, state = hub.snapshot()
    assert state == LIVE and frame_number(frame) == 1
    assert hub.status()["state"] == LIVE
    assert wait_for(lambda: sources[0].closed and hub.status()["state"] == IDLE)
    assert hub.opens == 1 and hub.reconnects == 0


def test_two_viewers_share_one_source_and_get_distinct_frames():
    hub, _ = make_hub([[]])

    async def both():
        async def read(n):
            return [c async for c in hub.mjpeg(max_frames=n)]

        return await asyncio.gather(read(3), read(3))

    a, b = asyncio.run(both())
    assert hub.opens == 1
    for chunks in (a, b):
        nums = [frame_number(part_body(c)) for c in chunks]
        assert nums == sorted(nums) and len(set(nums)) == 3, nums
        assert all(part_state(c) == LIVE for c in chunks)
        assert chunks[0].startswith(f"--{BOUNDARY}\r\nContent-Type: image/jpeg".encode())
    hub.stop()


def test_open_failure_gives_placeholder_and_redacted_error_then_reconnects():
    boom = RuntimeError("could not open rtsp://kona:hunter2@10.0.0.9:554/stream1")
    # backoff longer than the snapshot wait, so the first look sees the failure
    hub, sources = make_hub([boom, []], backoff_base=0.5, backoff_max=0.5)
    frame, state = hub.snapshot(timeout=0.2)
    assert frame == NO_SIGNAL_JPEG and state == DISCONNECTED
    assert "hunter2" not in hub.status()["last_error"]
    assert "rtsp://***@10.0.0.9" in hub.status()["last_error"]
    # Nobody watching -> no reconnecting for nobody: the hub goes idle...
    assert wait_for(lambda: hub.status()["state"] == IDLE)
    # ...and the next viewer triggers a fresh attempt, which succeeds.
    hub._add_viewer()
    try:
        assert wait_for(lambda: hub.status()["state"] == LIVE)
        assert len(sources) == 1 and hub.opens == 1
    finally:
        hub._remove_viewer()
        hub.stop()


def test_a_fully_black_camera_is_not_reported_as_live():
    from kona_tracker.camera.source import CameraFrameError

    hub, _ = make_hub(
        [[CameraFrameError("camera image is fully black")]],
        backoff_base=0.5,
        backoff_max=0.5,
    )
    frame, state = hub.snapshot(timeout=0.2)
    status = hub.status()
    assert frame == NO_SIGNAL_JPEG and state == DISCONNECTED
    assert status["last_error_kind"] == "black_frame"
    hub.stop()


def test_exception_mid_stream_reconnects_and_resumes():
    # backoff (0.5 s) exceeds stale_after (0.3 s), so the gap becomes visible;
    # with a shorter backoff the reconnect is seamless and every part is LIVE.
    hub, sources = make_hub([[2, OSError("connection reset")], []], backoff_base=0.5)
    chunks = collect(hub, 6)
    states = [part_state(c) for c in chunks]
    assert states[:2] == [LIVE, LIVE]
    assert DISCONNECTED in states or STALE in states, states
    assert states[-1] == LIVE  # back on real frames
    assert len(sources) == 2 and sources[0].closed
    assert "connection reset" in hub.status()["last_error"]
    hub.stop()


def test_hung_read_is_abandoned_and_replaced():
    hub, sources = make_hub([[1, "forever"], []], hang_after=0.4)
    chunks = collect(hub, 5)
    states = [part_state(c) for c in chunks]
    assert states[0] == LIVE
    assert states[-1] == LIVE
    assert len(sources) == 2, "supervisor must have started a second generation"
    assert not sources[0].closed, "the stuck reader is abandoned, not joined"
    sources[0].release.set()  # let the stuck thread return...
    assert wait_for(lambda: sources[0].closed), "...and it releases the source on return"
    hub.stop()


def test_stale_placeholder_carries_state_and_real_frame_returns():
    # A stall (0.5 s), not a hang: hang_after is raised so the reader is kept.
    hub, _ = make_hub([[1, None, None, ("block", 0.5), 3]], max_misses=10, hang_after=2.0)
    chunks = collect(hub, 4)
    states = [part_state(c) for c in chunks]
    assert states[0] == LIVE
    assert STALE in states
    assert part_body(chunks[states.index(STALE)]) == NO_SIGNAL_JPEG
    assert states[-1] == LIVE
    hub.stop()


def test_status_transitions():
    hub, sources = make_hub([["forever"], [], []], hang_after=0.4)
    hub._add_viewer()
    try:
        assert wait_for(lambda: hub.status()["state"] == CONNECTING, 1)
        assert wait_for(lambda: hub.status()["state"] in (DISCONNECTED, LIVE), 2)
        assert wait_for(lambda: hub.status()["state"] == LIVE, 3)
        status = hub.status()
        assert status["reconnects"] >= 1 and status["generation"] >= 2
        assert status["last_frame_age"] is not None
    finally:
        hub._remove_viewer()
        for s in sources:
            s.release.set()
        hub.stop()


def test_backoff_grows_and_resets():
    hub, _ = make_hub(
        [RuntimeError("a"), RuntimeError("b"), RuntimeError("c"), []],
        backoff_base=0.05,
        backoff_max=0.1,
    )
    hub._add_viewer()
    try:
        t0 = time.monotonic()
        assert wait_for(lambda: hub.status()["state"] == LIVE, 5)
        elapsed = time.monotonic() - t0
        assert hub.reconnects == 3
        assert elapsed >= 0.05 + 0.1 + 0.1 - 0.02, elapsed  # base, then capped
        assert hub._backoff == 0.05  # reset on first good frame
    finally:
        hub._remove_viewer()
        hub.stop()


@pytest.mark.parametrize("n", [1, 2])
def test_stop_ends_streams(n):
    hub, _ = make_hub([["forever"]])

    async def go():
        gen = hub.mjpeg()
        first = await gen.__anext__()  # placeholder after stale_after
        assert part_state(first) in (CONNECTING, DISCONNECTED, STALE)
        hub.stop()
        rest = [c async for c in gen]
        return rest

    assert asyncio.run(go()) == []


def test_steering_the_fake_source_actually_changes_the_picture():
    """The pad is only judgeable if pressing it moves the image, so this
    decodes two frames and asserts they differ."""
    cv2 = pytest.importorskip("cv2")
    import numpy as np

    from kona_tracker.camera.control import FakeControl

    control = FakeControl()
    source = FakeSource(fps=200, control=control)

    def frame():
        raw = source.read_jpeg()
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        return img

    centre = frame()
    control.move(pan=-0.9)
    left = frame()
    control.goto_preset(3)
    right = frame()

    assert centre.shape == left.shape == right.shape
    assert not np.array_equal(centre, left), "panning left changed nothing"
    assert not np.array_equal(left, right), "jumping to a preset changed nothing"


def test_the_fake_source_without_a_control_is_unchanged():
    """The tiny embedded JPEG path must survive: it is what lets the fake
    run with no OpenCV at all."""
    plain = FakeSource(fps=200).read_jpeg()
    assert plain.startswith(b"\xff\xd8") and len(plain) < 2000
    assert frame_number(plain) == 1


def test_noise_not_brightness_separates_a_dead_camera_from_a_dark_room():
    """A wedged USB device (measured: mean 0.00, sd 0.00) and a closed
    shutter hand back identical pixels. A real sensor in a dark room has
    read noise. "CHECK CAMERA" when the truth is "the light is off" is the
    confident-wrong output this project refuses, and night is when a
    sleeping dog is most worth looking at. The dark-room frame here is
    synthetic; the real one is still owed a lights-off evening."""
    np = pytest.importorskip("numpy")
    from kona_tracker.camera.source import frame_is_unusable

    black = np.zeros((480, 640, 3), dtype=np.uint8)
    assert frame_is_unusable(black), "all zero: wedged or covered"
    black[0, 0, 0] = 240  # one hot pixel is not a picture either
    assert frame_is_unusable(black)
    flat = np.full((480, 640, 3), 2, dtype=np.uint8)
    assert frame_is_unusable(flat), "no sensor has zero noise"
    rng = np.random.default_rng(1)
    dark_room = rng.integers(0, 6, size=(480, 640, 3), dtype=np.uint8)  # mean ~2.5, sd ~1.7
    assert not frame_is_unusable(dark_room), "dark but noisy is a real, dark picture"
    lit = np.full((480, 640, 3), 90, dtype=np.uint8)
    assert not frame_is_unusable(lit), "plainly lit frames skip the noise check"
