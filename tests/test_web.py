import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource, frame_number
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
        # The reason travels as a short kind, never the message with its host.
        assert snap.headers["x-kona-error"] == "open" and "hunter2" not in str(snap.headers)
        assert "x-kona-frame-age" not in snap.headers, "no frame has ever existed"
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
    with TestClient(app, client=("127.0.0.1", 50000)) as c:
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


def test_a_wifi_visitor_cannot_dodge_the_lockout_by_sending_the_header():
    """Port 8000 stays reachable on the LAN next to the tunnel. A peer that
    is not the tunnel keeps its own address as the key whatever it sends;
    otherwise a fresh header value per guess would mean no lockout."""
    app = _app(trusted_proxy_header="CF-Connecting-IP")
    with TestClient(app, client=("192.168.1.20", 50000)) as c:
        for n in (1, 2):
            r = c.post(
                "/login",
                data={"passcode": "0000"},
                headers={"CF-Connecting-IP": f"10.0.0.{n}"},
                follow_redirects=False,
            )
            assert r.status_code == 401
        r = c.post(
            "/login",
            data={"passcode": "4242"},
            headers={"CF-Connecting-IP": "10.0.0.3"},
            follow_redirects=False,
        )
        assert r.status_code == 429, "two guesses from one Wi-Fi peer, whatever it claims"
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


def test_snapshot_long_poll_returns_the_next_frame_with_identity_headers(client):
    """The phone sends back the seq it has and is held for the one after it:
    one request per frame, with the words about that frame in the same
    response as its pixels."""
    login(client)
    first = client.get("/snapshot.jpg")
    assert first.headers["x-kona-state"] == "live" and first.headers["x-kona-error"] == ""
    seq = int(first.headers["x-kona-seq"])
    assert seq >= 1 and float(first.headers["x-kona-frame-age"]) < 3.0
    second = client.get("/snapshot.jpg", params={"after": seq})
    assert second.status_code == 200 and second.headers["x-kona-state"] == "live"
    assert int(second.headers["x-kona-seq"]) > seq
    assert frame_number(second.content) > frame_number(first.content)


def test_snapshot_after_rejects_garbage_and_stays_behind_the_gate(client):
    assert client.get("/snapshot.jpg?after=5", follow_redirects=False).status_code == 401
    login(client)
    assert client.get("/snapshot.jpg", params={"after": "abc"}).status_code == 422
    assert client.get("/snapshot.jpg", params={"after": -1}).status_code == 422


def test_stream_is_refused_loudly_over_the_cap(client):
    """An abandoned stream used to be a silent worker on the server until
    nothing could start. Past the cap the answer is a 503 that names the
    alternative, and the count is visible in /status.json."""
    from kona_tracker.camera.hub import MAX_STREAMS

    login(client)
    hub = client.app.state.hub
    hub._streams = MAX_STREAMS
    try:
        r = client.get("/stream.mjpg", params={"frames": 1})
        assert r.status_code == 503 and r.headers["retry-after"] == "5"
        assert "snapshot.jpg" in r.text
        assert client.get("/status.json").json()["streams"] == MAX_STREAMS
    finally:
        hub._streams = 0


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
    assert 'id="capture"' in page and 'src="/static/camera.js?v=' in page
    from kona_tracker.web.app import HERE

    assert "navigator.share" in (HERE / "static" / "camera.js").read_text(encoding="utf-8")
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


def test_camera_page_polls_snapshots_and_holds_no_stream(client):
    """A stream held open from the phone is what wedged the Camera tab: an
    abandoned one lived on as a server worker until nothing could start.
    The page now assigns each frame itself from a short request, and reads
    the truth about it from that same response rather than a second poll."""
    from kona_tracker.web.app import HERE

    login(client)
    page = client.get("/camera").text
    assert 'src="/stream.mjpg"' not in page and 'id="cam"' in page
    js = (HERE / "static" / "camera.js").read_text(encoding="utf-8")
    assert "/snapshot.jpg?after=" in js and "X-Kona-Seq" in js
    assert "status.json" not in js, "one source of truth per frame, not two pollers"
    assert "stream.mjpg" not in js


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
    assert ".pull, .pull span, .pull.busy span { transition: none; animation: none; }" in reduce


def test_zoom_is_off_page_wide_but_the_map_still_pinches():
    """Chris asked for zoom off everywhere and reaffirmed it after being told
    the cost: this is a WCAG 1.4.4 failure, made deliberately, on his own
    two-reader app. Pinned here so it can never look like an accident.

    It takes both halves. Chrome and Android honour the viewport meta; iOS
    Safari has ignored `user-scalable` since iOS 10 and needs `gesture*` and
    multi-touch `touchmove` cancelled instead. The map is exempt in both,
    because Leaflet does its own pinch and that must keep working."""
    from kona_tracker.web.app import HERE

    base = (HERE / "templates" / "base.html").read_text(encoding="utf-8")
    assert "user-scalable=no" in base and "maximum-scale=1" in base

    js = (HERE / "static" / "app.js").read_text(encoding="utf-8")
    for event in ("gesturestart", "gesturechange", "gestureend"):
        assert event in js, event
    assert "e.touches.length > 1" in js, "a two-finger drag is not a gesture event"
    assert js.count("{ passive: false }") >= 2, "preventDefault needs a non-passive listener"
    assert js.count("overTheMap(e.target)") == 2, "both paths must exempt the map"
    assert "WCAG 1.4.4" in js, "the trade stays written down where it is made"

    # Double-tap zoom on a control was the other half of the complaint.
    css = (HERE / "static" / "app.css").read_text(encoding="utf-8")
    assert (
        ".seg a, .avatar, .shutter, .pill, .settings-link, .login button, .logout "
        "{ touch-action: manipulation; }"
    ) in css
    assert "touch-action: none" in css.split(".nub {")[1].split("}")[0], "press-and-hold"
    for line in css.splitlines():
        if "touch-action" in line:
            assert "kona-map" not in line and "leaflet" not in line and ".map" not in line


def test_the_map_keeps_its_own_touch_action_from_leaflet():
    """The exemption above is only real if Leaflet still claims the gesture."""
    from kona_tracker.web.app import HERE

    leaflet = (HERE / "static" / "leaflet" / "leaflet.css").read_text(encoding="utf-8")
    # Leaflet stamps these classes on the container when it is handling touch,
    # and takes `touch-action: none` so the browser hands it every gesture.
    # That is what makes pinching the map move the map, not the page.
    block = leaflet.split(".leaflet-container.leaflet-touch-drag.leaflet-touch-zoom {")[1]
    assert "touch-action: none" in block.split("}")[0]


def test_the_windows_hold_asks_for_the_system_but_never_the_display(monkeypatch):
    """Exercises the Windows path from any platform, which is the point.

    Before this, the success path ran only on the Windows CI leg, so a wrong
    assumption about it survived a green local run. Here the call is faked,
    so the flags are pinned everywhere. The display flag is the one that
    matters for the electricity argument: a dark monitor is most of an idle
    desktop's draw, and the whole reason to hold sleep off is that nobody is
    sitting at the PC.
    """
    import ctypes

    from kona_tracker.web import awake

    calls = []

    class FakeKernel:
        def SetThreadExecutionState(self, flags):
            calls.append(flags)
            return 1  # the previous state; anything non-zero means it took

    monkeypatch.setattr(awake.sys, "platform", "win32")
    monkeypatch.setattr(
        ctypes, "windll", type("W", (), {"kernel32": FakeKernel()})(), raising=False
    )

    assert awake.keep_awake() is True
    assert calls == [awake.ES_CONTINUOUS | awake.ES_SYSTEM_REQUIRED]
    assert not calls[0] & 0x00000002, "ES_DISPLAY_REQUIRED: the screen may still sleep"

    assert awake.allow_sleep() is True
    assert calls[1] == awake.ES_CONTINUOUS, "releasing is the bare continuous flag"

    # Windows refusing the request reads as a refusal, not a success.
    class Refuses:
        def SetThreadExecutionState(self, flags):
            return 0

    monkeypatch.setattr(ctypes, "windll", type("W", (), {"kernel32": Refuses()})(), raising=False)
    assert awake.keep_awake() is False


def test_keep_awake_is_opt_in_and_never_pretends_it_worked(capsys):
    """A keep-awake that silently failed is worse than none: it promises the
    page will be reachable while nobody is at the PC, and then is not.

    The expected answer depends on the platform, so the test asks the
    platform rather than assuming one. The first version of this asserted
    False outright and passed happily in a Linux sandbox, because there the
    assumption and the truth coincide; the Windows CI leg is the only place
    the success path runs at all, and it failed the moment it did. Encoding
    "this machine is not Windows" as if it were a fact about the code is the
    same mistake as a mock that answers every query.
    """
    import sys

    from kona_tracker.web.awake import allow_sleep, keep_awake

    on_windows = sys.platform == "win32"

    assert keep_awake() is on_windows, "Windows can hold sleep off; nothing else can"
    assert allow_sleep() is on_windows
    if on_windows:
        allow_sleep()  # never leave a CI runner holding the hold

    settings = Settings(passcode="4242", secret="s", camera_source="fake")
    assert settings.keep_awake is False, "off unless asked"
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert app.state.keeping_awake is False, "never held unless asked for"
    app.state.hub.stop()
    assert "KONA_KEEP_AWAKE" not in capsys.readouterr().err

    app = create_app(
        Settings(passcode="4242", secret="s", camera_source="fake", keep_awake=True),
        source_factory=lambda: FakeSource(fps=100),
    )
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert app.state.keeping_awake is on_windows
    app.state.hub.stop()

    warning = capsys.readouterr().err
    if on_windows:
        assert warning == "" or "KONA_KEEP_AWAKE is set" not in warning, "it worked; stay quiet"
    else:
        # The whole point of the warning: never let a refused hold pass for a
        # working one, or you walk away believing the page will be reachable.
        assert "KONA_KEEP_AWAKE is set" in warning and "may sleep" in warning


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


def test_every_response_carries_the_security_headers(client):
    """Once the URL is public this is a page with a live camera on it: it
    must not be frameable, must not hand OpenStreetMap a referrer, and may
    run only its own scripts. The headers ride the outer middleware so a
    login redirect, an <img> 401 and a static file all get them."""
    from kona_tracker.web.app import SECURITY_HEADERS

    csp = SECURITY_HEADERS["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in csp and "script-src 'self'" in csp
    assert "unsafe-inline" not in csp and "nonce" not in csp
    assert "https://tile.openstreetmap.org" in csp and "data:" in csp
    assert "blob:" in csp, "the Camera tab hands the <img> object URLs; without this it is black"
    assert "https://tiles.stadiamaps.com" in csp, (
        "the optional Stadia basemap; without this every tile is silently blocked"
    )

    responses = [
        client.get("/login"),
        client.get("/camera", follow_redirects=False),  # 303
        client.get("/stream.mjpg", follow_redirects=False),  # 401
        client.get("/static/app.css"),
        client.get("/healthz"),
    ]
    login(client)
    responses += [client.get("/camera"), client.get("/activity"), client.get("/settings")]
    for r in responses:
        for name, value in SECURITY_HEADERS.items():
            assert r.headers.get(name) == value, (r.request.url, name)
    # The avatar route sets nosniff itself; the middleware must not clobber it.
    assert client.get("/avatar.jpg").headers["x-content-type-options"] == "nosniff"


def test_pages_have_no_inline_script_and_no_inline_handlers(client):
    """CSP script-src 'self' would silently kill any of these. The map's
    points travel as a JSON data block, which is data, not script."""
    import re

    login(client)
    for path in ("/login", "/camera", "/activity", "/activity?preview=1", "/settings"):
        page = client.get(path).text
        for tag in re.findall(r"<script\b[^>]*>", page):
            assert 'src="/static/' in tag or 'type="application/json"' in tag, (path, tag)
        assert not re.search(r"\son[a-z]+\s*=", page), path
        assert "javascript:" not in page, path
    preview = client.get("/activity?preview=1").text
    assert '<script type="application/json" id="map-points">' in preview
    assert 'src="/static/map.js?v=' in preview and 'src="/static/app.js?v=' in preview
    assert "data-optional" in preview, "the avatar fallback moved from onerror= to app.js"


def test_healthz_is_public_and_says_only_what_a_pinger_needs(client):
    """Nothing watches the watcher today; an outside uptime ping against
    this is the cheapest honest fix. It is unauthenticated, so it must not
    leak error text or coordinates, and must not touch Fi."""
    r = client.get("/healthz")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok" and data["fi"] == "unconfigured"
    assert data["camera"] in ("idle", "connecting", "live", "stale", "disconnected")
    assert set(data) == {"status", "camera", "camera_error", "fi", "fi_age_s"}


def test_log_dir_writes_a_file_that_outlives_the_console(tmp_path):
    import logging

    log_dir = tmp_path / "logs"
    settings = Settings(passcode="4242", secret="s", camera_source="fake", log_dir=str(log_dir))
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        login(c)
        logging.getLogger("kona_tracker.camera").warning("camera open: a redacted reason")
    app.state.hub.stop()
    text = (log_dir / "kona.log").read_text(encoding="utf-8")
    assert "WARNING kona_tracker.camera: camera open: a redacted reason" in text
    # Detached on shutdown: nothing more lands, and the file is closed.
    logging.getLogger("kona_tracker.camera").warning("after shutdown")
    assert "after shutdown" not in (log_dir / "kona.log").read_text(encoding="utf-8")


def test_settings_page_reports_camera_health_from_the_road(client):
    """camera-doctor must be run at the machine, which is where Chris is not
    when he needs it. The settings page reads the same hub statistics."""
    login(client)
    client.get("/snapshot.jpg")  # wakes the camera
    page = client.get("/settings").text
    assert 'id="camera-settings-title"' in page and "Webcam on this computer" in page
    assert "Delivering frames" in page or "Opening the camera" in page


def test_the_profile_page_is_a_destination_not_a_broken_tab(client):
    """From Chris's screenshot, 2026-09-11: two avatars on one screen, a
    "Profile" eyebrow over a huge "Kona", "Back to Activity" right under an
    Activity tab, a tab bar with nothing selected, and "usb index 0". The
    page is reached from the avatar and left by its own back link, so it
    carries no header to duplicate and no tab to leave unselected."""
    login(client)
    page = client.get("/settings").text
    assert 'class="hdr"' not in page and 'class="seg"' not in page
    assert page.count('src="/avatar.jpg"') == 1
    assert ">Profile<" not in page and "Back to Activity" not in page
    assert 'class="back" href="/activity"' in page
    assert "usb index" not in page and "\u203a" not in page
    # The tabs are still the tabs everywhere else.
    assert 'class="seg"' in client.get("/activity").text


def test_camera_health_words_are_the_doctors_verdicts():
    from kona_tracker.web.views import camera_health

    wedged = camera_health(
        {"state": "disconnected", "last_error_kind": "black_frame", "reconnects": 3}
    )
    assert wedged["state"] == "Not connected" and wedged["live"] is False
    assert "unplug" in wedged["problem"] and wedged["reconnects"] == 3
    live = camera_health({"state": "live", "last_frame_age": 0.4, "last_error_kind": None})
    assert live["live"] and live["last_frame"] == "0 s ago" and live["problem"] is None
    # Unknown words are shown raw, never dressed up as something known.
    odd = camera_health({"state": "weird", "last_error_kind": "newkind"})
    assert odd["state"] == "weird" and odd["problem"] == "newkind"


@pytest.mark.parametrize("kind", ["pending", "unavailable", "partial", "stale", "ok"])
def test_healthz_distinguishes_no_reading_failure_and_partial_data(kind):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from kona_tracker.fi.parse import CollarStatus
    from kona_tracker.fi.service import FiSnapshot

    snapshot = (
        None
        if kind == "pending"
        else FiSnapshot(
            fetched_at=datetime.now(UTC),
            status=None if kind == "unavailable" else CollarStatus(battery_percent=50),
            problem="test failure" if kind in ("unavailable", "partial", "stale") else None,
            stale=kind == "stale",
        )
    )
    app = create_app(
        Settings(passcode="test-only", secret="test-only", camera_source="fake"),
        fi_service=SimpleNamespace(peek=lambda: snapshot),
    )
    with TestClient(app) as c:
        assert c.get("/healthz").json()["fi"] == kind


def test_the_app_hands_the_camera_timings_to_the_hub():
    """create_app used to leave idle_stop_seconds at the hub's default, so
    no setting could change it. Private attributes on purpose: the timings
    are not something /status.json should advertise."""
    settings = Settings(
        passcode="4242", secret="s", camera_idle_seconds=300, camera_reopen_seconds=4
    )
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    assert app.state.hub._idle_stop == 300 and app.state.hub._reopen_cooldown == 4


def test_map_defaults_to_openstreetmap_and_carries_no_key():
    """The fallback is the tested default, not an accident.

    A missing key must never produce a Stadia URL with an empty `api_key=`:
    every tile would 401 and the map would be blank with no error anywhere.
    """
    from kona_tracker.web.views import map_tile_config

    cfg = map_tile_config("osm")
    assert cfg["url"].startswith("https://tile.openstreetmap.org")
    assert "api_key" not in cfg["url"]
    assert cfg["dark"] is False, "OSM raster is light; the CSS filter must still run"

    # Belt and braces: `stadia` without a key is refused at settings load, but
    # if it ever reached here it must fall back rather than emit a blank key.
    assert map_tile_config("stadia", "")["url"].startswith("https://tile.openstreetmap.org")


def test_stadia_config_names_the_style_the_retina_placeholder_and_attribution():
    from kona_tracker.web.views import map_tile_config

    cfg = map_tile_config("stadia", "NOT-A-REAL-KEY")
    assert "alidade_smooth_dark" in cfg["url"]
    assert "{r}" in cfg["url"], "Leaflet's retina placeholder; this is what sharpens it on a phone"
    assert cfg["url"].endswith("?api_key=NOT-A-REAL-KEY")
    assert "Stadia Maps" in cfg["attribution"] and "OpenMapTiles" in cfg["attribution"]
    assert "OpenStreetMap" in cfg["attribution"], "required even on Stadia tiles"
    assert cfg["dark"] is True, "already dark; the CSS filter must not darken it twice"


def test_stadia_selected_without_a_key_is_refused_by_name(tmp_path, monkeypatch):
    """Fail at load, not at the first tile request.

    A blank basemap looks like a bug in this app rather than a missing key,
    and the person who has to diagnose it is the one who set the variable.
    """
    from kona_tracker.web.settings import SettingsError, load_settings

    for key in ("KONA_MAP_TILES", "KONA_STADIA_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text("KONA_PASSCODE=abcdef\nKONA_SECRET=s\nKONA_MAP_TILES=stadia\n", encoding="utf-8")
    try:
        load_settings(env)
    except SettingsError as e:
        assert "KONA_STADIA_API_KEY" in str(e)
    else:
        raise AssertionError("a stadia basemap with no key must not load")

    env.write_text(
        "KONA_PASSCODE=abcdef\nKONA_SECRET=s\nKONA_MAP_TILES=elevation\n", encoding="utf-8"
    )
    try:
        load_settings(env)
    except SettingsError as e:
        assert "osm or stadia" in str(e)
    else:
        raise AssertionError("an unknown basemap name must not load")


def test_the_rendered_page_carries_the_tile_config_as_data_not_code():
    """End-to-end: the pure function being right is not the same as the page
    getting it. The block sits inside the `{% if map_points %}` gate, so a
    map and its tile settings appear and disappear together.
    """
    from kona_tracker.camera.source import FakeSource
    from kona_tracker.web.settings import Settings

    settings = Settings(
        passcode="4242", secret="s", map_tiles="stadia", stadia_api_key="NOT-A-REAL-KEY"
    )
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        body = c.get("/activity?preview=1").text

    assert '<script type="application/json" id="map-config">' in body
    assert "alidade_smooth_dark" in body
    # Data, never code: it must not arrive as an executable script.
    assert "<script>" not in body.split('id="map-config"')[0][-200:]
