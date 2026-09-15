"""Today by the hour: rest and steps in 24 buckets, from restFeed and
stepFeed (period: DAY) -- the Fi app's Day tab, proven on Kona's collar in
probe round 11 (2026-09-13). The fixture is a plausible day with the clock
pinned at 10:00 Chicago, so hours 11-23 have not happened yet."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from conftest import fake_fi_handler, fixture
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.client import FiClient
from kona_tracker.fi.parse import HOURS_IN_DAY, HourBucket, HourlyDay, hourly_from
from kona_tracker.fi.service import FiService, FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import hourly_buckets, hourly_json, rest_history_context, steps_context

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


def test_parser_requires_exactly_twenty_four_buckets_per_feed():
    day = hourly_from(fixture("hourly")["data"])
    assert day is not None and len(day.hours) == HOURS_IN_DAY
    assert day.rest_present and day.steps_present and day.steps_total == 4210
    assert day.hours[0] == HourBucket(sleep_s=3600, nap_s=0, steps=40)
    assert day.hours[9].nap_s == 1290 and day.hours[9].rest_s == 1290
    assert day.hours[23] == HourBucket(None, None, None), "unelapsed hours are None, not zero"

    short = fixture("hourly")["data"]
    short["pet"]["restFeed"]["restSummary"]["restData"] = short["pet"]["restFeed"]["restSummary"][
        "restData"
    ][:23]
    half = hourly_from(short)
    assert half is not None and not half.rest_present and half.steps_present, (
        "23 rest buckets is a shape change; the steps half still stands"
    )
    assert hourly_from({"data": {}}) is None and hourly_from(None) is None


def test_buckets_mark_hours_still_to_come_and_never_read_them_as_zero():
    day = hourly_from(fixture("hourly")["data"])
    rest = hourly_buckets(day, "rest", FIXTURE_NOW, CHICAGO, "/rest")
    assert len(rest) == 24
    assert rest[0]["label"] == "12–1 am" and rest[0]["short"] == "00"
    assert rest[0]["value"] == 60 and rest[0]["sleep"] == 60 and rest[0]["nap"] == 0
    assert rest[9]["value"] == 22 and rest[9]["nap"] == 22
    assert not rest[10]["future"], "10:00 is the hour in progress, and Fi has begun counting it"
    assert rest[11]["future"] and rest[11]["value"] is None
    assert rest[0]["height"] == 150.0, "a full hour of sleep fills the chart"
    assert rest[0]["href"] == "/rest?hour=0#hours-title"

    steps = hourly_buckets(day, "steps", FIXTURE_NOW, CHICAGO, "/steps")
    assert steps[7]["value"] == 1480 and steps[1]["value"] == 0
    assert steps[7]["height"] == round(1480 / 3000 * 150, 2)
    assert hourly_buckets(None, "rest", FIXTURE_NOW, CHICAGO, "/rest") == []


def test_steps_chart_ceiling_grows_to_the_next_thousand_above_the_busiest_hour():
    hours = tuple(HourBucket(steps=4400 if i == 8 else 10) for i in range(24))
    day = HourlyDay(start=datetime(2026, 9, 10, 5, tzinfo=UTC), hours=hours, steps_present=True)
    snap = FiSnapshot(fetched_at=FIXTURE_NOW, hourly=day)
    ctx = steps_context(snap, configured=True)
    assert ctx["hours_maximum"] == 5000
    assert ctx["hours"][8]["height"] == round(4400 / 5000 * 150, 2)


def test_rest_page_shows_today_by_hour_above_the_days():
    with _client(_service()) as c:
        body = c.get("/rest").text
    assert "Today by hour" in body and "Rest by day" in body
    assert body.index("Today by hour") < body.index("Rest by day")
    assert "Through 10:00" in body
    assert 'href="/rest?hour=9#hours-title"' in body
    assert "So far today:" in body
    with _client(_service()) as c:
        body = c.get("/rest?hour=9").text
    assert "9–10 am" in body and "of rest" in body and "naps" in body


def test_steps_page_reads_fi_s_total_and_the_hour_buckets():
    with _client(_service()) as c:
        body = c.get("/steps").text
        assert "Steps by hour" in body and "4,210" in body and "of 9,000" in body
        assert "Through 10:00" in body and "View readings" in body
        assert body.count("future-bar") == 13, "hours 11-23 have not happened"
        chosen = c.get("/steps?hour=7").text
        assert "7–8 am" in chosen and "1,480 steps" in chosen
        assert c.get("/steps?hour=24").status_code == 422
        home = c.get("/activity").text
        assert 'href="/steps"' in home and "View steps" in home


def test_steps_page_without_fi_says_so():
    settings = Settings(passcode="4242", secret="s")
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        body = c.get("/steps").text
    assert "Fi is not configured" in body and "Steps by hour" not in body


def test_activity_json_carries_the_hour_buckets():
    with _client(_service()) as c:
        data = c.get("/activity.json").json()["hourly"]
    assert data["steps_total"] == 4210 and len(data["hours"]) == 24
    assert data["hours"][9] == {"sleep_s": 0, "nap_s": 1290, "steps": 1050}
    assert data["hours"][23] == {"sleep_s": None, "nap_s": None, "steps": None}
    assert hourly_json(None) is None
    assert rest_history_context(None, configured=False)["hours"] == []
