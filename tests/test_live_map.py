"""The full-screen live map: /map, /map.json, and the freshness labels.

Chris asked for this after the 2026-09-13 walk -- the Activity card's map is
a tile that cannot be enlarged, and on a walk the map is the whole point.
The rules worth pinning: it never invents a position the Activity page would
not claim, the fix age travels as seconds rather than a timestamp, and a
stale snapshot says so instead of leaving a confident dot on screen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.parse import CollarStatus, LocationPoint
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import (
    MAP_TITLES,
    _age_seconds,
    fix_age_label,
    live_map_context,
    live_map_json,
)

NOW = datetime(2026, 9, 13, 15, 0, tzinfo=UTC)


class StubFi:
    """Answers with one fixed snapshot: the page is what is under test."""

    def __init__(self, snapshot: FiSnapshot):
        self._snapshot = snapshot

    def snapshot(self, force: bool = False) -> FiSnapshot:
        return self._snapshot

    def peek(self) -> FiSnapshot:
        return self._snapshot

    def live_state(self) -> dict:
        """The "Start walk" cadence. Off, so the page draws the resting copy."""
        return {"live": False, "seconds_left": 0, "every_seconds": 20}


def _walking(minutes_ago: int = 2, points: int = 3) -> FiSnapshot:
    positions = tuple(
        LocationPoint(
            42.37 + n / 1000.0,
            -71.11 + n / 1000.0,
            recorded_at=NOW - timedelta(seconds=minutes_ago * 60 + (points - n) * 30),
            accuracy_m=8.0,
        )
        for n in range(points)
    )
    return FiSnapshot(
        fetched_at=NOW,
        status=CollarStatus(
            activity="walk",
            activity_since=NOW - timedelta(minutes=24),
            walk_distance=878.4,
            positions=positions,
        ),
    )


def test_fix_age_travels_as_seconds_not_a_timestamp():
    """The page counts up from a number, so a skewed phone clock cannot
    turn a fresh fix into a stale-looking one."""
    assert _age_seconds(NOW - timedelta(seconds=47), NOW) == 47
    # A collar fix stamped slightly in the future is a clock disagreement,
    # not a negative age.
    assert _age_seconds(NOW + timedelta(seconds=5), NOW) == 0
    assert _age_seconds(None, NOW) is None


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "0 s ago"), (47, "47 s ago"), (89, "89 s ago"), (120, "2 min ago"), (7200, "2 h ago")],
)
def test_fix_age_label_uses_the_unit_a_person_would_say(seconds, expected):
    assert fix_age_label(seconds) == expected
    assert fix_age_label(None) is None


def test_walk_shows_distance_in_miles_and_elapsed_time():
    context = live_map_context(_walking(), configured=True)
    assert context["map_title"] == MAP_TITLES["current"]
    # 878.4 m, the real figure from Chris's walk, in the units the rest of
    # the app already used.
    assert context["walk_distance"] == "0.5 mi"
    assert context["elapsed"] == [("24", "m")]
    assert context["fix_age_s"] is not None


def test_json_carries_the_points_and_nothing_heavy():
    payload = live_map_json(_walking(), configured=True)
    assert payload["kind"] == "current"
    assert len(payload["points"]) == 3
    assert payload["points"][0]["lat"] == pytest.approx(42.37)
    assert payload["live"] is True
    assert payload["distance"] == "0.5 mi"
    # The page polls this every ten seconds while walking, so the rest
    # history, walk log and hourly buckets deliberately stay out of it.
    for heavy in ("rest_history", "walks", "hourly", "overnight"):
        assert heavy not in payload


def test_a_stale_snapshot_never_claims_she_is_walking_now():
    """The map may only say "on a walk" about a snapshot that is current.
    A fix Fi sent before it stopped answering is real, but it is history."""
    walking = _walking()
    stale = FiSnapshot(
        fetched_at=walking.fetched_at,
        status=walking.status,
        stale=True,
    )
    payload = live_map_json(stale, configured=True)
    assert payload["stale"] is True
    assert payload["kind"] == "last"
    assert payload["title"] == MAP_TITLES["last"]
    assert payload["live"] is False


def test_no_position_is_an_honest_blank_not_a_guess():
    payload = live_map_json(FiSnapshot(fetched_at=NOW, status=CollarStatus()), configured=True)
    assert payload["points"] == []
    assert payload["kind"] is None
    assert payload["title"] == "Location unavailable"
    assert payload["fix_age_s"] is None


def test_not_configured_says_so_rather_than_erroring():
    payload = live_map_json(None, configured=False)
    assert payload["configured"] is False
    assert payload["points"] == []


def test_map_page_renders_and_activity_links_to_it():
    settings = Settings(passcode="4242", secret="test-secret")
    app = create_app(
        settings, source_factory=lambda: FakeSource(fps=100), fi_service=StubFi(_walking())
    )
    with TestClient(app) as client:
        # Every route is behind the passcode, this one included.
        assert client.get("/map", follow_redirects=False).status_code == 303
        assert client.get("/map.json", follow_redirects=False).status_code in (303, 401)
        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        body = client.get("/map").text
        assert 'id="kona-map"' in body
        assert "map_live.js" in body
        # Seeded from the server, so the first paint is a real number rather
        # than an em dash waiting on the first poll.
        assert 'id="live-age"' in body
        assert "0.5 mi" in body
        feed = client.get("/map.json").json()
        assert feed["kind"] == "current" and len(feed["points"]) == 3
        assert 'href="/map"' in client.get("/activity").text
    app.state.hub.stop()
