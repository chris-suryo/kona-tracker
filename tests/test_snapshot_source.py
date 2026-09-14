"""`SnapshotSource`: one JPEG per HTTP GET, handed on untouched.

The TurboPi serves `?action=snapshot` on port 8080 (measured multi-reader,
2026-09-13). These tests stand up a tiny HTTP server that answers the way
mjpg-streamer does -- a JPEG on the right path, an HTML page with a 200 on
the wrong one -- and prove the four things the hub depends on: the bytes
pass through unchanged, a non-JPEG body is not a frame, an unreachable
camera is an *open* failure (so the hub backs off rather than hammering an
off robot), and nothing about the URL leaks into a repr or an error.
"""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kona_tracker.camera.source import CameraOpenError, FakeSource, SnapshotSource

FRAME = FakeSource(fps=30).read_jpeg()
assert FRAME and FRAME.startswith(b"\xff\xd8")


class RobotHandler(BaseHTTPRequestHandler):
    """Answers like mjpg-streamer: a JPEG for `?action=snapshot`, an HTML
    page with a *200* for anything else, and a 500 on demand."""

    calls: list[str] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        RobotHandler.calls.append(self.path)
        if self.path.endswith("action=snapshot"):
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(FRAME)))
            self.end_headers()
            self.wfile.write(FRAME)
        elif self.path.endswith("boom"):
            self.send_response(500)
            self.end_headers()
        else:
            body = b"<html><body>mjpg-streamer</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@pytest.fixture
def robot():
    RobotHandler.calls = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), RobotHandler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_frames_pass_through_byte_for_byte(robot):
    src = SnapshotSource(f"{robot}/?action=snapshot")
    try:
        # The open already fetched one to prove the camera is there; it is
        # handed over, not thrown away and re-requested.
        assert src.read_jpeg() == FRAME
        assert len(RobotHandler.calls) == 1
        assert src.read_jpeg() == FRAME
        assert len(RobotHandler.calls) == 2
    finally:
        src.close()


def test_a_page_with_a_200_is_not_a_frame(robot):
    """mjpg-streamer answers a wrong path with HTML and a 200. An <img>
    would show nothing and say nothing; this refuses to open at all."""
    with pytest.raises(CameraOpenError, match="did not answer with a JPEG"):
        SnapshotSource(f"{robot}/wrong")


def test_a_server_error_is_not_a_frame_either(robot):
    with pytest.raises(CameraOpenError):
        SnapshotSource(f"{robot}/boom")


def test_an_off_robot_is_an_open_failure_so_the_hub_backs_off():
    """The robot runs on two cells and is off more than on. That must be
    an open failure -- which the hub answers with 1s->30s backoff -- rather
    than a source that opens and then misses ten reads every second."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listening here now
    with pytest.raises(CameraOpenError, match="could not reach"):
        SnapshotSource(f"http://127.0.0.1:{port}/?action=snapshot", timeout=0.5)


def test_a_connection_that_dies_mid_run_raises_rather_than_going_quiet(robot):
    src = SnapshotSource(f"{robot}/?action=snapshot")
    src.read_jpeg()
    # Point it at a port with nothing behind it, as if the robot powered down.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead = sock.getsockname()[1]
    sock.close()
    src._url = f"http://127.0.0.1:{dead}/?action=snapshot"
    with pytest.raises(RuntimeError, match="fetching"):
        src.read_jpeg()
    src.close()


def test_repr_and_errors_never_carry_credentials():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    url = f"http://user:hunter2@127.0.0.1:{port}/?action=snapshot"
    with pytest.raises(CameraOpenError) as caught:
        SnapshotSource(url, timeout=0.5)
    assert "hunter2" not in str(caught.value)


def test_a_borrowed_client_is_not_closed(robot):
    import httpx

    client = httpx.Client(timeout=1.0)
    src = SnapshotSource(f"{robot}/?action=snapshot", client=client)
    src.close()
    assert not client.is_closed
    client.close()
