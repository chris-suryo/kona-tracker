import asyncio
import time

from kona_tracker.camera.hub import BOUNDARY, CameraHub
from kona_tracker.camera.source import FakeSource, frame_number


def test_snapshot_returns_a_frame_and_stops_when_idle():
    sources: list[FakeSource] = []

    def open_source():
        s = FakeSource(fps=100)
        sources.append(s)
        return s

    hub = CameraHub(open_source, idle_stop_seconds=0.1)
    frame = hub.snapshot()
    assert frame and frame_number(frame) == 1
    time.sleep(0.5)
    assert sources[0].closed, "capture thread should stop after the last viewer leaves"
    assert hub.opens == 1


def test_two_viewers_share_one_source_and_get_distinct_frames():
    hub = CameraHub(lambda: FakeSource(fps=100), idle_stop_seconds=0.1)

    async def read(n):
        out = []
        async for chunk in hub.mjpeg(max_frames=n):
            out.append(chunk)
        return out

    async def both():
        return await asyncio.gather(read(3), read(3))

    a, b = asyncio.run(both())
    assert len(a) == 3 and len(b) == 3
    assert hub.opens == 1
    for chunks in (a, b):
        nums = [frame_number(c) for c in chunks]
        assert nums == sorted(nums) and len(set(nums)) == 3, nums
        assert chunks[0].startswith(f"--{BOUNDARY}\r\nContent-Type: image/jpeg".encode())
    hub.stop()


def test_camera_open_failure_surfaces_as_error_not_hang():
    def boom():
        raise RuntimeError("no camera at index 9")

    hub = CameraHub(boom)
    assert hub.snapshot(timeout=2) is None
    assert hub.error and "no camera" in hub.error
