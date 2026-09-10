"""The Fi snapshot path, end to end, against a mocked API.

The theme is that nothing here may invent a number. A missing field, an
unrecognised unit, a login that fails and a refresh that fails on top of good
data are each a distinct visible state, and each is pinned below.
"""

import json
from datetime import UTC, date, datetime, timedelta

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
from kona_tracker.web.views import TRACK, activity_context, activity_json, dial_offset

EMAIL, PASSWORD = "chris@example.com", "correct"

# Mid-afternoon on the fixture's "today": inside the in-progress window and
# after last night's window closed. Pinned so the fixtures never age.
NOW = datetime(2026, 9, 10, 15, 0, tzinfo=UTC)


def make_client(handler=fake_fi_handler) -> FiClient:
    return FiClient(transport=httpx.MockTransport(handler))


def service(handler=fake_fi_handler, refresh_seconds=300.0, clock=lambda: NOW) -> FiService:
    return FiService(
        EMAIL, PASSWORD, refresh_seconds, client_factory=lambda: make_client(handler), clock=clock
    )


# --------------------------------------------------------------------------
# parsers
# --------------------------------------------------------------------------


def test_parsers_read_the_shapes_the_probe_already_proved():
    pets = pets_from(fixture("pets")["data"])
    assert [(p.id, p.name) for p in pets] == [("pet-1", "Kona")]

    windows = rest_from(fixture("rest")["data"])
    assert len(windows) == 2, "today in progress, plus last night"
    assert windows[1].sleep == 30600 and windows[1].nap == 5400
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


def test_fetch_snapshot_reads_last_night_not_today():
    """The bug the real collar exposed.

    Fi's newest daily window is today, in progress, SLEEP=0. A "Last night"
    dial that read it would show 0 h. The hero is the last *completed* day;
    naps come from today.
    """
    with make_client() as client:
        snap = fetch_snapshot(client, EMAIL, PASSWORD, now=NOW)
    assert snap.pet_name == "Kona"
    assert snap.sleep_hours == 8.5, "last night, not today's 0"
    assert snap.window.end < NOW <= snap.today.end
    assert snap.nap_hours == pytest.approx(1290 / 3600), "naps so far today"
    assert snap.activity.steps == 4210 and snap.week.steps == 31000
    assert snap.problem is None and snap.has_data and not snap.unit_suspect


def test_new_collar_cutoff_hides_old_night_and_week_without_hiding_today():
    with make_client() as client:
        snap = fetch_snapshot(client, EMAIL, PASSWORD, now=NOW, data_start=date(2026, 9, 10))
    assert snap.window is None and snap.today is not None
    assert snap.activity.steps == 4210, "today belongs to the new setup"
    assert snap.week is None and snap.historical_totals_hidden
    ctx = activity_context(snap, configured=True)
    assert ctx["night_pending"] and ctx["data_start_label"] == "today"


def test_a_collar_paired_today_has_no_night_yet():
    """Only an in-progress window: say the night is still to come, not 0 h."""
    from kona_tracker.fi.parse import split_windows

    windows = rest_from(fixture("rest")["data"])
    last, today = split_windows(windows[:1], NOW)  # drop yesterday
    assert last is None and today is not None
    ctx = activity_context(FiSnapshot(fetched_at=NOW, today=today, activity=None), configured=True)
    assert ctx["night_pending"] and ctx["sleep_hours"] is None
    assert ctx["nap_hours"] == "0.4"


def test_split_windows_handles_naive_and_missing_timestamps():
    from kona_tracker.fi.parse import RestWindow, split_windows

    naive = rest_from(
        {
            "pet": {
                "dailyStat": {
                    "restSummaries": [
                        {
                            "start": "2026-09-09T04:00:00",
                            "end": "2026-09-10T04:00:00",
                            "data": {"sleepAmounts": [{"type": "SLEEP", "duration": 100}]},
                        }
                    ]
                }
            }
        }
    )
    last, today = split_windows(naive, NOW)
    assert last is not None and last.sleep == 100, "a bare stamp is read as UTC, not a crash"
    assert split_windows([RestWindow(None, None, 1, 1)], NOW) == (None, None)


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
        snap = fetch_snapshot(client, EMAIL, PASSWORD, now=NOW)
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
        assert "8.5" in body and "4,210" in body and "9,000" in body
        assert "0.4" in body and "so far today" in body  # today's naps, not last night's
        assert "31,000" in body and "This week" in body  # replaced the distance tile
        assert "raw units" not in body
        assert PASSWORD not in body and EMAIL not in body

        data = c.get("/activity.json").json()
        assert data["sleep_seconds"] == 30600 and data["sleep_hours"] == 8.5
        assert data["today_nap_seconds"] == 1290 and data["week_steps"] == 31000
        assert data["distance_m"] == 3120.5, "metres, in the JSON; the tile is the design's call"
        assert data["steps"] == 4210 and data["problem"] is None
        assert "password" not in json.dumps(data).lower()

        assert body.index("Steps today") < body.index("Naps today")
        assert body.index("Naps today") < body.index("Location") < body.index("This week")
        assert "Fi identifies this resting place as Home" in body


def test_activity_page_without_credentials_explains_the_two_env_lines():
    with web_client(None) as c:
        body = c.get("/activity").text
        assert "FI_EMAIL" in body and "FI_PASSWORD" in body
        assert "waiting for the collar" in body
        data = c.get("/activity.json").json()
        assert data["configured"] is False and data["stale"] is False
        assert data["has_photo"] is False
        assert all(
            value is None
            for key, value in data.items()
            if key not in ("configured", "stale", "has_photo")
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


# --------------------------------------------------------------------------
# profile + collar status (slice 4b backend)
# --------------------------------------------------------------------------


def test_profile_and_status_parse_the_measured_shapes():
    from datetime import date

    from kona_tracker.fi.parse import profile_from, status_from

    data = fixture("status")["data"]
    profile = profile_from(data)
    assert profile.name == "Kona" and profile.breed == "Labrador Retriever"
    assert profile.birthday == date(2025, 8, 15)
    assert profile.photo_url == "https://cdn.example.invalid/kona.jpg"

    status = status_from(data)
    assert status.battery_percent == 57, "lives in device.info, not on Device"
    assert status.time_to_empty_s == 368634
    assert status.on_base is True and status.signal_percent is None
    assert status.activity == "rest" and status.walk_distance is None
    assert status.area_name is None and status.place_name == "Home"
    assert status.led_on is False and status.led_color == "White" and status.mode == "NORMAL"
    assert status.next_update is not None and status.last_report is not None


def test_escape_and_walk_are_independent_flags():
    """Measured 2026-09-10: mode went POST_ESCAPE_NOTIFICATION when she left
    without an owner's phone, and stayed there while Fi also detected a
    walk. Both must be readable at once."""
    from kona_tracker.fi.parse import status_from

    data = json.loads(json.dumps(fixture("status")["data"]))
    data["pet"]["device"]["operationParams"]["mode"] = "POST_ESCAPE_NOTIFICATION"
    data["pet"]["ongoingActivity"] = {"__typename": "OngoingWalk", "distance": 285.8}
    st = status_from(data)
    assert st.escaped and not st.lost and st.activity == "walk"
    assert st.walk_distance == 285.8

    data["pet"]["device"]["operationParams"]["mode"] = "LOST_DOG"
    assert status_from(data).lost and not status_from(data).escaped
    assert not status_from(fixture("status")["data"]).escaped


def test_json_carries_metres_and_flags_but_no_days_left_on_the_page():
    with web_client(service()) as c:
        data = c.get("/activity.json").json()
        page = c.get("/activity").text
    assert data["distance_m"] == 3120.5 and data["week_distance_m"] == 22000.0
    assert data["escaped"] is False and data["lost"] is False
    assert data["time_to_empty_s"] == 368634, "kept in the JSON"
    assert "4.3" not in page and "days" not in page, "never a headline: it swung 4 d -> 12 h"


def test_status_when_she_is_out_on_a_walk():
    from kona_tracker.fi.parse import status_from

    data = json.loads(json.dumps(fixture("status")["data"]))
    data["pet"]["device"]["lastConnectionState"] = {
        "__typename": "ConnectedToCellular",
        "date": "2026-09-10T21:00:00Z",
        "signalStrengthPercent": 72,
    }
    data["pet"]["ongoingActivity"] = {
        "__typename": "OngoingWalk",
        "start": "2026-09-10T20:50:00Z",
        "lastReportTimestamp": "2026-09-10T21:00:00Z",
        "areaName": None,
        "distance": 420,
    }
    status = status_from(data)
    assert status.on_base is False and status.signal_percent == 72
    assert status.activity == "walk" and status.walk_distance == 420


def test_walk_positions_are_validated_sorted_and_exposed_behind_auth():
    from kona_tracker.fi.parse import status_from

    data = json.loads(json.dumps(fixture("status")["data"]))
    walk = fixture("location")["data"]["pet"]["ongoingActivity"]
    walk["positions"].extend(
        [
            {"date": "2026-09-10T19:20:00Z", "errorRadius": -2,
             "position": {"latitude": 30.26, "longitude": -97.74}},
            {"date": "2026-09-10T19:30:00Z", "errorRadius": 4,
             "position": {"latitude": 999, "longitude": -97.74}},
        ]
    )
    data["pet"]["ongoingActivity"] = walk
    status = status_from(data)
    assert [(p.latitude, p.longitude) for p in status.positions] == [
        (30.26, -97.74),
        (30.2672, -97.7431),
    ]
    assert status.positions[0].accuracy_m is None

    def walking(request):
        if request.url.path == "/graphql" and "KonaStatus" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"data": data})
        return fake_fi_handler(request)

    with web_client(service(walking)) as c:
        page = c.get("/activity").text
        api = c.get("/activity.json").json()
        assert 'id="kona-map"' in page and "tile.openstreetmap.org" in page
        assert "Current walk" in page and "Updated" in page
        assert "30.2672" in page and len(api["positions"]) == 2


def test_last_gps_fix_survives_when_fi_returns_to_rest():
    status_calls = 0

    def handler(request):
        nonlocal status_calls
        if request.url.path == "/graphql" and "KonaStatus" in json.loads(request.content)["query"]:
            status_calls += 1
            data = json.loads(json.dumps(fixture("status")["data"]))
            if status_calls == 1:
                data["pet"]["ongoingActivity"] = fixture("location")["data"]["pet"][
                    "ongoingActivity"
                ]
            return httpx.Response(200, json={"data": data})
        return fake_fi_handler(request)

    svc = service(handler)
    first = svc.snapshot()
    assert first.status.positions
    svc._refresh()
    second = svc.snapshot()
    assert second.status.activity == "rest" and second.status.positions == first.status.positions
    assert activity_context(second, configured=True)["location_live"] is False


def test_absent_status_fields_are_none_and_bad_photo_urls_are_dropped():
    from kona_tracker.fi.parse import profile_from, status_from

    empty = status_from({"pet": {}})
    assert empty.battery_percent is None and empty.on_base is None and empty.activity is None
    assert (
        profile_from({"pet": {"yearOfBirth": 2025, "monthOfBirth": 2, "dayOfBirth": 30}}).birthday
        is None
    )
    http_only = {"pet": {"photos": {"first": {"image": {"fullSize": "http://x/kona.jpg"}}}}}
    assert profile_from(http_only).photo_url is None, "only https reaches the proxy"


@pytest.mark.parametrize(
    "birthday,expected",
    [
        ((2025, 8, 15), "1 year"),  # Kona on 2026-09-10: 12 months and 26 days
        ((2025, 7, 1), "1 year 2 months"),
        ((2026, 3, 1), "6 months"),
        ((2025, 9, 10), "1 year"),
        ((2023, 1, 1), "3 years"),
        (None, None),
    ],
)
def test_age_label(birthday, expected):
    from datetime import date

    from kona_tracker.web.views import age_label

    assert age_label(date(*birthday) if birthday else None, NOW) == expected


def test_snapshot_carries_profile_and_status_and_a_collar_failure_is_partial():
    with make_client() as client:
        snap = fetch_snapshot(client, EMAIL, PASSWORD, now=NOW)
    assert snap.profile.breed == "Labrador Retriever" and snap.status.battery_percent == 57

    def status_fails(request):
        if request.url.path == "/graphql" and "KonaStatus" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"errors": [{"message": "boom"}]})
        return fake_fi_handler(request)

    snap = service(status_fails).snapshot()
    assert snap.sleep_hours == 8.5 and snap.status is None and snap.profile is None
    assert snap.partial and snap.problem.startswith("Collar:")


def test_activity_json_exposes_the_collar_without_the_photo_url():
    with web_client(service()) as c:
        data = c.get("/activity.json").json()
    assert data["battery_percent"] == 57 and data["on_base"] is True
    assert data["activity"] == "rest" and data["breed"] == "Labrador Retriever"
    assert data["birthday"] == "2025-08-15" and data["has_photo"] is True
    assert "cdn.example.invalid" not in json.dumps(data), "the URL stays server-side"


def test_a_saved_home_address_is_never_exposed_to_the_page_or_json():
    from kona_tracker.fi.parse import CollarStatus

    private = "86 Norfolk"
    snap = FiSnapshot(
        fetched_at=NOW,
        pet_name="Kona",
        status=CollarStatus(activity="rest", place_name=private),
    )
    assert activity_context(snap, configured=True)["area_name"] == "Home"
    payload = activity_json(snap, configured=True)
    assert payload["area_name"] == "Home" and private not in json.dumps(payload)


# --------------------------------------------------------------------------
# /avatar.jpg
# --------------------------------------------------------------------------


def avatar_client(fetch, fi=None) -> TestClient:
    settings = Settings(passcode="4242", secret="test-secret")
    app = create_app(
        settings,
        source_factory=lambda: FakeSource(fps=100),
        fi_service=fi if fi is not None else service(),
        avatar_fetch=fetch,
    )
    client = TestClient(app)
    client.post("/login", data={"passcode": "4242"})
    return client


def test_avatar_is_proxied_once_and_gated_like_the_stream():
    calls: list[str] = []

    def fetch(url):
        calls.append(url)
        return b"\xff\xd8jpegbytes", "image/jpeg"

    with avatar_client(fetch) as c:
        first = c.get("/avatar.jpg")
        assert first.status_code == 200 and first.content == b"\xff\xd8jpegbytes"
        assert first.headers["content-type"].startswith("image/jpeg")
        assert "max-age" in first.headers["cache-control"]
        c.get("/avatar.jpg")
        assert calls == ["https://cdn.example.invalid/kona.jpg"], "fetched once, then cached"

        c.cookies.clear()
        assert c.get("/avatar.jpg", follow_redirects=False).status_code == 401, (
            "an <img> cannot follow a redirect to the login page"
        )


def test_avatar_404s_when_there_is_no_photo_or_the_link_is_dead():
    with avatar_client(lambda url: None) as c:
        assert c.get("/avatar.jpg").status_code == 404, "a dead link is not a broken icon"

    with avatar_client(lambda url: (b"x", "image/png"), fi=None) as c:
        pass  # default service has a photo; covered above

    unconfigured = create_app(
        Settings(passcode="4242", secret="s"),
        source_factory=lambda: FakeSource(fps=100),
        fi_service=None,
        avatar_fetch=lambda url: (b"x", "image/png"),
    )
    with TestClient(unconfigured) as c:
        c.post("/login", data={"passcode": "4242"})
        assert c.get("/avatar.jpg").status_code == 404
    unconfigured.state.hub.stop()


def test_default_avatar_fetch_refuses_non_raster_plain_http_and_downgrade_redirects(
    monkeypatch,
):
    """Review finding: httpx follows a redirect from https to http without
    complaint, so the scheme has to be checked on the final hop. And SVG is
    an image type that can carry script, served from our own origin."""
    import httpx as _httpx

    from kona_tracker.web.app import fetch_avatar

    assert fetch_avatar("http://cdn/kona.jpg") is None

    def fake_get(url, **kw):
        final = url
        ctype, body = "image/jpeg", b"jpg"
        if "html" in url:
            ctype, body = "text/html", b"<h1>"
        elif "svg" in url:
            ctype, body = "image/svg+xml", b"<svg onload=alert(1)/>"
        elif "downgrade" in url:
            final = "http://10.0.0.1/kona.jpg"  # https -> http redirect, followed
        resp = _httpx.Response(200, headers={"content-type": ctype}, content=body)
        resp.request = _httpx.Request("GET", final)
        return resp

    monkeypatch.setattr(_httpx, "get", fake_get)
    assert fetch_avatar("https://cdn/page.html") is None
    assert fetch_avatar("https://cdn/kona.svg") is None
    assert fetch_avatar("https://cdn/downgrade.jpg") is None, "final hop must still be https"
    assert fetch_avatar("https://cdn/kona.jpg") == (b"jpg", "image/jpeg")


def test_a_shape_change_in_the_collar_blob_is_a_partial_not_a_blank_page():
    """Review finding: `device.info` is an arbitrary blob, and a non-dict
    where a dict was expected used to raise AttributeError out of the whole
    fetch, discarding the sleep and steps that had already arrived."""
    from kona_tracker.fi.parse import profile_from, status_from

    hostile = {
        "pet": {
            "device": "gone",
            "photos": 7,
            "breed": ["Lab"],
            "ongoingActivity": None,
        }
    }
    assert status_from(hostile).battery_percent is None
    assert profile_from(hostile).photo_url is None and profile_from(hostile).breed is None
    nested = {
        "pet": {
            "device": {
                "info": {"max77658Info": "x"},
                "lastConnectionState": 3,
                "operationParams": [],
                "ledColor": "White",
            }
        }
    }
    st = status_from(nested)
    assert st.time_to_empty_s is None and st.on_base is None and st.led_color is None

    def blob_goes_weird(request):
        if request.url.path == "/graphql" and "KonaStatus" in json.loads(request.content)["query"]:
            return httpx.Response(200, json={"data": {"pet": {"device": "nope"}}})
        return fake_fi_handler(request)

    snap = service(blob_goes_weird).snapshot()
    assert snap.sleep_hours == 8.5, "sleep survived the collar blob changing shape"
    assert snap.status is not None and snap.status.battery_percent is None
    assert snap.problem is None
