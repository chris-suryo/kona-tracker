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
    # Kona's data is behind the same gate as her camera.
    assert client.get("/activity", follow_redirects=False).status_code == 303
    assert client.get("/settings", follow_redirects=False).status_code == 303
    assert client.get("/activity.json", follow_redirects=False).status_code == 303


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


def _app(**kw):
    settings = Settings(passcode="4242", secret="s", lockout_attempts=2, lockout_seconds=60, **kw)
    return create_app(settings, source_factory=lambda: FakeSource(fps=100))


def test_a_forwarded_header_is_ignored_unless_it_is_trusted():
    """Unset by default: a stranger cannot pick their own bucket by sending
    CF-Connecting-IP, and everyone behind one peer address shares one --
    which is the LAN behaviour, and the reason the setting exists."""
    app = _app()
    with TestClient(app) as c:
        for ip in ("203.0.113.1", "203.0.113.2"):
            r = c.post(
                "/login",
                data={"passcode": "0000"},
                headers={"CF-Connecting-IP": ip},
                follow_redirects=False,
            )
            assert r.status_code == 401
        r = c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        assert r.status_code == 429, "two failures under two forged addresses still add up"
    app.state.hub.stop()


def test_a_trusted_proxy_header_gives_each_visitor_their_own_lockout():
    """Behind cloudflared every peer is 127.0.0.1. With the header trusted,
    a stranger locking themselves out does not lock out the household."""
    app = _app(trusted_proxy_header="CF-Connecting-IP")
    with TestClient(app) as c:
        stranger = {"CF-Connecting-IP": "203.0.113.1"}
        sister = {"CF-Connecting-IP": "198.51.100.7"}
        for _ in range(2):
            assert c.post("/login", data={"passcode": "0000"}, headers=stranger).status_code == 401
        assert c.post("/login", data={"passcode": "4242"}, headers=stranger).status_code == 429
        r = c.post("/login", data={"passcode": "4242"}, headers=sister, follow_redirects=False)
        assert r.status_code == 303, "a different visitor is a different bucket"
        # No header at all (a LAN visitor bypassing the tunnel) falls back to
        # the peer address, and that bucket is untouched by the stranger.
        r = c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        assert r.status_code == 303
    app.state.hub.stop()


def test_session_cookie_is_secure_only_when_asked():
    """`secure=True` would break http://192.168.x.x on the LAN -- the browser
    silently stops sending the cookie -- so it is a setting, off by default,
    and the logout must clear the cookie with the same attributes."""
    app = _app()
    with TestClient(app) as c:
        r = login(c)
        assert "secure" not in r.headers["set-cookie"].lower()
        r = c.post("/logout", follow_redirects=False)
        assert "secure" not in r.headers["set-cookie"].lower()
    app.state.hub.stop()

    app = _app(secure_cookies=True)
    with TestClient(app, base_url="https://testserver") as c:
        r = login(c)
        cookie = r.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
        assert c.get("/camera").status_code == 200
        r = c.post("/logout", follow_redirects=False)
        assert "secure" in r.headers["set-cookie"].lower()
    app.state.hub.stop()


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


def test_usb_camera_offers_capture_and_share_but_no_motion_controls(client):
    login(client)
    page = client.get("/camera").text
    assert 'id="capture"' in page and "navigator.share" in page
    assert 'class="ptz"' not in page and "Left corner" not in page


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


def _app_with(model, source="fake"):
    """A client whose camera model decides which controls exist."""
    from kona_tracker.web.app import default_control

    settings = Settings(passcode="4242", secret="s", camera_source=source, camera_model=model)
    control = default_control(settings)
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100), control=control)
    return app, control


def test_the_pad_appears_only_when_something_can_actually_move_the_camera():
    """The invariant: a control appears when the *connected driver* can do
    it, not when the model could in principle. A C225 over RTSP can pan,
    but until TapoControl exists we cannot make it, so no pad — otherwise
    every press 409s and the user gets a dead button."""
    cases = [
        ("c225", "fake", True),  # simulated motors: really movable
        ("c225", "rtsp", False),  # model can pan, no driver written yet
        ("c120", "rtsp", False),  # fixed camera, never
    ]
    for model, source, expected in cases:
        app, _ = _app_with(model, source=source)
        with TestClient(app) as c:
            login(c)
            html = c.get("/camera").text
            assert ('class="ptz"' in html) is expected, (model, source)
            assert ('data-preset="1"' in html) is expected, (model, source)
            assert c.get("/status.json").json()["capabilities"]["ptz"] is expected
        app.state.hub.stop()


def test_an_undriveable_camera_advertises_nothing_but_remembers_the_model():
    from kona_tracker.camera.capabilities import TAPO_PAN_TILT
    from kona_tracker.camera.control import NoControl

    c = NoControl(TAPO_PAN_TILT)
    assert c.capabilities.ptz is False and c.capabilities.presets is False
    assert c.model_capabilities.ptz is True  # kept for status and docs


def test_moving_a_pan_tilt_camera_updates_the_reported_position():
    app, _ = _app_with("c225", source="fake")
    with TestClient(app) as c:
        login(c)
        assert c.get("/status.json").json()["position"] == {"pan": 0.0, "tilt": 0.0}
        moved = c.post("/control/move", data={"pan": "0.4", "tilt": "-0.1"})
        assert moved.status_code == 200 and moved.json() == {"pan": 0.4, "tilt": -0.1}

        status = c.get("/status.json").json()
        assert status["position"]["pan"] == 0.4
        assert status["capabilities"]["ptz"] is True
        assert status["capabilities"]["talk"] is False

        preset = c.post("/control/preset", data={"number": "3"})
        assert preset.status_code == 200 and preset.json()["pan"] == 0.8
    app.state.hub.stop()


def test_a_fixed_camera_refuses_to_move_instead_of_pretending():
    app, _ = _app_with("c120", source="rtsp")
    with TestClient(app) as c:
        login(c)
        r = c.post("/control/move", data={"pan": "0.4"})
        assert r.status_code == 409
        assert "pan or tilt" in r.json()["error"]
        assert c.get("/status.json").json()["capabilities"]["ptz"] is False
    app.state.hub.stop()


def test_control_endpoints_are_behind_the_passcode(client):
    assert (
        client.post("/control/move", data={"pan": "0.4"}, follow_redirects=False).status_code == 303
    )
    assert (
        client.post("/control/preset", data={"number": "1"}, follow_redirects=False).status_code
        == 303
    )


def test_motion_is_opt_in_and_respects_the_accessibility_setting():
    """The polish must never be something a user cannot turn off.

    `@view-transition` is what makes a multi-page app feel like an app, and
    the animations are decoration on top of markup that is already complete —
    but both have to disappear for anyone who asked their phone for less
    motion.
    """
    from kona_tracker.web.app import HERE

    css = (HERE / "static" / "app.css").read_text(encoding="utf-8")
    assert "@view-transition { navigation: auto; }" in css
    for name in ("kona-header", "kona-tab", "kona-frame", "kona-hero"):
        assert css.count(f"view-transition-name: {name}") == 1, "names must stay unique"

    reduce = css[css.index("@media (prefers-reduced-motion: reduce)") :]
    assert "@view-transition { navigation: none; }" in reduce
    assert ".dial .val, .stat { animation: none; }" in reduce


def test_leaflet_is_vendored_and_is_the_exact_release_the_page_used_to_pin():
    """A CDN is a dependency, and one that was measured to leave a blank
    coloured box when unreachable. The copies in static/ are the npm
    release: these are the SRI hashes activity.html carried for unpkg."""
    import base64
    import hashlib

    from kona_tracker.web.app import HERE

    vendored = HERE / "static" / "leaflet"
    expected = {
        "leaflet.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
        "leaflet.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=",
    }
    for name, sha in expected.items():
        digest = hashlib.sha256((vendored / name).read_bytes()).digest()
        assert base64.b64encode(digest).decode() == sha, f"{name} is not Leaflet 1.9.4 as published"
    assert (vendored / "LICENSE").read_text(encoding="utf-8").startswith("BSD 2-Clause")
    for image in ("layers.png", "layers-2x.png", "marker-icon.png"):
        assert (vendored / "images" / image).exists(), "leaflet.css references these"


def test_the_map_page_loads_no_third_party_script(client):
    login(client)
    page = client.get("/activity?preview=1").text
    assert "unpkg.com" not in page and "/static/leaflet/leaflet.js" in page
    assert client.get("/static/leaflet/leaflet.css").status_code == 200
    assert client.get("/static/leaflet/images/layers.png").status_code == 200
