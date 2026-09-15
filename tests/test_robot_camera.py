"""The robot as a second camera: its own hub behind the same gate.

`app.state.hub` stays the house camera and every pre-robot URL keeps its
meaning byte for byte; the robot is reached by `cam=robot` on the same
routes, and by a `/robot` page whose tab exists only when a robot is
configured. Nothing here touches the Tapo path unless KONA_ROBOT_SNAPSHOT_URL
is set, which these tests prove by running both ways.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.placeholder import NO_SIGNAL_JPEG, ROBOT_OFF_JPEG
from kona_tracker.camera.source import CameraOpenError, FakeSource
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

ROBOT_URL = "http://10.0.0.3:8080/?action=snapshot"


def make(robot: bool, robot_source=None, **overrides):
    settings = Settings(
        passcode="4242",
        secret="s",
        stale_seconds=0.2,
        hang_seconds=0.5,
        robot_snapshot_url=ROBOT_URL if robot else "",
        **overrides,
    )
    return create_app(
        settings,
        source_factory=lambda: FakeSource(fps=100),
        robot_source_factory=robot_source or (lambda: FakeSource(fps=100)),
    )


@pytest.fixture
def both():
    app = make(robot=True)
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"})
        yield c, app
    app.state.hub.stop()
    app.state.robot_hub.stop()


@pytest.fixture
def house_only():
    app = make(robot=False)
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"})
        yield c, app
    app.state.hub.stop()


def test_no_robot_means_no_hub_no_tab_and_no_page(house_only):
    c, app = house_only
    assert app.state.robot_hub is None
    page = c.get("/camera").text
    assert 'href="/robot"' not in page
    assert c.get("/robot").status_code == 404
    assert c.get("/snapshot.jpg", params={"cam": "robot"}).status_code == 404
    assert c.get("/status.json", params={"cam": "robot"}).status_code == 404


def test_a_configured_robot_gets_a_tab_a_page_and_its_own_hub(both):
    c, app = both
    assert app.state.robot_hub is not None and app.state.robot_hub is not app.state.hub
    assert app.state.robot_hub.name == "robot" and app.state.hub.name == "camera"
    page = c.get("/robot")
    assert page.status_code == 200
    assert 'href="/robot" class="on"' in page.text
    assert 'id="cam"' in page.text and "robot.js" in page.text and "poll.js" in page.text
    # The Camera tab now shows the third tab too, unselected.
    assert 'href="/robot" class=""' in c.get("/camera").text
    # The robot page carries no house-camera controls.
    assert 'id="capture"' not in page.text and "cam-settings" not in page.text


def test_the_robot_name_is_what_the_page_calls_it():
    app = make(robot=True, robot_name="TurboPi")
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"})
        assert '<div class="d">TurboPi</div>' in c.get("/robot").text
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_the_robot_snapshot_is_gated_like_an_image_not_a_page():
    """An <img> cannot follow a redirect to /login; the gate's 401 rule is
    keyed on the path, which is why the camera is a query and not a prefix."""
    app = make(robot=True)
    with TestClient(app) as c:
        r = c.get("/snapshot.jpg", params={"cam": "robot"}, follow_redirects=False)
        assert r.status_code == 401
        assert c.get("/robot", follow_redirects=False).status_code == 303
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_robot_frames_carry_the_same_four_headers_and_come_from_the_robot_hub(both):
    c, app = both
    r = c.get("/snapshot.jpg", params={"cam": "robot", "after": 0})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    for name in ("x-kona-state", "x-kona-seq", "x-kona-error"):
        assert name in r.headers
    # Only the robot hub was woken by that request.
    assert app.state.robot_hub.status()["viewers"] >= 0
    assert app.state.hub.status()["state"] == "idle", "the house camera was not touched"


def test_the_default_camera_is_the_house_one_byte_for_byte(both):
    c, _ = both
    plain = c.get("/snapshot.jpg", params={"after": 0})
    named = c.get("/snapshot.jpg", params={"after": 0, "cam": "house"})
    assert plain.status_code == named.status_code == 200
    assert plain.headers["x-kona-state"] == named.headers["x-kona-state"]
    status = c.get("/status.json").json()
    assert "capabilities" in status and "position" in status


def test_robot_status_has_no_house_numbers_in_it(both):
    c, _ = both
    status = c.get("/status.json", params={"cam": "robot"}).json()
    assert "state" in status and "last_error_kind" in status
    assert "capabilities" not in status and "position" not in status


@pytest.mark.parametrize("cam", ["", "kitchen", "../robot", "robot/", "ROBOT"])
def test_any_other_camera_name_is_a_404_and_reaches_nothing(both, cam):
    c, _ = both
    assert c.get("/snapshot.jpg", params={"cam": cam}).status_code == 404
    assert c.get("/status.json", params={"cam": cam}).status_code == 404


def test_an_off_robot_shows_robot_off_not_no_signal():
    def off():
        raise CameraOpenError("could not reach http://***@10.0.0.3:8080/: ConnectError")

    app = make(robot=True, robot_source=off)
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"})
        r = c.get("/snapshot.jpg", params={"cam": "robot"})
        assert r.content == ROBOT_OFF_JPEG and r.content != NO_SIGNAL_JPEG
        assert r.headers["x-kona-state"] != "live"
        assert r.headers["x-kona-error"] == "open"
        # The house camera is unaffected by the robot being off.
        house = c.get("/snapshot.jpg")
        assert house.headers["x-kona-error"] == ""
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_both_hubs_are_stopped_at_shutdown():
    app = make(robot=True)
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"})
        c.get("/snapshot.jpg", params={"cam": "robot"})
        c.get("/snapshot.jpg")
        assert app.state.robot_hub.status()["state"] != "idle"
    # Leaving the `with` ran the lifespan's finally.
    assert app.state.robot_hub.status()["state"] == "idle"
    assert app.state.hub.status()["state"] == "idle"


def test_robot_log_lines_and_threads_say_which_camera_they_are(caplog):
    import logging
    import threading
    import time

    def off():
        raise CameraOpenError("could not reach http://10.0.0.3:8080/: ConnectError")

    app = make(robot=True, robot_source=off)
    with TestClient(app) as c, caplog.at_level(logging.WARNING, logger="kona_tracker.camera"):
        c.post("/login", data={"passcode": "4242"})
        c.get("/snapshot.jpg", params={"cam": "robot"})
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not any(
            "robot open:" in r.getMessage() for r in caplog.records
        ):
            time.sleep(0.05)
        names = {t.name for t in threading.enumerate()}
        assert any(n.startswith("kona-robot-") for n in names)
    assert any("robot open:" in r.getMessage() for r in caplog.records)
    assert not any("camera open:" in r.getMessage() for r in caplog.records)
    app.state.hub.stop()
    app.state.robot_hub.stop()


def test_settings_page_describes_neither_camera_with_or_without_a_robot(both, house_only):
    """The camera and robot status rows were retired from Settings: the tab
    that shows the picture is where its state is put into words, in one
    vocabulary (poll.js). Neither camera gets a section here now."""
    for c, _ in (both, house_only):
        page = c.get("/settings").text
        assert 'id="camera-settings-title"' not in page
        assert 'id="robot-settings-title"' not in page
