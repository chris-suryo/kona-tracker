"""Driving over one connection, and the safety rules that buys and costs.

**The measurement this exists for.** The robot is on the home LAN. A phone on
LTE reaches it through Tailscale to the PC (~700 ms) and then over wired
Ethernet to the Pi (~1 ms). Over HTTP, `drive.js` held one command in flight
at a time -- it has to, or they pile up -- so the send rate was capped by that
round trip at about 1.5 a second, against a 500 ms TTL. The robot session
measured the result: the gateway's watchdog firing seven times in six seconds
with the stick held down.

A socket removes the round trip from the send path. But it also introduces a
server-side loop that repeats the last command, and that is a safety change,
not a performance one: a watchdog that fires when commands *stop* arriving is
defeated by anything that keeps sending on the operator's behalf. So the pump
has its own expiry, and most of this file is about that.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.robot.gateway import DRIVE_HOLD_MS, DRIVE_INTERVAL_MS, RobotGateway
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

TOKEN = "socket-token-value"


class Pi:
    """A gateway that records what actually reached the robot."""

    def __init__(self, drive_status: int = 200, reason: str = ""):
        self.drives: list[dict] = []
        self.stops = 0
        self.drive_status = drive_status
        self.reason = reason

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/drive":
            self.drives.append(json.loads(request.content))
            if self.drive_status != 200:
                return httpx.Response(self.drive_status, json={"ok": False, "reason": self.reason})
            return httpx.Response(200, json={"ok": True})
        if request.url.path == "/stop":
            self.stops += 1
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json={"ok": True})


def app_for(pi: Pi | None, drive: bool = True):
    gateway = (
        RobotGateway("http://10.0.0.3:9031", TOKEN, transport=httpx.MockTransport(pi))
        if drive and pi
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


@pytest.fixture
def driving():
    pi = Pi()
    app = app_for(pi)
    client = TestClient(app)
    with client:
        client.post("/login", data={"passcode": "4242"})
        yield client, pi
    app.state.hub.stop()
    app.state.robot_hub.stop()


def settle(pi: Pi, want: int, timeout: float = 10.0) -> None:
    """Wait for the pump to have sent `want` commands, or give up loudly."""
    wait_for(lambda: len(pi.drives) >= want, timeout)


def holding(socket, frame: str, condition, timeout: float = 10.0) -> bool:
    """Wait for `condition` while a thumb stays down.

    The pump deliberately lets go after DRIVE_HOLD_MS of silence, so any test
    that waits longer than that WITHOUT sending gets a robot that has
    correctly stopped -- and an assertion that fails for a reason the product
    is right about. A real drive page sends five frames a second; so does
    this.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        socket.send_text(frame)
        time.sleep(DRIVE_INTERVAL_MS / 2000.0)
    return False


def wait_for(condition, timeout: float = 10.0) -> bool:
    """Poll until `condition` holds, or the deadline passes.

    **Every timing assertion in this file goes through here, and the deadlines
    are deliberately generous.** Two of these tests were written as "sleep a
    bit, then assert", and both flaked on CI within an hour of landing: the
    takeover test saw an in-flight command arrive out of order on Windows, and
    the teardown test gave the stop two seconds on a loaded Ubuntu runner and
    got 0. They passed on the next two runs, which is the worst outcome --
    a test that fails one run in three is a test nobody trusts, and the
    instinct it teaches is to re-run CI rather than read it.

    A long deadline costs nothing when the condition holds, because this
    returns as soon as it does. It only costs time on a genuine failure,
    which is the one case worth being slow about.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_a_signed_out_phone_cannot_open_the_socket():
    """The `gate` middleware is an HTTP middleware and does NOT run for a
    WebSocket handshake. Without an explicit check here this would be the one
    unauthenticated route in the app -- and the one that moves a robot."""
    from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415 - test-only

    pi = Pi()
    app = app_for(pi)
    client = TestClient(app)
    with client:  # deliberately no /login
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/robot/ws/drive") as socket:
                socket.send_text('{"vx":1,"vy":0,"omega":0}')
                socket.receive_text()
    assert pi.drives == [], "an unauthenticated socket reached the motors"
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_one_frame_keeps_the_robot_driving_without_the_phone_repeating_itself(driving):
    """The point of the pump. The phone sends when it can; the Pi sees a
    steady rate regardless, so jitter on the slow leg cannot stutter it.

    Bounded above as well as below, and the upper bound is the safety rule:
    one frame buys DRIVE_HOLD_MS of holding and not a millisecond more, so at
    a 200 ms interval this is two or three sends, never an open-ended stream.
    Getting that wrong in the permissive direction is how a pump defeats the
    watchdog it is supposed to sit in front of.
    """
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":0.5,"vy":0,"omega":0}')
        settle(pi, 2)
        time.sleep((DRIVE_HOLD_MS + 4 * DRIVE_INTERVAL_MS) / 1000.0)
    assert len(pi.drives) >= 2, "one frame should be refreshed, not sent once"
    assert len(pi.drives) <= DRIVE_HOLD_MS / DRIVE_INTERVAL_MS + 1, "it held past its own expiry"
    assert pi.drives[0] == {"vx": 0.5, "vy": 0.0, "omega": 0.0, "ttl_ms": 500}
    assert all(d == pi.drives[0] for d in pi.drives), "the refresh changed the command"


def test_the_pump_lets_go_when_the_phone_goes_quiet(driving):
    """The safety rule that pays for the pump.

    Repeating a command forever would defeat the gateway's watchdog, which
    only fires when commands stop arriving. So silence past DRIVE_HOLD_MS
    stops the repeat and sends one stop of its own.
    """
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":1,"vy":0,"omega":0}')
        settle(pi, 2)
        sent_while_held = len(pi.drives)
        assert wait_for(lambda: pi.stops >= 1), (
            "the pump kept holding the throttle for a phone that is gone"
        )
        quiet = len(pi.drives)
        # Now prove it STAYS let go. This one is a fixed sleep on purpose:
        # the assertion is that nothing happens, and there is no condition to
        # wait for. A slow runner only makes it a stronger check.
        time.sleep(3 * DRIVE_INTERVAL_MS / 1000.0)
        assert len(pi.drives) == quiet, "it must stay let go, not resume"
    assert quiet >= sent_while_held


def test_the_stop_it_sends_on_going_quiet_is_sent_once_not_every_tick(driving):
    """The Pi's RPC server handles one request at a time and an unnecessary
    stop blocks it for two seconds. A stop repeated at 5 Hz would be the app
    attacking the robot it is trying to protect."""
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":1,"vy":0,"omega":0}')
        settle(pi, 2)
        assert wait_for(lambda: pi.stops >= 1), "the pump never let go"
        # Then give it several more ticks to send the duplicates it must not.
        time.sleep(6 * DRIVE_INTERVAL_MS / 1000.0)
        assert pi.stops == 1, f"sent {pi.stops} stops where one was needed"


def test_an_explicit_stop_frame_goes_straight_through(driving):
    """Ahead of the pump's next tick. The page also sends its own HTTP stop,
    which is the one it can watch land; this is only about getting the wheels
    to zero as soon as the bytes arrive."""
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":1,"vy":0,"omega":0}')
        settle(pi, 1)
        socket.send_text('{"stop":true}')
        assert json.loads(socket.receive_text())["stopped"] is True
    assert pi.stops >= 1


def test_closing_the_page_stops_the_robot(driving):
    """A socket that drops is a person who has gone. The gateway's watchdog
    is the backstop, but not trying would be leaving it to chance."""
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":1,"vy":0,"omega":0}')
        settle(pi, 1)
    assert wait_for(lambda: pi.stops >= 1), "the socket closed and the robot was never told to stop"


def test_a_refusal_reaches_the_phone_and_the_pump_lets_go():
    """A flat battery or a running demo must not become a pump that keeps
    retrying into a robot that has said no."""
    pi = Pi(drive_status=409, reason="low_battery")
    app = app_for(pi)
    client = TestClient(app)
    with client:
        client.post("/login", data={"passcode": "4242"})
        with client.websocket_connect("/robot/ws/drive") as socket:
            socket.send_text('{"vx":1,"vy":0,"omega":0}')
            answer = json.loads(socket.receive_text())
            assert answer["ok"] is False
            assert answer["reason"] == "low_battery"
            sent = len(pi.drives)
            time.sleep(3 * DRIVE_INTERVAL_MS / 1000.0)
            assert len(pi.drives) == sent, "the pump kept pushing after a refusal"
    app.state.hub.stop()
    app.state.robot_hub.stop()


@pytest.mark.parametrize(
    "junk",
    ["not json at all", "[]", '"a string"', '{"vx":"fast"}', '{"vx":null}'],
)
def test_a_malformed_frame_is_ignored_rather_than_driving_at_zero(driving, junk):
    """A frame we cannot read must not become an all-zero command: zero is a
    deliberate instruction to stop, and inventing one from a parse failure
    would make a garbled connection look like a person letting go."""
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as socket:
        socket.send_text('{"vx":0.7,"vy":0,"omega":0}')
        settle(pi, 1)
        socket.send_text(junk)
        settle(pi, len(pi.drives) + 2)
    assert all(d["vx"] == 0.7 for d in pi.drives), "a bad frame changed the command"


def test_a_second_driver_takes_over_rather_than_fighting(driving):
    """The Pi's RPC server is single-threaded. Two drive pages open at once
    would interleave two command streams into it and fight over the robot."""
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as first:
        first.send_text('{"vx":0.2,"vy":0,"omega":0}')
        settle(pi, 1)
        with client.websocket_connect("/robot/ws/drive") as second:
            second.send_text('{"vx":0.9,"vy":0,"omega":0}')

            # A 0.2 already in flight when the second page connected is not
            # the first page still driving, and on Windows one arrived AFTER
            # a 0.9 -- two threadpool calls completing out of order. So this
            # waits for a clean run rather than assuming a fixed window
            # contains no straggler.
            def only_the_new_one() -> bool:
                tail = [d["vx"] for d in pi.drives[-3:]]
                return len(tail) == 3 and all(v == 0.9 for v in tail)

            assert holding(second, '{"vx":0.9,"vy":0,"omega":0}', only_the_new_one), (
                f"the first page is still driving: {[d['vx'] for d in pi.drives]}"
            )


def test_there_is_no_socket_without_a_gateway():
    from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415 - test-only

    app = app_for(None, drive=False)
    client = TestClient(app)
    with client:
        client.post("/login", data={"passcode": "4242"})
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/robot/ws/drive") as socket:
                socket.receive_text()
    app.state.hub.stop()


def test_the_hold_window_is_longer_than_the_send_interval_and_shorter_than_a_second():
    """Both halves matter. Shorter than the interval and a single late frame
    cuts the throttle; much longer and the phone dying leaves the robot
    driving for a time a person would notice and not forgive."""
    assert DRIVE_HOLD_MS > DRIVE_INTERVAL_MS * 2
    assert DRIVE_HOLD_MS <= 1000


def test_a_page_that_was_taken_over_does_not_stop_the_page_that_replaced_it(driving):
    """The handover must be silent on the robot.

    Every socket stops the robot on its way out, which is right when the
    person has gone. But a socket closed *because a newer drive page took
    over* has not lost its person -- and its parting stop would land on the
    page that just started driving, as a stutter with no cause visible
    anywhere on either screen.

    The first version of this guard used `set.discard(...) is None`, which is
    always true, so the stop always fired. That is exactly the kind of bug a
    test written after the fix would have been shaped around, so this one
    counts stops rather than inspecting the flag.
    """
    client, pi = driving
    with client.websocket_connect("/robot/ws/drive") as first:
        first.send_text('{"vx":0.2,"vy":0,"omega":0}')
        settle(pi, 1)
        with client.websocket_connect("/robot/ws/drive") as second:
            second.send_text('{"vx":0.9,"vy":0,"omega":0}')
            settle(pi, len(pi.drives) + 2)
            # Keep the second page's thumb down throughout. Without that the
            # observation window is longer than DRIVE_HOLD_MS, both pumps
            # correctly let go, and each sends the very stop this test is
            # asserting the absence of -- a test failing on behaviour the
            # product gets right.
            mark = len(pi.drives)
            assert holding(
                second,
                '{"vx":0.9,"vy":0,"omega":0}',
                lambda: len(pi.drives) >= mark + 4,
            ), "the second page never took over the pump"
            assert pi.stops == 0, "the superseded page stopped the robot mid-drive"
            still = [d["vx"] for d in pi.drives[mark + 1 :]]
            assert still and all(v == 0.9 for v in still), still
