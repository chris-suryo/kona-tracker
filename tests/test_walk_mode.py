"""Walk mode: the button that makes the server ask Fi more often.

The reason it exists, measured on 2026-09-13: Fi decides a walk has started
two to three minutes after it has, so auto-detect alone leaves the start of
every walk at the resting cadence. The person holding the lead knows sooner
than Fi does, so they get a button -- and Fi's own detection stays underneath
for the walks nobody pressed anything for.

The rules worth pinning: it expires by itself, it never polls faster than the
floor, a walk Fi *has* noticed speeds things up with no button at all, and a
carried-over route (a walk that ended) does not.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.parse import CollarStatus, LocationPoint
from kona_tracker.fi.service import (
    DEFAULT_REFRESH_SECONDS,
    LIVE_FLOOR_SECONDS,
    FiService,
    FiSnapshot,
)
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import live_button

NOW = datetime(2026, 9, 13, 15, 0, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = NOW):
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


def _service(clock: Clock, **kwargs) -> FiService:
    return FiService("a@b.c", "pw", clock=clock, **kwargs)


def test_live_mode_speeds_the_cadence_up_and_expires_by_itself():
    clock = Clock()
    fi = _service(clock, live_seconds=20, live_max_seconds=7200)
    assert fi._effective_ttl() == DEFAULT_REFRESH_SECONDS

    state = fi.start_live()
    assert state["live"] is True
    assert state["every_seconds"] == 20
    assert state["seconds_left"] == 7200
    assert fi._effective_ttl() == 20

    # Halfway through, still live and counting down honestly.
    clock.advance(3600)
    assert fi.live_state()["seconds_left"] == 3600

    # A button nobody switched off must not poll Fi all night.
    clock.advance(3601)
    assert fi.live_state()["live"] is False
    assert fi._effective_ttl() == DEFAULT_REFRESH_SECONDS


def test_stopping_is_immediate():
    clock = Clock()
    fi = _service(clock)
    fi.start_live()
    assert fi.stop_live()["live"] is False
    assert fi._effective_ttl() == DEFAULT_REFRESH_SECONDS


def test_the_fast_cadence_has_a_floor():
    """However the setting is written, this polls somebody else's private
    API. One second is not an option a config file gets to pick."""
    fi = _service(Clock(), live_seconds=1)
    fi.start_live()
    assert fi._effective_ttl() == LIVE_FLOOR_SECONDS


def test_a_walk_fi_has_noticed_speeds_up_with_no_button():
    """Chris's sister takes her out and presses nothing. Once Fi says walk,
    the page should keep up on its own."""
    clock = Clock()
    fi = _service(clock, live_seconds=20)
    fi._snapshot = FiSnapshot(
        fetched_at=NOW,
        status=CollarStatus(
            activity="walk",
            positions=(LocationPoint(42.37, -71.11, recorded_at=NOW),),
        ),
    )
    assert fi._effective_ttl() == 20


def test_a_finished_walk_does_not_keep_the_fast_cadence():
    """When a walk ends the service carries its last route forward so the
    map still has something to draw. That carried route is history, and it
    must not hold the server at the walking cadence for the rest of the day."""
    clock = Clock()
    fi = _service(clock, live_seconds=20)
    fi._snapshot = FiSnapshot(
        fetched_at=NOW,
        status=CollarStatus(
            activity="walk",
            positions=(LocationPoint(42.37, -71.11, recorded_at=NOW),),
            positions_carried=True,
        ),
    )
    assert fi._effective_ttl() == DEFAULT_REFRESH_SECONDS


@pytest.mark.parametrize(
    ("state", "on", "label"),
    [
        ({"live": False, "seconds_left": 0, "every_seconds": 20}, False, "Start walk"),
        ({"live": True, "seconds_left": 1800, "every_seconds": 20}, True, "Stop walk"),
    ],
)
def test_the_button_says_what_pressing_it_does(state, on, label):
    button = live_button(state)
    assert button["offered"] is True
    assert button["on"] is on
    assert button["label"] == label
    # The caption used to print our polling interval in both states. That is
    # a fact about this server, not about Kona -- Chris's words on 2026-09-15
    # were "I don't ever need to see that". Off, the button speaks for
    # itself and the note is empty; on, the one thing worth saying is that
    # it stops by itself, so nobody leaves it draining the collar.
    assert "20 s" not in button["note"], "our cadence is not news about a dog"
    if on:
        assert button["note"] == "Stops on its own in 30 min"
    else:
        assert button["note"] == ""


def test_no_collar_means_no_button_rather_than_a_dead_one():
    button = live_button(None)
    assert button["offered"] is False
    assert button["label"] is None


class StubFi:
    def __init__(self):
        self.snapshot_value = FiSnapshot(fetched_at=NOW, status=CollarStatus())
        self.calls: list[bool] = []
        self._live = False

    def snapshot(self, force: bool = False) -> FiSnapshot:
        return self.snapshot_value

    def peek(self) -> FiSnapshot:
        return self.snapshot_value

    def start_live(self) -> dict:
        self.calls.append(True)
        self._live = True
        return self.live_state()

    def stop_live(self) -> dict:
        self.calls.append(False)
        self._live = False
        return self.live_state()

    def live_state(self) -> dict:
        return {
            "live": self._live,
            "seconds_left": 7200 if self._live else 0,
            "every_seconds": 20,
        }


def test_the_route_starts_and_stops_and_needs_the_passcode():
    fi = StubFi()
    app = create_app(
        Settings(passcode="4242", secret="test-secret"),
        source_factory=lambda: FakeSource(fps=100),
        fi_service=fi,
    )
    with TestClient(app) as client:
        # Pinned to the exact redirect, not "303 or 401": a looser assertion
        # would still pass if the gate degraded, which is the whole property
        # this test is named for.
        blocked = client.post("/live", data={"on": "true"}, follow_redirects=False)
        assert blocked.status_code == 303
        assert blocked.headers["location"] == "/login"
        assert fi.calls == []  # a stranger cannot start it

        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        started = client.post("/live", data={"on": "true"}).json()
        assert started["live"] is True and started["every_seconds"] == 20
        assert "Stop walk" in client.get("/activity").text

        stopped = client.post("/live", data={"on": "false"}).json()
        assert stopped["live"] is False
        assert fi.calls == [True, False]
        assert "Start walk" in client.get("/activity").text
    app.state.hub.stop()


def test_without_a_collar_the_route_says_so_instead_of_erroring():
    app = create_app(
        Settings(passcode="4242", secret="test-secret"),
        source_factory=lambda: FakeSource(fps=100),
    )
    with TestClient(app) as client:
        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        assert client.post("/live", data={"on": "true"}).status_code == 409
        # ... and the page does not offer a button that cannot work.
        assert "walk-toggle" not in client.get("/activity").text
    app.state.hub.stop()
