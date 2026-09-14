"""The drive routes: four failures, four answers, and never a 500.

The camera's `/control/move` answers a driver failure with a FastAPI 500 and
a traceback-derived body. On a camera that is ugly; on a route that moves a
physical object it is worse than ugly, because the page cannot tell "the
robot said no" from "the robot is gone" -- and those need different words
and different behaviour from whoever is holding the joystick. These tests
pin that every robot route distinguishes them, and that nothing that could
move the robot exists at all until the safety gateway is configured.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.robot.gateway import RobotGateway
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

TOKEN = "drive-token-value"
ROBOT_URL = "http://10.0.0.3:8080/?action=snapshot"

HEALTHY = {
    "battery_v": 8.01,
    "sonar_mm": 412,
    "driving": False,
    "demo": None,
    "last_command_age_ms": None,
    "low_battery": False,
    "battery_age_ms": 300,
    "demo_detection": True,
}


def healthy(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, **HEALTHY})


def make(handler=None, drive: bool = True, robot: bool = True):
    """An app whose gateway answers however a test needs it to."""
    gateway = None
    if drive:
        gateway = RobotGateway(
            "http://10.0.0.3:9031",
            TOKEN,
            transport=httpx.MockTransport(handler or healthy),
        )
    settings = Settings(
        passcode="4242",
        secret="s" * 20,
        stale_seconds=0.2,
        hang_seconds=0.5,
        robot_snapshot_url=ROBOT_URL if robot else "",
        robot_name="TurboPi",
    )
    return create_app(
        settings,
        source_factory=lambda: FakeSource(fps=100),
        robot_source_factory=lambda: FakeSource(fps=100),
        robot_gateway=gateway,
    )


def signed_in(app):
    client = TestClient(app)
    client.__enter__()
    client.post("/login", data={"passcode": "4242"})
    return client


@pytest.fixture
def drivable():
    app = make()
    client = signed_in(app)
    yield client, app
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


@pytest.fixture
def watch_only():
    app = make(drive=False)
    client = signed_in(app)
    yield client, app
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


# -- nothing exists until the gateway does ----------------------------------


def test_a_watchable_robot_is_not_a_drivable_one(watch_only):
    """The normal state until the gateway is installed on the Pi: the tab
    works, the picture works, and there is no way to move anything."""
    client, app = watch_only
    assert app.state.robot is None
    page = client.get("/robot")
    assert page.status_code == 200 and "drive-link" not in page.text
    assert client.get("/drive").status_code == 404
    for path in ("/robot/drive", "/robot/stop", "/robot/look"):
        assert client.post(path).status_code == 404
    assert client.get("/robot/telemetry").status_code == 404


def test_settings_needs_both_halves_before_it_calls_a_robot_drivable():
    def settings(**kwargs) -> Settings:
        return Settings(passcode="4242", secret="s" * 20, **kwargs)

    both = settings(robot_control_url="http://10.0.0.3:9031", robot_token="t")
    assert both.robot_drive_configured is True
    for half in (
        settings(robot_control_url="http://10.0.0.3:9031"),
        settings(robot_token="t"),
        settings(),
    ):
        assert half.robot_drive_configured is False
    # And it is a different question from "is there a robot to watch".
    watchable = settings(robot_snapshot_url=ROBOT_URL)
    assert watchable.robot_configured is True
    assert watchable.robot_drive_configured is False


def test_the_drive_page_and_its_link_appear_once_the_gateway_is_configured(drivable):
    client, _ = drivable
    assert 'href="/drive"' in client.get("/robot").text
    page = client.get("/drive")
    assert page.status_code == 200
    assert 'id="stick"' in page.text and 'id="estop"' in page.text
    # The send interval travels from the server so it cannot drift from the
    # TTL it has to stay under.
    assert 'data-interval="200"' in page.text
    assert "Turn sideways" in page.text, "portrait is told what to do"


def test_driving_is_behind_the_same_passcode_as_everything_else():
    app = make()
    with TestClient(app) as client:
        assert client.get("/drive", follow_redirects=False).status_code == 303
        assert client.post("/robot/drive", follow_redirects=False).status_code == 303
        assert client.post("/robot/stop", follow_redirects=False).status_code == 303
        assert client.post("/robot/look", follow_redirects=False).status_code == 303
        assert client.get("/robot/telemetry", follow_redirects=False).status_code == 303
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_the_session_cookie_stays_samesite_so_another_site_cannot_drive():
    """Load-bearing now that a POST moves a physical object: without this a
    page Chris visits while signed in could drive the robot from its own
    JavaScript."""
    app = make()
    with TestClient(app) as client:
        login = client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        cookie = login.headers["set-cookie"].lower()
        assert "samesite=lax" in cookie or "samesite=strict" in cookie
        assert "httponly" in cookie
    app.state.hub.stop()
    app.state.robot_hub.stop()


# -- the four failures -------------------------------------------------------


def answers(status: int, body: dict):
    return lambda request: httpx.Response(status, json=body)


@pytest.mark.parametrize(
    ("reason", "expected_words"),
    [("low_battery", "too low"), ("demo_running", "demo")],
)
def test_a_refusal_is_409_with_words_that_name_what_to_do(reason, expected_words):
    app = make(answers(409, {"ok": False, "reason": reason}))
    client = signed_in(app)
    r = client.post("/robot/drive", data={"vx": 0.4, "vy": 0, "omega": 0})
    assert r.status_code == 409
    assert r.json()["reason"] == reason
    assert expected_words in r.json()["error"].lower()
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_a_silent_robot_is_503_not_500():
    app = make(answers(503, {"ok": False, "reason": "turbopi_unreachable"}))
    client = signed_in(app)
    r = client.post("/robot/stop")
    assert r.status_code == 503, "a stop that did not land must not read as success"
    assert r.json()["reason"] == "unreachable"
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_an_unreachable_gateway_is_503_rather_than_a_traceback():
    def refused(request):
        raise httpx.ConnectError("nothing listening", request=request)

    app = make(refused)
    client = signed_in(app)
    r = client.post("/robot/drive", data={"vx": 0.2, "vy": 0, "omega": 0})
    assert r.status_code == 503
    assert "could not reach" in r.json()["error"]
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_the_robots_own_error_becomes_a_502_and_never_a_500():
    app = make(answers(502, {"ok": False, "reason": "E02 - Invalid parameter!"}))
    client = signed_in(app)
    r = client.post("/robot/look", data={"pan_deg": 10, "tilt_deg": 0})
    assert r.status_code == 502 and "E02" in r.json()["error"]
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_an_unexpected_failure_says_nothing_it_has_not_reasoned_about():
    """An exception nobody anticipated has, by definition, text nobody has
    checked. Its class name goes to the log; the browser gets a sentence."""

    def explode(request):
        raise ValueError(f"surprise carrying {TOKEN}")

    app = make(explode)
    client = signed_in(app)
    r = client.post("/robot/stop")
    assert r.status_code == 502
    assert TOKEN not in r.text and "surprise" not in r.text
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_a_bad_velocity_is_rejected_without_reaching_the_robot():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    app = make(handler)
    client = signed_in(app)
    # FastAPI's own Form parsing catches this one before we do, which is
    # the same outcome: a 4xx, and nothing sent.
    assert client.post("/robot/drive", data={"vx": "fast"}).status_code == 422
    assert seen == []
    client.__exit__(None, None, None)
    app.state.hub.stop()
    app.state.robot_hub.stop()


# -- what leaves this machine ------------------------------------------------


def test_the_browser_never_chooses_the_ttl_and_never_sends_a_motor_id(drivable):
    import json

    client, app = drivable
    seen = []
    app.state.robot._client = httpx.Client(
        base_url="http://10.0.0.3:9031",
        headers={"X-Robot-Token": TOKEN},
        transport=httpx.MockTransport(
            lambda r: (seen.append(r), httpx.Response(200, json={"ok": True}))[1]
        ),
    )
    # Even asked for the maximum, the page cannot widen its own dead man.
    client.post("/robot/drive", data={"vx": 5, "vy": 0, "omega": 0, "ttl_ms": 2000})
    body = json.loads(seen[0].read().decode())
    assert body == {"vx": 1.0, "vy": 0.0, "omega": 0.0, "ttl_ms": 500}
    assert seen[0].headers["X-Robot-Token"] == TOKEN


def test_telemetry_is_passed_through_including_the_keys_we_did_not_ask_for(drivable):
    """`demo_detection` and `battery_age_ms` are the gateway author's
    additions. The page needs both: a null battery is not a flat one, and a
    demo guard that cannot run must be said out loud, not assumed."""
    client, _ = drivable
    body = client.get("/robot/telemetry").json()
    assert body["demo_detection"] is True
    assert body["last_command_age_ms"] is None
    assert body["battery_age_ms"] == 300


def test_the_app_stops_the_robot_on_its_way_out():
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"ok": True, **HEALTHY})

    app = make(handler)
    with TestClient(app) as client:
        client.post("/login", data={"passcode": "4242"})
        client.get("/robot/telemetry")
        assert "/stop" not in calls
    # Leaving the `with` ran the lifespan's finally.
    assert calls[-1] == "/stop"
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_a_failing_stop_at_shutdown_does_not_take_the_app_down_with_it():
    """`stop_quietly` exists for exactly this: raising inside a `finally`
    would mask whatever was already being handled."""

    def dead(request):
        raise httpx.ConnectError("gone", request=request)

    app = make(dead)
    with TestClient(app) as client:
        client.post("/login", data={"passcode": "4242"})
    app.state.hub.stop()
    app.state.robot_hub.stop()
