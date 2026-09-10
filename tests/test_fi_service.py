"""The Fi snapshot path, end to end, against a mocked API.

The theme is that nothing here may invent a number. A missing field, an
unrecognised unit, a login that fails and a refresh that fails on top of good
data are each a distinct visible state, and each is pinned below.
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from conftest import fake_fi_handler, fixture
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.client import FiClient
from kona_tracker.fi.parse import (
    RestWindow,
    activity_from,
    hours_from_duration,
    pets_from,
    rest_from,
)
from kona_tracker.fi.service import FiService, FiSnapshot, fetch_snapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import TRACK, activity_context, dial_offset

EMAIL, PASSWORD = "chris@example.com", "correct"


def make_client(handler=fake_fi_handler) -> FiClient:
    return FiClient(transport=httpx.MockTransport(handler))


def service(handler=fake_fi_handler, refresh_seconds=300.0) -> FiService:
    return FiService(EMAIL, PASSWORD, refresh_seconds, client_factory=lambda: make_client(handler))


# --------------------------------------------------------------------------
# parsers
# --------------------------------------------------------------------------


def test_parsers_read_the_shapes_the_probe_already_proved():
    pets = pets_from(fixture("pets")["data"])
    assert [(p.id, p.name) for p in pets] == [("pet-1", "Kona")]

    windows = rest_from(fixture("rest")["data"])
    assert len(windows) == 1
    assert windows[0].sleep == 30600 and windows[0].nap == 5400
    assert windows[0].start.year == 2026

    stats = activity_from(fixture("activity")["data"])
    assert (stats.steps, stats.step_goal, stats.distance) == (4210, 9000, 3120.5)


def test_missing_fields_are_none_not_zero():
    assert rest_from({"pet": {"dailyStat": {"restSummaries": [{"data": None}]}}})[0].sleep is None
    stats = activity_from({"pet": {"dailyStat": {"totalSteps": 0}}})
    assert stats.steps == 0 and stats.step_goal is None  # a real zero survives
    assert pets_from(None) == [] and rest_from(None) == []


def test_a_true_value_is_not_a_step_count():
    # `type(x) in (int, float)` rather than isinstance, because bool is an int.
    assert activity_from({"pet": {"dailyStat": {"totalSteps": True}}}).steps is None


@pytest.mark.parametrize(
    "seconds,expected",
    [(30600, 8.5), (0, 0.0), (86400, 24.0), (None, None), ("8h", None)],
)
def test_hours_from_plausible_durations(seconds, expected):
    assert hours_from_duration(seconds) == expected


def test_an_impossible_duration_returns_none_rather_than_a_confident_number():
    # 30600 *minutes* would be three weeks asleep. If Fi ever changes units
    # the page must show the raw figure, not "510 h".
    assert hours_from_duration(30600 * 60) is None
    assert hours_from_duration(-1) is None


# --------------------------------------------------------------------------
# fetch + cache
# --------------------------------------------------------------------------


def test_fetch_snapshot_reads_last_night():
    with make_client() as client:
        snap = fetch_snapshot(client, EMAIL, PASSWORD)
    assert snap.pet_name == "Kona"
    assert snap.sleep_hours == 8.5 and snap.nap_hours == 1.5
    assert snap.activity.steps == 4210
    assert snap.problem is None and snap.has_data and not snap.unit_suspect


def test_bad_password_is_a_problem_not_a_crash():
    svc = FiService(EMAIL, "wrong", client_factory=make_client)
    snap = svc.snapshot()
    assert not snap.has_data
    assert "login failed" in snap.problem.lower()
    assert "wrong" not in snap.problem  # never echo the credential


def test_rest_failure_still_leaves_the_steps():
    def handler(request):
        if request.url.path == "/graphql" and "KonaRest" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"errors": [{"message": "boom"}]})
        return fake_fi_handler(request)

    snap = service(handler).snapshot()
    assert snap.window is None and snap.sleep_hours is None
    assert snap.activity.steps == 4210
    # This is what Chris hit on first contact with the real API: steps fine,
    # sleep query rejected. It is a fresh reading missing a piece, NOT an old
    # reading, and the message has to send him somewhere useful.
    assert snap.partial and not snap.stale
    assert snap.problem.startswith("Sleep:")
    assert "kona probe" in snap.problem


def test_partial_and_stale_are_not_described_the_same_way():
    """The bug the real collar exposed.

    Steps arriving while sleep fails is a *current* reading with a hole in
    it. Calling that "the last good reading" tells Chris the numbers are old
    when they are not, and the two states need different words on the page.
    """

    def rest_fails(request):
        if request.url.path == "/graphql" and "KonaRest" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"errors": [{"message": "boom"}]})
        return fake_fi_handler(request)

    with web_client(service(rest_fails)) as c:
        body = c.get("/activity").text
        assert "4,210" in body, "the half that worked still shows"
        assert "last good reading" not in body
        assert "not from this moment" not in body
        assert "didn&#39;t come through" in body or "didn't come through" in body
        assert c.get("/activity.json").json()["stale"] is False


def test_a_failed_refresh_keeps_the_last_good_reading():
    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/auth/login":
            calls["n"] += 1
            if calls["n"] > 1:
                raise httpx.ConnectError("network gone", request=request)
        return fake_fi_handler(request)

    svc = service(handler, refresh_seconds=1.0)
    good = svc.snapshot()
    assert good.sleep_hours == 8.5

    svc._attempted_at = datetime.now(UTC) - timedelta(hours=1)  # force staleness
    svc._refresh()  # synchronous, so the assertion is not a race
    stale = svc.snapshot()
    assert stale.sleep_hours == 8.5, "data must survive a failed refresh"
    assert stale.problem and "connection failed" in stale.problem
    assert stale.fetched_at == good.fetched_at, "'as of' must mean when the data was true"
    assert stale.stale and not stale.partial, "this one really is old data"


def test_cached_snapshot_is_reused_rather_than_logging_in_per_request():
    logins = {"n": 0}

    def handler(request):
        if request.url.path == "/auth/login":
            logins["n"] += 1
        return fake_fi_handler(request)

    svc = service(handler, refresh_seconds=3600.0)
    for _ in range(5):
        svc.snapshot()
    assert logins["n"] == 1


def test_an_account_with_no_pets_says_so():
    def handler(request):
        if request.url.path == "/graphql" and "KonaPets" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"data": {"currentUser": {"userHouseholds": []}}})
        return fake_fi_handler(request)

    snap = service(handler).snapshot()
    assert not snap.has_data and "no pets" in snap.problem


def test_an_unexpected_exception_becomes_a_problem_not_a_500():
    def explode():
        raise ValueError("something we did not anticipate")

    svc = FiService(EMAIL, PASSWORD, client_factory=explode)
    snap = svc.snapshot()
    assert not snap.has_data and "Unexpected error" in snap.problem


# --------------------------------------------------------------------------
# view formatting
# --------------------------------------------------------------------------


def test_dial_offset_maps_hours_onto_the_track_in_the_stylesheet():
    assert dial_offset(None) == TRACK  # empty ring, never a guess
    assert dial_offset(0) == TRACK
    assert dial_offset(12) == 0.0  # full ring at the 12 h scale
    assert dial_offset(6) == pytest.approx(TRACK / 2, abs=0.1)
    assert dial_offset(48) == 0.0, "clamped, so a long sleep cannot wrap to look short"


def test_context_shows_raw_seconds_when_the_unit_is_not_credible():
    with make_client() as client:
        snap = fetch_snapshot(client, EMAIL, PASSWORD)
    broken = FiSnapshot(
        fetched_at=snap.fetched_at,
        pet_name=snap.pet_name,
        window=RestWindow(start=snap.window.start, end=snap.window.end, sleep=30600 * 60, nap=None),
        activity=snap.activity,
    )
    ctx = activity_context(broken, configured=True)
    assert ctx["sleep_hours"] is None
    assert ctx["sleep_raw"] == 30600 * 60 and ctx["unit_suspect"]
    assert ctx["dial_offset"] == TRACK  # nothing drawn we cannot justify


def test_context_of_nothing_at_all_is_all_dashes():
    ctx = activity_context(None, configured=False)
    assert ctx["sleep_hours"] is None and ctx["steps"] is None and ctx["as_of"] is None
    assert ctx["has_data"] is False and ctx["dial_offset"] == TRACK


# --------------------------------------------------------------------------
# the page
# --------------------------------------------------------------------------


def web_client(fi_service=None, **kw) -> TestClient:
    settings = Settings(passcode="4242", secret="test-secret", **kw)
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100), fi_service=fi_service)
    client = TestClient(app)
    client.post("/login", data={"passcode": "4242"})
    return client


def test_activity_page_renders_real_numbers():
    with web_client(service()) as c:
        body = c.get("/activity").text
        assert "8.5" in body and "4,210" in body and "1.5" in body
        assert "9,000" in body  # step goal
        assert PASSWORD not in body and EMAIL not in body

        data = c.get("/activity.json").json()
        assert data["sleep_seconds"] == 30600 and data["sleep_hours"] == 8.5
        assert data["steps"] == 4210 and data["problem"] is None
        assert "password" not in json.dumps(data).lower()


def test_activity_page_without_credentials_explains_the_two_env_lines():
    with web_client(None) as c:
        body = c.get("/activity").text
        assert "FI_EMAIL" in body and "FI_PASSWORD" in body
        assert "waiting for the collar" in body
        data = c.get("/activity.json").json()
        assert data["configured"] is False and data["stale"] is False
        assert all(
            value is None for key, value in data.items() if key not in ("configured", "stale")
        )


def test_activity_page_says_what_went_wrong_without_leaking_the_password():
    bad = FiService(EMAIL, "s3cret-passphrase", client_factory=make_client)
    with web_client(bad) as c:
        body = c.get("/activity").text
        assert "reach Fi" in body and "login failed" in body.lower()
        assert "s3cret-passphrase" not in body
        assert "s3cret-passphrase" not in json.dumps(c.get("/activity.json").json())


def test_settings_never_print_the_fi_password():
    s = Settings(passcode="4242", secret="s", fi_email="a@b.c", fi_password="hunter2")
    assert "hunter2" not in repr(s) and s.fi_configured
    assert not Settings(passcode="4242", secret="s", fi_email="a@b.c").fi_configured


def test_a_failure_is_never_dressed_up_as_an_empty_night():
    """ "As of 18:48" over a blank dial reads as "she slept nothing"."""
    bad = FiService(EMAIL, "s3cret-passphrase", client_factory=make_client)
    ctx = activity_context(bad.snapshot(), configured=True)
    assert ctx["as_of"] is None, "no timestamp without data to date"
    with web_client(bad) as c:
        body = c.get("/activity").text
        assert "as of" not in body
        assert "no rest data yet" not in body
        assert "couldn&#39;t reach the collar" in body or "couldn't reach the collar" in body
