"""`RobotGateway`: the only thing in this app that can move the robot.

The gateway on the Pi owns the watchdog, the kinematics and the duty cap.
What these tests pin is our half of the contract -- that the token goes on
every call and comes back out of nothing, that the dead-man TTL is ours to
set and not the caller's, that a value we would not want on a motor is
rejected here rather than clamped quietly on the far side, and that each of
the gateway's four failure shapes becomes a distinct, honest error.
"""

from __future__ import annotations

import json
import socket

import httpx
import pytest

from kona_tracker.robot.gateway import (
    DRIVE_INTERVAL_MS,
    DRIVE_TTL_MS,
    RobotFault,
    RobotGateway,
    RobotRefused,
    RobotUnreachable,
)

TOKEN = "s3cret-robot-token"


def gateway(handler, token: str = TOKEN) -> RobotGateway:
    return RobotGateway("http://robot.test:9031", token, transport=httpx.MockTransport(handler))


def body_of(request: httpx.Request) -> dict:
    """What we actually put on the wire, parsed rather than string-matched."""
    return json.loads(request.read().decode())


def ok(payload: dict | None = None) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, **(payload or {})})


def recorder(payload: dict | None = None):
    """A handler that answers 200 and keeps every request it was given."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(payload)

    return handler, seen


def test_every_call_carries_the_token_and_none_of_them_carry_a_motor_id():
    handler, seen = recorder({"battery_v": 8.01})
    robot = gateway(handler)
    robot.drive(0.4, 0.0, -0.2)
    robot.stop()
    robot.telemetry()
    robot.look_at(0, -10)
    assert len(seen) == 4
    for request in seen:
        assert request.headers["X-Robot-Token"] == TOKEN
    body = body_of(seen[0])
    assert set(body) == {"vx", "vy", "omega", "ttl_ms"}
    # Motor ids are the gateway's business. If one ever appears here, the
    # kinematics have leaked to the wrong side of the link.
    for word in ("motor", "SetBrushMotor", "duty"):
        assert word not in json.dumps(body)


def test_the_page_can_never_choose_the_length_of_its_own_dead_man_switch():
    """`drive()` takes no ttl argument at all, and sends ours every time.

    A browser that could ask for the gateway's maximum TTL and then crash
    would leave the robot driving for two seconds with nobody holding it.
    """
    handler, seen = recorder()
    robot = gateway(handler)
    robot.drive(1, 1, 1)
    assert body_of(seen[0])["ttl_ms"] == DRIVE_TTL_MS
    # The send interval must stay well under the TTL, or one dropped
    # request is a stutter rather than a non-event.
    assert DRIVE_INTERVAL_MS * 2 <= DRIVE_TTL_MS


@pytest.mark.parametrize(
    ("sent", "expected"),
    [(5, 1.0), (-5, -1.0), (0.4, 0.4), (1, 1.0), (-1, -1.0), ("0.25", 0.25)],
)
def test_velocities_are_clamped_before_they_leave_this_machine(sent, expected):
    handler, seen = recorder()
    robot = gateway(handler)
    robot.drive(sent, 0, 0)
    assert body_of(seen[0])["vx"] == expected


@pytest.mark.parametrize("sent", ["inf", "-inf", "1e999", "-1e999", float("inf")])
def test_an_infinity_clamps_to_full_tilt_rather_than_reaching_a_motor(sent):
    """Float coercion accepts "inf" and "1e999" quite happily, and an
    infinity on a motor duty is nonsense the gateway would have to reject.
    min/max clamp it to exactly full deflection, which is a real command."""
    handler, seen = recorder()
    robot = gateway(handler)
    robot.drive(sent, 0, 0)
    assert body_of(seen[0])["vx"] in (1.0, -1.0)


@pytest.mark.parametrize("bad", ["fast", None, [1], {"vx": 1}, float("nan")])
def test_a_value_that_is_not_a_number_is_refused_rather_than_sent_as_zero(bad):
    """A zero that looks deliberate is worse than an error: it would read
    as 'the operator let go' when in fact the command was nonsense."""
    handler, seen = recorder()
    robot = gateway(handler)
    with pytest.raises(RobotFault):
        robot.drive(bad, 0, 0)
    assert seen == [], "nothing reached the robot"


def test_look_is_clamped_to_the_servo_safe_range():
    """A servo driven into its mechanical stop stalls, draws full current
    and strips its own gears. The gateway clamps too; this is the belt."""
    handler, seen = recorder()
    robot = gateway(handler)
    robot.look_at(90, -90)
    assert body_of(seen[0]) == {"pan_deg": 45.0, "tilt_deg": -45.0}


def test_a_flat_battery_or_a_running_demo_is_a_refusal_with_its_reason():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"ok": False, "reason": "low_battery"})

    with pytest.raises(RobotRefused) as caught:
        gateway(handler).drive(0.2, 0, 0)
    assert caught.value.reason == "low_battery"


def test_a_silent_robot_is_unreachable_not_a_fault():
    """`turbopi_unreachable` means the command did not land, which to a
    person holding a joystick is the same thing as the gateway being gone."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False, "reason": "turbopi_unreachable"})

    with pytest.raises(RobotUnreachable, match="turbopi_unreachable"):
        gateway(handler).stop()


def test_a_wrong_token_says_so_in_words_that_name_the_fix():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad token"})

    with pytest.raises(RobotFault, match="rejected our token"):
        gateway(handler).telemetry()


def test_the_robots_own_error_text_comes_through_a_fault():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"ok": False, "reason": "E02 - Invalid parameter!"})

    with pytest.raises(RobotFault, match="E02"):
        gateway(handler).drive(0.1, 0, 0)


def test_a_200_that_says_it_failed_is_believed_over_its_status_code():
    """The robot's own RPC does exactly this -- HTTP 200 with success false
    -- so the gateway may well pass the habit along. Believe the body."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "reason": "no"})

    with pytest.raises(RobotFault):
        gateway(handler).stop()


@pytest.mark.parametrize("body", [b"<html>gateway</html>", b"[1, 2, 3]"])
def test_an_answer_that_is_not_a_json_object_is_a_fault(body):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    with pytest.raises(RobotFault):
        gateway(handler).telemetry()


def test_an_absent_gateway_is_unreachable_rather_than_an_httpx_traceback():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing is listening here now
    robot = RobotGateway(f"http://127.0.0.1:{port}", TOKEN, timeout=0.5)
    try:
        with pytest.raises(RobotUnreachable) as caught:
            robot.telemetry()
        # Names the transport failure, reads as a sentence, and carries no
        # URL -- httpx puts the address in its own message and this must not.
        message = str(caught.value)
        assert message[0].isupper() and message.endswith("."), message
        assert "Error" in message or "Timeout" in message, message
        assert str(port) not in message and "127.0.0.1" not in message
    finally:
        robot.close()


def test_the_token_never_appears_in_an_error_or_a_repr():
    """The one secret this module holds. A log line is forever."""

    def echoes(request: httpx.Request) -> httpx.Response:
        # A gateway that carelessly reflects what it was sent.
        return httpx.Response(502, json={"ok": False, "reason": f"rejected {TOKEN}"})

    robot = gateway(echoes)
    with pytest.raises(RobotFault) as caught:
        robot.drive(0.1, 0, 0)
    assert TOKEN not in str(caught.value)
    assert "***" in str(caught.value)
    assert TOKEN not in repr(robot)


def test_a_reason_from_the_gateway_cannot_run_away_with_the_page():
    long_reason = "x" * 5000

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"ok": False, "reason": long_reason})

    with pytest.raises(RobotFault) as caught:
        gateway(handler).stop()
    assert len(str(caught.value)) <= 200


def test_stop_quietly_reports_failure_instead_of_raising_into_a_finally():
    """Used on shutdown and inside error handling, where raising would mask
    whatever we were already dealing with."""

    def dead(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"ok": False, "reason": "turbopi_unreachable"})

    assert gateway(dead).stop_quietly() is False
    handler, seen = recorder()
    assert gateway(handler).stop_quietly() is True
    assert len(seen) == 1


def test_a_borrowed_client_is_not_closed():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: ok()))
    robot = RobotGateway("http://robot.test:9031", TOKEN, client=client)
    robot.close()
    assert not client.is_closed
    client.close()


def test_health_needs_no_token_to_be_useful_and_never_touches_the_motors():
    handler, seen = recorder({"turbopi": True, "battery_v": 8.01, "uptime_s": 12})
    robot = gateway(handler, token="")
    assert robot.health()["turbopi"] is True
    assert seen[0].method == "GET" and seen[0].url.path == "/health"
