"""Exercise the CLI's real shutdown configuration with an open TCP MJPEG stream."""

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

SERVER = """
import asyncio
import socket
import sys
from pathlib import Path
import uvicorn
from kona_tracker import cli
from kona_tracker.camera.source import FakeSource
from kona_tracker.web import settings

out = Path(sys.argv[1])
settings.load_settings = lambda *a, **k: settings.Settings(
    passcode="test-only", secret="test-only", camera_source="fake")
original_close = FakeSource.close
def close(self):
    original_close(self)
    (out / "released").write_text("yes")
FakeSource.close = close

def run(app, **kwargs):
    assert kwargs["timeout_graceful_shutdown"] == 5
    server = uvicorn.Server(uvicorn.Config(app, **kwargs))
    @app.post("/_stop")
    async def stop():
        server.should_exit = True
        return {"stopping": True}
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    (out / "port").write_text(str(sock.getsockname()[1]))
    asyncio.run(server.serve(sockets=[sock]))
    (out / "stopped").write_text("yes")

uvicorn.run = run
cli.serve(host="127.0.0.1", port=0, env_file=out / "absent.env", fake_camera=True)
"""


def test_cli_shutdown_finishes_with_a_phone_still_streaming(tmp_path: Path):
    script = tmp_path / "server.py"
    script.write_text(SERVER, encoding="utf-8")
    with (tmp_path / "server.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, str(script), str(tmp_path)],
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:
            deadline = time.monotonic() + 15
            while not (tmp_path / "port").exists() and time.monotonic() < deadline:
                assert proc.poll() is None
                time.sleep(0.05)
            port = (tmp_path / "port").read_text()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                while True:
                    try:
                        response = client.post("/login", data={"passcode": "test-only"})
                        assert response.status_code == 303
                        break
                    except httpx.ConnectError:
                        assert time.monotonic() < deadline
                        time.sleep(0.05)
                with client.stream("GET", "/stream.mjpg") as stream:
                    chunks = stream.iter_bytes()
                    assert b"kona-frame" in next(chunks)
                    assert client.post("/_stop").status_code == 200
                    # Retain both stream and iterator; closing either first
                    # would test a disconnected viewer, missing the regression.
                    assert proc.wait(timeout=12) == 0
            assert (tmp_path / "stopped").exists()
            assert (tmp_path / "released").exists(), "camera cleanup must run"
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
