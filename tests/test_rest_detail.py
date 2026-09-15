"""The real /rest page: Kona's daily rest history, drawn from the collar.

Two layers. The context math is checked against the five daily windows the
collar actually returned on 2026-09-11 (see test_rest_history.py for the
fixture's provenance). The route is checked end to end through the same Fi
mock every other page test uses, whose `rest.json` returns two windows.
"""

from datetime import UTC, date, datetime, timedelta

import httpx
from conftest import fake_fi_handler

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.client import FiClient
from kona_tracker.fi.parse import RestWindow, rest_history
from kona_tracker.fi.service import FiService, FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import rest_history_context

try:
    from fastapi.testclient import TestClient
except ImportError:  # pragma: no cover
    from starlette.testclient import TestClient


def _w(day: int, sleep, nap) -> RestWindow:
    start = datetime(2026, 9, day, 4, 0, tzinfo=UTC)
    return RestWindow(start=start, end=start + timedelta(days=1), sleep=sleep, nap=nap)


MEASURED = [
    _w(11, 0, 23356),  # today, in progress
    _w(10, 24760, 7373),
    _w(9, 8796, 6971),
    _w(8, 18406, 16545),
    _w(7, 0, 13576),  # collar set up this day
]
NOW = datetime(2026, 9, 11, 20, 57, tzinfo=UTC)
COLLAR_START = date(2026, 9, 7)


def _snapshot(days=MEASURED, **kw) -> FiSnapshot:
    return FiSnapshot(fetched_at=NOW, rest_days=rest_history(days, NOW, COLLAR_START), **kw)


def test_context_draws_one_bar_per_day_in_minutes_oldest_first():
    ctx = rest_history_context(_snapshot(), configured=True)

    assert ctx["has_days"] and ctx["total_days"] == 5
    assert [b["short"] for b in ctx["buckets"]] == ["Mon", "Tue", "Wed", "Thu", "Fri"]
    # Named by the window's start as Fi sent it, the hero's convention.
    assert ctx["buckets"][0]["date"] == "2026-09-07" and ctx["buckets"][0]["label"] == "7 Sep"
    assert ctx["range_label"] == "7 Sep – 11 Sep"
    assert ctx["excluded_note"] == "today and the collar's first day are excluded"
    thu = ctx["buckets"][3]
    assert thu["sleep"] == round(24760 / 60) and thu["nap"] == round(7373 / 60)
    assert thu["value"] == round((24760 + 7373) / 60)
    assert thu["complete"] is True and thu["partial"] is False
    # Every bar has the geometry the shared CSS and SVG expect.
    for b in ctx["buckets"]:
        assert {"x", "width", "height", "sleep_height", "nap_height", "href"} <= b.keys()


def test_average_covers_complete_days_only_and_says_how_many():
    """Today and the collar's first day both draw, both are excluded, and the
    page states the count so "average" is never mistaken for "every day"."""
    ctx = rest_history_context(_snapshot(), configured=True)

    assert ctx["complete_days"] == 3
    complete_totals = [(24760 + 7373), (8796 + 6971), (18406 + 16545)]
    expected = round(sum(round(t / 60) for t in complete_totals) / 3)
    assert ctx["average"] == expected
    assert ctx["average_sleep"] == round(sum(round(s / 60) for s in (24760, 8796, 18406)) / 3)
    today, first = ctx["buckets"][-1], ctx["buckets"][0]
    assert today["in_progress"] and today["partial"] and not today["complete"]
    assert first["partial_first_day"] and first["partial"] and not first["complete"]


def test_no_reading_stays_none_not_zero_in_chart_and_average():
    days = [_w(9, None, None), _w(8, 3600, 600)]
    ctx = rest_history_context(_snapshot(days), configured=True)

    missing = next(b for b in ctx["buckets"] if b["short"] == "Wed")
    assert missing["value"] is None and missing["sleep"] is None and missing["nap"] is None
    assert missing["height"] == 0, "drawn as a missing mark, not a zero-height bar"
    # The average ignores the None rather than counting it as 0.
    assert ctx["average"] == round((3600 + 600) / 60)
    assert ctx["complete_days"] == 2


def test_exclusion_note_names_only_what_was_actually_left_out():
    """With no collar cutoff there is no "first day" to exclude, and a page
    that claimed one would be asserting a measurement that never happened."""
    only_today = rest_history(MEASURED[:2], NOW, None)  # 10 Sep complete, 11 Sep in progress
    ctx = rest_history_context(FiSnapshot(fetched_at=NOW, rest_days=only_today), configured=True)
    assert ctx["excluded_note"] == "today is excluded"
    assert ctx["complete_days"] == 1

    all_complete = rest_history(MEASURED[1:4], NOW, None)  # 8, 9, 10 Sep, all finished
    ctx = rest_history_context(FiSnapshot(fetched_at=NOW, rest_days=all_complete), configured=True)
    assert ctx["excluded_note"] is None
    assert ctx["complete_days"] == 3


def test_chart_floor_stops_a_quiet_week_looking_busy():
    quiet = [_w(9, 1200, 600), _w(8, 900, 300)]
    ctx = rest_history_context(_snapshot(quiet), configured=True)
    assert ctx["maximum"] == 720, "twelve-hour floor; 30 minutes must not fill the chart"
    assert ctx["buckets"][0]["height"] < 10


def test_unconfigured_and_empty_states_are_explicit():
    unconfigured = rest_history_context(None, configured=False)
    assert unconfigured["has_days"] is False and unconfigured["configured"] is False

    empty = rest_history_context(FiSnapshot(fetched_at=NOW, problem="Fi is down"), configured=True)
    assert empty["has_days"] is False and empty["problem"] == "Fi is down"
    assert empty["average"] is None and empty["complete_days"] == 0


# ---------------------------------------------------------------- the route


#: The mock's rest.json holds the windows for 9 and 10 September. Pin the
#: service's clock inside the 10th so that day is "in progress" and the 9th
#: is complete, whatever the real date is when the suite runs.
FIXTURE_NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def _service() -> FiService:
    def make_client() -> FiClient:
        return FiClient(transport=httpx.MockTransport(fake_fi_handler))

    return FiService(
        "chris@example.com", "correct", client_factory=make_client, clock=lambda: FIXTURE_NOW
    )


def _client(fi_service) -> TestClient:
    settings = Settings(passcode="4242", secret="s", preview_enabled=True)
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100), fi_service=fi_service)
    c = TestClient(app)
    c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
    return c


def test_rest_page_renders_real_days_and_never_the_sample_vocabulary():
    with _client(_service()) as c:
        r = c.get("/rest")
    assert r.status_code == 200
    body = r.text
    assert "Rest by day" in body and "View readings" in body
    assert "Average daily rest" in body
    # The mock's rest.json carries two daily windows: one complete, one today.
    assert "1 complete day of 2" in body
    # The mock has no collar cutoff, so only today is excluded -- and the
    # page must not claim a "first day" exclusion that did not happen.
    assert "Today is excluded" in body and "first day" not in body
    # Days are named as the hero names them: the window's start date as Fi
    # sent it. The fixture's windows start on the 9th and 10th; the mock's
    # Chicago timezone must not pull them back a day.
    assert "9 Sep – 10 Sep" in body
    assert "Checked Fi 10:00 am CDT" in body
    # Nothing from the design-preview page may appear here. "by hour" is no
    # longer on the list: since 2026-09-13 the hours are Fi's own
    # (restFeed period: DAY), and the page draws them above the days.
    for word in ("sample", "Sample", "Fictional", "fictional", "Design preview"):
        assert word not in body, word
    assert "Today by hour" in body


def test_rest_page_selected_day_reads_back_its_numbers():
    with _client(_service()) as c:
        r = c.get("/rest?selected=0")
    assert r.status_code == 200
    assert 'aria-current="true"' in r.text
    assert "of rest" in r.text


def test_rest_page_without_fi_says_so_rather_than_drawing_nothing():
    with _client(None) as c:
        r = c.get("/rest")
    assert r.status_code == 200
    assert "Fi is not configured" in r.text and "FI_EMAIL" in r.text


def test_homepage_links_view_rest_to_the_real_page_and_preview_to_the_sample():
    with _client(_service()) as c:
        live = c.get("/activity").text
        sample = c.get("/activity?preview=1").text
    assert 'href="/rest"' in live and "/preview/rest" not in live
    assert 'href="/preview/rest"' in sample and 'href="/rest"' not in sample


def test_activity_json_carries_rest_history_with_its_flags():
    with _client(_service()) as c:
        data = c.get("/activity.json").json()
    days = data["rest_history"]
    assert len(days) == 2
    assert [d["date"] for d in days] == sorted(d["date"] for d in days), "oldest first"
    assert {"sleep_s", "nap_s", "total_s", "complete", "in_progress", "partial_first_day"} <= days[
        0
    ].keys()
    assert sum(1 for d in days if d["in_progress"]) == 1
    assert all(isinstance(d["complete"], bool) for d in days)
