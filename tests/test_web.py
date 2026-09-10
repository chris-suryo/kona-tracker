import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.web.app import create_app
from kona_tracker.web.auth import COOKIE_NAME
from kona_tracker.web.settings import Settings


@pytest.fixture
def client():
    settings = Settings(
        passcode="4242", secret="test-secret", lockout_attempts=3, lockout_seconds=60
    )
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        yield c
    app.state.hub.stop()


def login(client, code="4242"):
    return client.post("/login", data={"passcode": code}, follow_redirects=False)


def test_unauthenticated_html_redirects_to_login(client):
    r = client.get("/camera", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert client.get("/login").status_code == 200


def test_unauthenticated_stream_is_401_not_redirect(client):
    assert client.get("/stream.mjpg", follow_redirects=False).status_code == 401
    assert client.get("/snapshot.jpg", follow_redirects=False).status_code == 401
    assert client.get("/status.json", follow_redirects=False).status_code == 303


def test_snapshot_shows_placeholder_with_honest_state_when_camera_fails():
    from kona_tracker.camera.placeholder import NO_SIGNAL_JPEG

    def boom():
        raise RuntimeError("could not open rtsp://kona:hunter2@10.0.0.9:554/stream1")

    settings = Settings(passcode="4242", secret="s", stale_seconds=0.2, hang_seconds=0.5)
    app = create_app(settings, source_factory=boom)
    with TestClient(app) as c:
        login(c)
        snap = c.get("/snapshot.jpg")
        assert snap.status_code == 200 and snap.content == NO_SIGNAL_JPEG
        assert snap.headers["x-kona-state"] in ("disconnected", "connecting")  # never 'live'
        status = c.get("/status.json").json()
        assert "hunter2" not in status["last_error"] and "***@10.0.0.9" in status["last_error"]
    app.state.hub.stop()


def test_wrong_passcode_then_right_passcode(client):
    r = login(client, "0000")
    assert r.status_code == 401 and COOKIE_NAME not in r.cookies
    r = login(client)
    assert r.status_code == 303 and r.headers["location"] == "/camera"
    assert COOKIE_NAME in r.cookies
    assert client.get("/camera").status_code == 200
    assert "Camera" in client.get("/activity").text
    assert client.get("/login", follow_redirects=False).status_code == 303  # already in


def test_lockout_after_repeated_failures(client):
    for _ in range(3):
        assert login(client, "0000").status_code == 401
    assert login(client, "4242").status_code == 429  # even the right code waits


def test_forged_cookie_is_rejected(client):
    client.cookies.set(COOKIE_NAME, "ok.forged.signature")
    assert client.get("/camera", follow_redirects=False).status_code == 303


def test_snapshot_and_stream_with_cookie(client):
    login(client)
    snap = client.get("/snapshot.jpg")
    assert snap.status_code == 200 and snap.headers["content-type"] == "image/jpeg"
    assert snap.content.startswith(b"\xff\xd8")
    assert snap.headers["x-kona-state"] == "live"
    status = client.get("/status.json").json()
    assert status["state"] == "live" and status["opens"] == 1 and status["last_error"] is None

    # Starlette's TestClient runs the app to completion, so cap the stream.
    r = client.get("/stream.mjpg", params={"frames": 3})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert r.content.count(b"--kona-frame\r\nContent-Type: image/jpeg") == 3


def test_logout_clears_cookie(client):
    login(client)
    r = client.post("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert client.get("/camera", follow_redirects=False).status_code == 303


def test_manifest_and_icons_are_public(client):
    """Install must work before login, so these cannot sit behind the gate."""
    r = client.get("/static/manifest.webmanifest", follow_redirects=False)
    assert r.status_code == 200
    manifest = r.json()
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/camera"
    srcs = {i["src"] for i in manifest["icons"]}
    assert "/static/icon-192.png" in srcs and "/static/icon-512.png" in srcs
    assert any(i.get("purpose") == "maskable" for i in manifest["icons"])

    for src in sorted(srcs) + ["/static/icon-180.png", "/static/favicon-32.png"]:
        icon = client.get(src, follow_redirects=False)
        assert icon.status_code == 200, src
        assert icon.headers["content-type"] == "image/png", src
        assert icon.content.startswith(b"\x89PNG"), src


def test_pages_link_the_manifest_and_apple_icon(client):
    login(client)
    html = client.get("/camera").text
    assert '<link rel="manifest" href="/static/manifest.webmanifest">' in html
    assert '<link rel="apple-touch-icon" href="/static/icon-180.png">' in html
    assert '<meta name="apple-mobile-web-app-title" content="Kona">' in html
    # The standalone launch depends on this one; it predates the manifest.
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
