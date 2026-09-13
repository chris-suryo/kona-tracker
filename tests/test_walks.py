"""The walk log and last night's interval, from the data layer to the page.

Every shape here was returned by Kona's collar on 2026-09-13 (probe rounds
10 and 11); the fixtures are those responses with the coordinates replaced.
The clock is pinned inside the fixture's day so "today" means the same
thing whatever the calendar says when the suite runs.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from conftest import fake_fi_handler
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.client import FiClient
from kona_tracker.fi.parse import LocationPoint, Overnight, Walk
from kona_tracker.fi.service import FiService, FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import (
    activity_context,
    activity_json,
    distance_label,
    overnight_labels,
    walk_context,
    walk_rows,
)

# 10:00 in Chicago, the mock profile's timezone; the fixture walks ran
# 07:18-09:24 that morning and one more the afternoon before.
FIXTURE_NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)
CHICAGO = ZoneInfo("America/Chicago")


def _service() -> FiService:
    def make_client() -> FiClient:
        return FiClient(transport=httpx.MockTransport(fake_fi_handler))

    return FiService(
        "chris@example.com", "correct", client_factory=make_client, clock=lambda: FIXTURE_NOW
    )


def _client(fi_service) -> TestClient:
    settings = Settings(passcode="4242", secret="s")
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100), fi_service=fi_service)
    c = TestClient(app)
    c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
    return c


def test_distance_reads_in_miles_and_short_hops_in_feet():
    assert distance_label(6449) == "4.0 mi"
    assert distance_label(2021) == "1.3 mi"
    assert distance_label(1378.568) == "0.9 mi"
    assert distance_label(120) == "390 ft"
    assert distance_label(0) == "0 ft"
    assert distance_label(None) is None and distance_label(-1) is None


def test_walk_rows_keep_today_only_on_kona_s_clock_and_keep_the_car_ride():
    walks = (
        Walk(
            "late",
            "walk",
            datetime(2026, 9, 10, 13, 14, tzinfo=UTC),
            datetime(2026, 9, 10, 14, 24, tzinfo=UTC),
            11353,
            6449,
            None,
            (LocationPoint(30.0, -97.0),) * 2,
        ),
        Walk(
            "ride",
            "travel",
            datetime(2026, 9, 10, 12, 18, tzinfo=UTC),
            datetime(2026, 9, 10, 12, 23, tzinfo=UTC),
            0,
            1378.5,
        ),
        # 21:00Z on the 9th is 16:00 Chicago on the 9th: yesterday, whatever UTC says.
        Walk(
            "old",
            "walk",
            datetime(2026, 9, 9, 21, 0, tzinfo=UTC),
            datetime(2026, 9, 9, 21, 30, tzinfo=UTC),
            3000,
            1500,
        ),
        # 04:30Z on the 10th is 23:30 Chicago on the 9th: also yesterday.
        Walk(
            "midnight",
            "walk",
            datetime(2026, 9, 10, 4, 30, tzinfo=UTC),
            datetime(2026, 9, 10, 5, 0, tzinfo=UTC),
            900,
            400,
        ),
    )
    rows = walk_rows(walks, FIXTURE_NOW.astimezone(CHICAGO), CHICAGO)
    assert [r["id"] for r in rows] == ["late", "ride"]
    late, ride = rows
    assert late["label"] == "Walk" and late["span"] == "08:14 – 09:24"
    assert late["duration"] == [("1", "h"), ("10", "m")]
    assert late["steps"] == "11,353" and late["distance"] == "4.0 mi"
    assert late["href"] == "/walks/late"
    assert ride["label"] == "Car ride" and ride["steps"] is None, "a car ride has no steps to show"
    assert ride["href"] is None, "no route, no page"


def test_a_walk_without_a_route_lists_but_does_not_link():
    walk = Walk("w", "walk", FIXTURE_NOW, FIXTURE_NOW, 10, 5)
    (row,) = walk_rows((walk,), FIXTURE_NOW, None)
    assert row["href"] is None


def test_overnight_labels_say_when_and_how_often_she_woke():
    night = Overnight(
        date=None,
        sleep_seconds=27832,
        sleep_start=datetime(2026, 9, 12, 4, 20, tzinfo=UTC),
        sleep_end=datetime(2026, 9, 12, 12, 4, tzinfo=UTC),
        interruptions=(
            (datetime(2026, 9, 12, 7, 0, tzinfo=UTC), datetime(2026, 9, 12, 7, 5, tzinfo=UTC)),
            (datetime(2026, 9, 12, 9, 10, tzinfo=UTC), datetime(2026, 9, 12, 9, 25, tzinfo=UTC)),
        ),
    )
    eastern = ZoneInfo("America/New_York")
    labels = overnight_labels(night, eastern)
    assert labels["span"] == "00:20 – 08:04"
    assert labels["wake_label"] == "woke twice" and labels["wake_count"] == 2
    assert labels["interruptions"] == ["03:00 – 03:05", "05:10 – 05:25"]
    assert overnight_labels(None, eastern) is None
    quiet = Overnight(None, 100, night.sleep_start, night.sleep_end)
    assert overnight_labels(quiet, eastern)["wake_label"] == "slept through"
    once = Overnight(None, 100, night.sleep_start, night.sleep_end, night.interruptions[:1])
    assert overnight_labels(once, eastern)["wake_label"] == "woke once"


def test_activity_page_lists_today_s_walks_and_last_night_s_span():
    with _client(_service()) as c:
        page = c.get("/activity").text
    assert "Walks today" in page
    assert 'href="/walks/walk-late"' in page and 'href="/walks/walk-early"' in page
    assert 'href="/walks/walk-yesterday"' not in page, "yesterday's walk is not today's"
    assert "Car ride" in page and 'href="/walks/ride"' not in page
    assert "11,353" in page and "4.0 mi" in page
    # The rest metric now carries Fi's own interval for the night, Chicago time.
    assert "23:20 – 07:04 · woke twice" in page


def test_walk_page_draws_the_route_and_reports_fi_s_figures():
    with _client(_service()) as c:
        r = c.get("/walks/walk-late")
        assert r.status_code == 200
        page = r.text
        assert "Today · 08:14 – 09:24" in page
        assert "11,353" in page and "4.0 mi" in page and "8 GPS fixes" in page
        assert '<script type="application/json" id="map-points">' in page
        assert page.count('"lat"') == 8, "every fix of the route, none invented"
        assert "pace" in page
        # An id the feed no longer holds is a 404, not an empty page.
        assert c.get("/walks/not-a-walk").status_code == 404
        assert c.get("/walks/../etc").status_code in (404, 422)


def test_walk_page_requires_login():
    with _client(_service()) as c:
        c.post("/logout")
        assert c.get("/walks/walk-late", follow_redirects=False).status_code == 303


def test_activity_json_carries_walks_and_overnight():
    with _client(_service()) as c:
        data = c.get("/activity.json").json()
    walks = data["walks"]
    assert [w["kind"] for w in walks] == ["walk", "walk", "travel", "walk"]
    assert walks[0]["steps"] == 11353 and walks[0]["distance_m"] == 6449
    assert walks[0]["path_points"] == 8 and walks[2]["path_points"] == 0
    night = data["overnight"]
    assert night["sleep_s"] == 30600 and len(night["interruptions"]) == 2
    assert night["interruptions"][0]["start"] < night["interruptions"][1]["start"]


def test_walk_context_names_the_day_relative_to_now():
    walk = Walk(
        "w",
        "walk",
        datetime(2026, 9, 9, 13, 0, tzinfo=UTC),
        datetime(2026, 9, 9, 13, 30, tzinfo=UTC),
        1000,
        800,
        path=(LocationPoint(30.0, -97.0), LocationPoint(30.001, -97.001)),
    )
    snap = FiSnapshot(fetched_at=FIXTURE_NOW, walks=(walk,))
    ctx = walk_context(snap, "w", configured=True)
    assert ctx["day"] == "Yesterday" and ctx["points"] == 2
    assert ctx["pace"] is not None and ctx["pace"].endswith("/mi")
    assert walk_context(snap, "missing", configured=True) is None
    assert walk_context(None, "w", configured=False) is None


def test_unconfigured_activity_json_has_null_walks():
    assert activity_json(None, configured=False)["walks"] is None
    assert activity_json(None, configured=False)["overnight"] is None
    ctx = activity_context(None, configured=False)
    assert ctx["walks_today"] == [] and ctx["overnight"] is None
