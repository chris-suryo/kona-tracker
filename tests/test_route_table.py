"""The route table, pinned, before app.py is split into routers.

`create_app()` is being taken apart into one router per domain. The split is
allowed to change where a handler lives and nothing else, and "nothing else"
needs a definition that a test can hold: every path, every method set, the
WebSocket, the static mount, the order of the two middlewares, and the seven
attributes the app publishes on `app.state` for tests and the audit server.

This landed on the unsplit code first, green, so that a route the refactor
drops, renames, or accidentally gives a prefix fails here by name rather
than as a 404 in somebody's phone.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.routing import Mount, Route, WebSocketRoute

from kona_tracker.camera.source import FakeSource
from kona_tracker.robot.gateway import RobotGateway
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

GOLDEN = [
    ("http", "GET", "/"),
    ("http", "GET", "/activity"),
    ("http", "GET", "/activity.json"),
    ("http", "GET", "/avatar.jpg"),
    ("http", "GET", "/camera"),
    ("http", "GET", "/control/settings"),
    ("http", "GET", "/drive"),
    ("http", "GET", "/healthz"),
    ("http", "GET", "/live"),
    ("http", "GET", "/login"),
    ("http", "GET", "/map"),
    ("http", "GET", "/map.json"),
    ("http", "GET", "/preview/{metric}"),
    ("http", "GET", "/rest"),
    ("http", "GET", "/robot"),
    ("http", "GET", "/robot/led"),
    ("http", "GET", "/robot/telemetry"),
    ("http", "GET", "/settings"),
    ("http", "GET", "/snapshot.jpg"),
    ("http", "GET", "/status.json"),
    ("http", "GET", "/steps"),
    ("http", "GET", "/stream.mjpg"),
    ("http", "GET", "/walks/{walk_id}"),
    ("http", "POST", "/control/move"),
    ("http", "POST", "/control/preset"),
    ("http", "POST", "/control/setting"),
    ("http", "POST", "/live"),
    ("http", "POST", "/login"),
    ("http", "POST", "/logout"),
    ("http", "POST", "/robot/drive"),
    ("http", "POST", "/robot/led"),
    ("http", "POST", "/robot/look"),
    ("http", "POST", "/robot/stop"),
    ("mount", "", "/static"),
    ("websocket", "", "/robot/ws/drive"),
]

STATE = ["auth", "control", "fi", "health_summary", "hub", "robot", "robot_hub"]


def table(app) -> list[tuple[str, str, str]]:
    return sorted(rows(app.routes, ""))


def rows(routes, prefix: str):
    """FastAPI 0.141 keeps an included router as one lazy entry in
    `app.routes` rather than copying its routes in, so the table walks into
    it -- carrying the prefix it was included with, which is how a router
    that grew one would show up here as every one of its paths changing."""
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from rows(included.routes, prefix + route.include_context.prefix)
            continue
        if isinstance(route, Mount):
            yield ("mount", "", prefix + route.path)
        elif isinstance(route, WebSocketRoute):
            yield ("websocket", "", prefix + route.path)
        elif isinstance(route, Route):
            methods = ",".join(sorted(m for m in (route.methods or ()) if m != "HEAD"))
            yield ("http", methods, prefix + route.path)


@pytest.fixture
def app():
    gateway = RobotGateway(
        "http://192.0.2.3:9031",
        "token-" * 4,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"ok": True})),
    )
    built = create_app(
        Settings(
            passcode="4242",
            secret="s" * 20,
            robot_snapshot_url="http://192.0.2.3:8080/?action=snapshot",
            robot_name="TurboPi",
        ),
        source_factory=lambda: FakeSource(fps=100),
        robot_source_factory=lambda: FakeSource(fps=100),
        robot_gateway=gateway,
    )
    yield built
    built.state.hub.stop()
    built.state.robot_hub.stop()


def test_every_route_is_still_there_and_nothing_grew_a_prefix(app):
    assert table(app) == GOLDEN


def test_the_gate_runs_after_the_security_headers_are_applied(app):
    """Starlette runs `user_middleware` outermost first. `security_headers`
    wraps `gate`, so a 401 or a redirect from the gate carries the headers
    too. Reversing them would strip the CSP from every refusal."""
    names = [m.kwargs["dispatch"].__name__ for m in app.user_middleware]
    assert names == ["security_headers", "gate"]


def test_the_app_publishes_what_the_tests_and_audit_server_reach_for(app):
    for name in STATE:
        assert hasattr(app.state, name), name


def test_the_table_is_the_same_with_no_robot_at_all():
    """No gateway does not mean fewer routes. Every robot path is registered
    regardless and answers 404 from `robot_or_404()`; the WebSocket closes
    the handshake with 1008. So the split must not make any of them
    conditional either -- a router that only exists when configured would
    change the table, and this pins that it does not."""
    built = create_app(
        Settings(passcode="4242", secret="s" * 20),
        source_factory=lambda: FakeSource(fps=100),
    )
    try:
        assert table(built) == GOLDEN
        assert built.state.robot is None
    finally:
        built.state.hub.stop()
