"""Prove the OpenCV + FFmpeg *network* path with no camera: a tiny HTTP MJPEG
server in a thread serves FakeSource frames; RtspSource opens it by URL (any
URL FFmpeg understands works the same way as rtsp://) and reads real frames.
Skipped where the OpenCV wheel is unavailable."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np
import pytest

from kona_tracker.camera.source import FakeSource, _import_cv2

try:
    _import_cv2()  # sets the FFmpeg env (tcp, timeout, quiet logs) before the import
except ImportError:  # pragma: no cover - wheel unavailable on this platform
    pytest.skip("OpenCV wheel unavailable", allow_module_level=True)


class MjpegHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        src = FakeSource(fps=30)
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            for _ in range(60):
                jpeg = src.read_jpeg()
                self.wfile.write(
                    b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                    + str(len(jpeg)).encode()
                    + b"\r\n\r\n"
                    + jpeg
                    + b"\r\n"
                )
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


@pytest.fixture
def mjpeg_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MjpegHandler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/stream"
    srv.shutdown()


def test_rtsp_source_reads_frames_from_a_network_stream(mjpeg_server):
    from kona_tracker.camera.source import RtspSource

    src = RtspSource(mjpeg_server)
    try:
        assert (src.width, src.height) == (32, 32)
        frames = [src.read_jpeg() for _ in range(3)]
        assert all(f and f.startswith(b"\xff\xd8") for f in frames)
        assert "127.0.0.1" in repr(src)
    finally:
        src.close()


def test_rtsp_source_open_failure_is_redacted():
    from kona_tracker.camera.source import CameraOpenError, RtspSource

    # a closed port: connection refused fast, no hang
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(CameraOpenError) as exc:
        RtspSource(f"http://127.0.0.1:{port}/x", "kona", "hunter2")
    # message is built from the bare URL: host visible, credentials absent
    assert "hunter2" not in str(exc.value) and "kona" not in str(exc.value)
    assert "127.0.0.1" in str(exc.value)


def test_rtsp_source_error_never_carries_credentials_even_for_odd_urls():
    from kona_tracker.camera.source import CameraOpenError, RtspSource

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    for url, user, pw in [
        (f"http://127.0.0.1:{port}/x", "kona", "sec/ret"),
        (f"http://kona:sec/ret@127.0.0.1:{port}/x", "", ""),  # embedded, raw slash
    ]:
        with pytest.raises(CameraOpenError) as exc:
            RtspSource(url, user, pw)
        assert "sec" not in str(exc.value), str(exc.value)


def test_rtsp_frames_wider_than_the_cap_are_shrunk_before_encoding(mjpeg_server):
    """The Tapo's main stream is 2560x1440 and there is no CAP_PROP to ask a
    network camera for less, so the cap has to happen after decode. The
    test stream is 32x32; capping at 16 must deliver 16x16 JPEGs and report
    that size, since it is the size a viewer actually receives."""
    from kona_tracker.camera.source import RtspSource

    cv2 = _import_cv2()
    src = RtspSource(mjpeg_server, max_width=16)
    try:
        assert (src.source_width, src.source_height) == (32, 32)
        assert (src.width, src.height) == (16, 16)
        jpeg = src.read_jpeg()
        assert jpeg and jpeg.startswith(b"\xff\xd8")
        decoded = cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (16, 16)
    finally:
        src.close()


def test_rtsp_cap_never_scales_a_frame_up(mjpeg_server):
    from kona_tracker.camera.source import RtspSource

    cv2 = _import_cv2()
    src = RtspSource(mjpeg_server, max_width=64)
    try:
        assert (src.width, src.height) == (32, 32)
        decoded = cv2.imdecode(np.frombuffer(src.read_jpeg(), dtype=np.uint8), cv2.IMREAD_COLOR)
        assert decoded.shape[:2] == (32, 32)
    finally:
        src.close()


def test_rtsp_cap_keeps_the_aspect_ratio():
    """1440p capped at 1280 wide is 720 tall, not 1440; a squashed dog is
    worse than a big one."""
    from kona_tracker.camera.source import RtspSource

    assert RtspSource._delivered_size(type("S", (), {"_max_width": 1280})(), 2560, 1440) == (
        1280,
        720,
    )
