"""Prove the OpenCV + FFmpeg *network* path with no camera: a tiny HTTP MJPEG
server in a thread serves FakeSource frames; RtspSource opens it by URL (any
URL FFmpeg understands works the same way as rtsp://) and reads real frames.
Skipped where the OpenCV wheel is unavailable."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kona_tracker.camera.source import FakeSource

cv2 = pytest.importorskip("cv2")


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
    assert "hunter2" not in str(exc.value) and "***@127.0.0.1" in str(exc.value)
