"""The front lights: the one robot control that is not about moving.

The robot session's own reading of the Pi's source (2026-09-15) is what makes
this its own test file rather than three lines in `test_robot_drive.py`:

> They are reachable while `TurboPi.py` is down. The two front RGBs are on
> the ultrasonic module at **I2C 0x77**, registers 2-8 -- not on the serial
> bus that owns the motors. [...] So the gateway drives them **directly over
> I2C**, not through port 9030.

Which makes `/led` the only endpoint that answers when `/health` says
`turbopi: false`. Every other control on the Robot tab is dead in that state
and this one is not, so the tests that matter here are about *not* borrowing
the drive routes' assumptions.
"""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.robot.gateway import RobotFault, RobotGateway
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

TOKEN = "led-token-value"


def make(handler, drive: bool = True):
    gateway = (
        RobotGateway("http://10.0.0.3:9031", TOKEN, transport=httpx.MockTransport(handler))
        if drive
        else None
    )
    return create_app(
        Settings(
            passcode="4242",
            secret="s" * 20,
            robot_snapshot_url="http://10.0.0.3:8080/?action=snapshot",
            robot_name="TurboPi",
        ),
        source_factory=lambda: FakeSource(fps=100),
        robot_source_factory=lambda: FakeSource(fps=100),
        robot_gateway=gateway,
    )


def signed_in(app):
    client = TestClient(app)
    client.__enter__()
    client.post("/login", data={"passcode": "4242"})
    return client


def client_for(handler, drive: bool = True):
    app = make(handler, drive=drive)
    client = signed_in(app)
    return client, app


def shut(client, app):
    client.__exit__(None, None, None)
    app.state.hub.stop()
    if getattr(app.state, "robot_hub", None):
        app.state.robot_hub.stop()


@pytest.fixture
def lights():
    """A gateway that remembers what it was told, the way the real one does."""
    state = {"on": None, "r": None, "g": None, "b": None}
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/led":
            return httpx.Response(404, json={"ok": False, "reason": "not here"})
        if request.method == "POST":
            body = json.loads(request.content)
            seen.append(body)
            state.update(body)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True, **state})

    client, app = client_for(handler)
    yield client, seen, state
    shut(client, app)


def test_reading_before_anything_was_set_says_unknown_not_off(lights):
    """Four nulls is the gateway saying nobody has touched them since it
    started -- which is not off. A demo may have left them lit. Drawing a
    confident "Off" there would be the page inventing a fact."""
    client, _, _ = lights
    body = client.get("/robot/led").json()
    assert body["on"] is None
    assert body["r"] is None


def test_a_colour_reaches_the_robot_as_three_channels_and_an_on(lights):
    client, seen, _ = lights
    assert client.post("/robot/led", data={"on": "true", "r": 0, "g": 255, "b": 40}).status_code
    assert seen[-1] == {"on": True, "r": 0, "g": 255, "b": 40}


@pytest.mark.parametrize(
    ("sent", "landed"),
    [
        (999, 255),
        (-5, 0),
        (255.9, 255),
        ("200", 200),
    ],
)
def test_channels_are_clamped_before_they_leave_this_machine(sent, landed):
    """The gateway clamps too. We clamp first for the same reason pan and tilt
    are clamped twice: a bad value should not travel, and the number in our
    log should be the number we meant."""
    from kona_tracker.robot.gateway import _channel  # noqa: PLC0415 - test-only

    assert _channel(sent) == landed


@pytest.mark.parametrize("junk", ["green", None, object(), float("nan")])
def test_something_that_is_not_a_number_is_refused_rather_than_sent_as_zero(junk):
    """Zero is black, and black is indistinguishable from off. A malformed
    value silently becoming zero would look like a working button."""
    from kona_tracker.robot.gateway import _channel  # noqa: PLC0415 - test-only

    with pytest.raises(RobotFault):
        _channel(junk)


def test_the_gateway_answers_the_i2c_write_failing_as_its_own_state():
    """`led_unavailable` is a 503 and means the I2C write failed -- a
    different problem from the gateway being gone, though both are 503 to a
    person. The reason travels so the page can say which."""

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False, "reason": "led_unavailable"})

    client, app = client_for(broken)
    try:
        response = client.post("/robot/led", data={"on": "true", "r": 255, "g": 255, "b": 255})
        assert response.status_code == 503
        assert response.json()["reason"] == "unreachable"
    finally:
        shut(client, app)


def test_the_lights_answer_while_the_robots_own_software_is_down():
    """The point of the whole feature. `/health` reporting `turbopi: false`
    kills every other control on the page; these are on a different bus and
    must not be greyed out with them."""
    calls: list[str] = []

    def turbopi_is_down(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "turbopi": False})
        if request.url.path == "/drive":
            return httpx.Response(503, json={"ok": False, "reason": "turbopi_unreachable"})
        if request.url.path == "/led":
            return httpx.Response(200, json={"ok": True, "on": True, "r": 255, "g": 0, "b": 0})
        return httpx.Response(404, json={"ok": False, "reason": "not here"})

    client, app = client_for(turbopi_is_down)
    try:
        # The motors are gone...
        assert client.post("/robot/drive", data={"vx": 1, "vy": 0, "omega": 0}).status_code == 503
        # ...and the lights are not.
        lit = client.post("/robot/led", data={"on": "true", "r": 255, "g": 0, "b": 0})
        assert lit.status_code == 200, "the lights are on I2C 0x77, not the motor bus"
        assert lit.json()["on"] is True
    finally:
        shut(client, app)


def test_there_is_no_light_switch_without_a_gateway():
    """Same rule as every other robot route: a control that would 404 on
    every press is never drawn, so the route is a 404 rather than a 500."""
    client, app = client_for(lambda r: httpx.Response(200, json={"ok": True}), drive=False)
    try:
        assert client.get("/robot/led").status_code == 404
        assert client.post("/robot/led", data={"on": "true"}).status_code == 404
        assert "led-settings" not in client.get("/robot").text
    finally:
        shut(client, app)


def test_the_robot_page_offers_the_lights_when_there_is_a_gateway(lights):
    client, _, _ = lights
    page = client.get("/robot").text
    assert 'id="led-settings"' in page
    assert "led.js" in page
