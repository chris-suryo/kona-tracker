"""The Activity page's numbers, as Python decides them before Jinja sees them.

Chris's phone list, 2026-09-11: the ring must go past 100%, naps and last
night read as hours and minutes, and the bottom row must say something he
can act on. Every case here was a real reading or a real complaint.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.parse import ActivityStats, CollarStatus, PetProfile, RestWindow
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import activity_context, duration_parts, step_ring

NOW = datetime(2026, 9, 11, 15, 0, tzinfo=UTC)
#: Kona's zone, the value `tests/fixtures/status.json` carries. Pinned here
#: because every clock face on the page is rendered in *her* zone, so a test
#: that writes one as a literal is really asserting the machine it ran on.
#: `tzdata` is a declared dependency, so this loads on Windows too.
CHICAGO = ZoneInfo("America/Chicago")


class StubFi:
    """Answers with one fixed snapshot: the page is what is under test."""

    def __init__(self, snapshot: FiSnapshot):
        self._snapshot = snapshot

    def snapshot(self, force: bool = False) -> FiSnapshot:
        return self._snapshot

    def peek(self) -> FiSnapshot:
        return self._snapshot


def render(snapshot: FiSnapshot) -> str:
    settings = Settings(passcode="4242", secret="test-secret")
    app = create_app(
        settings, source_factory=lambda: FakeSource(fps=100), fi_service=StubFi(snapshot)
    )
    with TestClient(app) as client:
        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        page = client.get("/activity").text
    app.state.hub.stop()
    return page


@pytest.mark.parametrize(
    ("steps", "goal", "expected"),
    [
        (14_000, 28_000, {"percent": 50, "arc": 50.0, "overflow": 0.0}),
        (28_000, 28_000, {"percent": 100, "arc": 100.0, "overflow": 0.0}),
        # The day she does half again her goal used to read "exactly done".
        (42_000, 28_000, {"percent": 150, "arc": 100.0, "overflow": 50.0}),
        # A third lap would paint over the second and say nothing new.
        (100_000, 28_000, {"percent": 357, "arc": 100.0, "overflow": 100.0}),
        (0, 28_000, {"percent": 0, "arc": 0.0, "overflow": 0.0}),
        (3_000, None, {"percent": 0, "arc": 0.0, "overflow": 0.0}),
        (None, 28_000, {"percent": 0, "arc": 0.0, "overflow": 0.0}),
        (3_000, 0, {"percent": 0, "arc": 0.0, "overflow": 0.0}),
    ],
)
def test_the_ring_keeps_going_past_the_goal(steps, goal, expected):
    assert step_ring(steps, goal) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (30_600, [("8", "h"), ("30", "m")]),
        (1_290, [("22", "m")]),  # 21.5 minutes rounds up, not down to 0.4 h
        (7_200, [("2", "h")]),  # a whole number of hours does not say "0m"
        (0, [("0", "m")]),  # zero naps is known, not missing
        (29, [("0", "m")]),
        (None, None),
        (30_600 * 60, None),  # not credible as seconds: the page shows raw
    ],
)
def test_durations_read_as_hours_and_minutes(seconds, expected):
    assert duration_parts(seconds) == expected


def _snapshot(**status) -> FiSnapshot:
    start = NOW.replace(hour=0, minute=0) - timedelta(days=1)
    return FiSnapshot(
        fetched_at=NOW,
        pet_name="Kona",
        window=RestWindow(start, start + timedelta(days=1), 30_600, 0),
        today=RestWindow(start + timedelta(days=1), start + timedelta(days=2), 0, 1_290),
        activity=ActivityStats(42_000, 28_000, 900),
        week=ActivityStats(90_000, 196_000, None),
        profile=PetProfile(name="Kona", timezone="America/Chicago"),
        status=CollarStatus(**status) if status else None,
    )


def test_the_page_draws_a_second_lap_and_prints_the_true_percentage():
    page = render(_snapshot())
    assert "150%" in page and 'aria-label="150 percent' in page
    assert 'class="value over"' in page and 'stroke-dashoffset="50.0"' in page
    # And not when she is short of it.
    modest = replace(_snapshot(), activity=ActivityStats(14_000, 28_000, 0))
    page = render(modest)
    assert "50%" in page and 'class="value over"' not in page


def test_the_page_prints_naps_and_last_night_as_hours_and_minutes():
    page = render(_snapshot())
    assert "8<small>h</small>30<small>m</small>" in page
    assert "22<small>m</small>" in page
    assert "<small>h</small></span>\n    <span>so far today" not in page


def test_resting_since_uses_the_start_fi_already_sends():
    since = NOW - timedelta(hours=2, minutes=18)
    expected = since.astimezone(CHICAGO).strftime("%H:%M")
    ctx = activity_context(_snapshot(activity="rest", activity_since=since), configured=True)
    assert ctx["activity_since"] == expected
    page = render(_snapshot(activity="rest", activity_since=since))
    assert "Resting" in page and f"since {expected}" in page
    # A walk keeps its distance and gains the start time beside it.
    page = render(_snapshot(activity="walk", activity_since=since, walk_distance=420))
    assert f"420 m so far · since {expected}" in page
    # Nothing to say without a start; the line simply is not there.
    assert activity_context(_snapshot(activity="rest"), configured=True)["activity_since"] is None


def test_a_rest_that_began_on_an_earlier_day_names_the_day():
    """Otherwise "since 17:00" on a dog who settled last night reads as this
    afternoon. The boundary is *her* local midnight, not the server's."""
    began = NOW - timedelta(hours=17)
    local = began.astimezone(CHICAGO)
    assert local.date() < NOW.astimezone(CHICAGO).date(), "this fixture must cross her midnight"
    ctx = activity_context(_snapshot(activity="rest", activity_since=began), configured=True)
    assert ctx["activity_since"] == f"{local.day} {local:%b} {local:%H:%M}"


def test_without_fi_s_timezone_since_falls_back_to_the_servers_clock():
    """The same rule every other time on the page follows: no zone from Fi
    means this machine's clock, never UTC dressed up as hers. Written from
    `.astimezone()` rather than a literal so it is true on any machine --
    the mistake this file made on 2026-09-11, which only showed up on
    Chris's PC because both CI runners are UTC.

    `endswith`, not `==`, because the day prefix is genuinely
    machine-dependent here: run this far enough east and the server's own
    "today" has already rolled over, so a rest that began 2 h 18 m ago
    began on an earlier local date and the label correctly says so. The
    time of day is the part that must follow the server's clock.
    """
    since = NOW - timedelta(hours=2, minutes=18)
    zoneless = replace(
        _snapshot(activity="rest", activity_since=since), profile=PetProfile(name="Kona")
    )
    ctx = activity_context(zoneless, configured=True)
    assert ctx["activity_since"].endswith(since.astimezone().strftime("%H:%M"))
    assert ctx["clock_zone"] is None, "an unnamed clock is never labelled as hers"


def test_the_bottom_row_names_the_day_the_weekly_total_arrives():
    """ "Building a clean baseline" was a status line about our data hygiene.
    Chris asked for something he can use: the date the total becomes real."""
    snapshot = replace(
        _snapshot(), data_start=date(2026, 9, 10), week=None, historical_totals_hidden=True
    )
    ctx = activity_context(snapshot, configured=True)
    assert ctx["week_available_label"] == "17 Sep"
    page = render(snapshot)
    assert "Available 17 Sep" in page and "Building a clean baseline" not in page
    assert "weekly total waits until 17 Sep" in page
    # Nothing unusual: no lecture about midnight under the numbers.
    ordinary = render(_snapshot())
    assert "midnight to midnight" not in ordinary and "week_available" not in ordinary
    assert activity_context(_snapshot(), configured=True)["week_available_label"] is None
