"""The Activity page and its JSON twin: the whole snapshot turned into the
exact strings and numbers the template prints.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    LocationPoint,
    Overnight,
    PetProfile,
    RestWindow,
)
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views.format import (
    DIAL_SCALE_HOURS,
    _age_seconds,
    _clock,
    _count,
    _day,
    _hhmm,
    _location_label,
    _since,
    _span,
    age_label,
    dial_offset,
    distance_label,
    duration_parts,
    kona_zone,
    step_ring,
)
from kona_tracker.web.views.history import hourly_json
from kona_tracker.web.views.walks import walk_rows, walks_json


def overnight_labels(night: Overnight | None, zone: tzinfo | None) -> dict[str, Any] | None:
    """`00:20 – 08:04` and how often she woke, or None when Fi has no night."""
    if night is None or night.sleep_start is None or night.sleep_end is None:
        return None
    count = len(night.interruptions)
    if count == 0:
        wake = "slept through"
    elif count == 1:
        wake = "woke once"
    elif count == 2:
        wake = "woke twice"
    else:
        wake = f"woke {count} times"
    return {
        "span": _span(night.sleep_start, night.sleep_end, zone),
        "wake_count": count,
        "wake_label": wake,
        "interruptions": [_span(a, b, zone) for a, b in night.interruptions],
    }


#: How far behind the collar's last report a connection reading may be and
#: still describe the present. The collar reports every ~3 minutes at rest
#: (`nextLocationUpdateExpectedBy`, measured 2026-09-13), and when it is on
#: the base the two timestamps are identical, so a minute is generous.
CONNECTION_CURRENT_SECONDS = 60


def connection_label(status: CollarStatus | None, zone: tzinfo | None) -> dict[str, Any] | None:
    """Where the collar is connected -- and whether that is news or memory.

    Fi's field is `lastConnectionState`. On 2026-09-13 it still said
    ConnectedToBase, from hours earlier, while Kona was 878 m from the house
    on a walk, and the page printed "On charger" beside a moving map. Fi was
    not wrong; we were reading a *last known* state as a current one.

    So the reading is only allowed to speak in the present tense when its own
    timestamp keeps up with the collar's last report. Otherwise it says what
    it actually is: the last connection Fi recorded, and when.
    """
    if status is None or status.on_base is None:
        return None
    place = "the base" if status.on_base else "cellular"
    current = True
    if status.connection_at is not None and status.last_report is not None:
        behind = (status.last_report - status.connection_at).total_seconds()
        current = behind <= CONNECTION_CURRENT_SECONDS
    if current:
        if status.on_base:
            # NOT "On charger". `ConnectedToBase` means the collar is talking
            # to the base over its short-range radio, which it does from
            # anywhere in range -- a dog asleep on the sofa nearby is
            # connected to the base and charging nothing. Chris saw "On
            # charger" on 2026-09-15 with the collar on Kona and the base
            # empty, which is how this was found.
            #
            # There is no field to fix it with, either: `charging` on `Device`
            # is recorded as confirmed absent in docs/device-capabilities.md
            # -- the probe asked and Fi does not have it. So the app cannot
            # know whether the collar is charging and must not imply it.
            text = "Connected to base"
        elif status.signal_percent is not None:
            text = f"Cellular {_count(status.signal_percent)}%"
        else:
            text = "Cellular"
        return {"text": text, "current": True}
    when = _hhmm(_clock(status.connection_at, zone)) if status.connection_at else None
    return {
        "text": f"Last connected to {place}{f' · {when}' if when else ''}",
        "current": False,
    }


def last_night(snapshot: FiSnapshot | None, zone: tzinfo | None) -> dict[str, Any] | None:
    """ "Asleep last night" -- one night's sleep, with the span that matches it.

    Two numbers were being shown as one. The hero used Fi's SLEEP total for
    the whole calendar day (35513 s on 2026-09-12, "9h 52m"), while the
    caption under it used `overnightRestSummary`'s actual bout (27832 s,
    00:20-08:04, "7h 44m"). A figure and its own caption disagreeing by two
    hours is exactly the confident-wrong output this project refuses, and
    Chris chose the overnight bout on 2026-09-13: it is what a person means
    by "last night", and it is the one the span describes.

    The day total is not lost -- it is what `/rest` charts, per day, where
    the label says so. When Fi sends no overnight summary the day total
    stands in, and `source` says which is on screen so the caption can too.
    """
    if snapshot is None:
        return None
    night = snapshot.overnight
    window = snapshot.window
    if night is not None and night.sleep_seconds is not None and night.sleep_start is not None:
        return {
            "parts": duration_parts(night.sleep_seconds),
            "raw": night.sleep_seconds,
            "source": "overnight",
            "labels": overnight_labels(night, zone),
        }
    if window is None:
        return None
    return {
        "parts": duration_parts(window.sleep),
        "raw": window.sleep,
        "source": "day",
        "labels": None,
    }


def activity_context(snapshot: FiSnapshot | None, configured: bool) -> dict[str, Any]:
    """Everything `activity.html` needs, with no data invented on the way."""
    window = snapshot.window if snapshot else None
    today = snapshot.today if snapshot else None
    activity = snapshot.activity if snapshot else None
    week = snapshot.week if snapshot else None
    profile = snapshot.profile if snapshot else None
    status = snapshot.status if snapshot else None
    sleep_hours = snapshot.sleep_hours if snapshot else None
    zone = kona_zone(profile.timezone if profile else None)
    fetched_local = _clock(snapshot.fetched_at, zone) if snapshot else None
    night = last_night(snapshot, zone)
    positions = status.positions if status else ()
    rest_position = status.rest_position if status else None
    home_position = status.home_location if status else None
    stale = bool(snapshot and snapshot.stale)
    walking = bool(
        positions and status and status.activity == "walk" and not status.positions_carried
    )
    # What the map may claim, most current first. Only `current` and `rest`
    # speak about now, so both need a fresh snapshot; a fix Fi sent before it
    # stopped answering is still real, but it is "last seen", not "resting".
    if walking and not stale:
        map_kind, map_positions = "current", positions
    elif rest_position and not stale:
        map_kind, map_positions = "rest", (rest_position,)
    elif rest_position:
        map_kind, map_positions = "last", (rest_position,)
    elif positions:
        map_kind, map_positions = "last", positions
    elif home_position:
        map_kind, map_positions = "home", (home_position,)
    else:
        map_kind, map_positions = None, ()
    # The home pin is a saved place, not a fix: it carries no time.
    last_position = map_positions[-1] if map_positions and map_kind != "home" else None
    location_label = _location_label(status)

    return {
        # Who she is and what the collar says, for the template to use when
        # the design lands. Nothing here is rendered yet.
        "has_photo": bool(profile and profile.photo_url),
        "breed": profile.breed if profile else None,
        "age": age_label(profile.birthday, fetched_local) if profile and fetched_local else None,
        "battery": _count(status.battery_percent) if status else None,
        # No "days left" here on purpose. `timeToEmptyS` read 4.3 days on
        # the charger and 12 hours once cellular and GPS were running: it is
        # a live power estimate, not a fact about the battery. It stays in
        # the JSON; the percentage is the number for the page.
        "on_base": status.on_base if status else None,
        "signal": _count(status.signal_percent) if status else None,
        "activity": status.activity if status else None,
        # When the current rest or walk began, so "Resting" can say for how
        # long. Fi already sends it; the page used to throw it away.
        "activity_since": (_since(status.activity_since, fetched_local, zone) if status else None),
        "escaped": status.escaped if status else None,
        "lost": status.lost if status else None,
        # Metres, walk-only, verified 2026-09-10: a 285.8 m OngoingWalk
        # became totalDistance 286 for the day. A true 0 is a real "no walk".
        "distance_m": _count(activity.distance if activity else None),
        "walk_distance_m": _count(status.walk_distance) if status else None,
        # The same number in the units the rest of the app uses. The live
        # walk said "878.4 m walked" on 2026-09-13 while the walk log below
        # it said miles, which is the app disagreeing with itself on screen.
        "walk_distance": distance_label(status.walk_distance) if status else None,
        # How old the fix on the map is, in seconds. The map page counts up
        # from it; the Activity card renders it once.
        "fix_age_s": (
            _age_seconds(last_position.recorded_at, snapshot.fetched_at)
            if last_position and snapshot
            else None
        ),
        "led_on": status.led_on if status else None,
        "area_name": location_label,
        "map_points": [
            {
                "lat": point.latitude,
                "lon": point.longitude,
                "accuracy": point.accuracy_m,
            }
            for point in map_positions
        ],
        "map_kind": map_kind,
        "location_updated": (
            _hhmm(_clock(last_position.recorded_at, zone))
            if last_position and last_position.recorded_at
            else None
        ),
        "location_live": walking and not stale,
        "data_start_label": (
            "today"
            if snapshot and fetched_local and snapshot.data_start == fetched_local.date()
            else _day(snapshot.data_start)
            if snapshot and snapshot.data_start
            else None
        ),
        "historical_totals_hidden": bool(snapshot and snapshot.historical_totals_hidden),
        # The day the weekly total stops being able to include the previous
        # collar: `data_start` plus the seven days FiService withholds. A date
        # to act on, rather than a sentence about our own data hygiene.
        "week_available_label": (
            _day(snapshot.data_start + timedelta(days=7))
            if snapshot and snapshot.data_start and snapshot.historical_totals_hidden
            else None
        ),
        "tab": "activity",
        "configured": configured,
        "has_data": bool(snapshot and snapshot.has_data),
        "pet_name": (snapshot.pet_name if snapshot else "") or "Kona",
        # `8h 30m` as (figure, unit) pairs. None when there is nothing to say
        # or the figure is not credible as seconds; `sleep_raw` covers that.
        # One night, and the span that describes that same night. See
        # `last_night`: these used to come from two different calculations.
        "sleep_parts": (night["parts"] if night else None),
        "sleep_source": (night["source"] if night else None),
        "nap_parts": duration_parts(today.nap if today else None),
        # The collar was paired today: there is a day in progress but no
        # completed night yet. Say so, rather than "no data".
        "night_pending": window is None and today is not None,
        # Kept so a unit change shows the real figure instead of nothing.
        "sleep_raw": (night["raw"] if night else None),
        "nap_raw": today.nap if today else None,
        "unit_suspect": bool(snapshot and snapshot.unit_suspect),
        # Two different failures that must not share a sentence: "stale"
        # means these numbers are old, "partial" means they are current
        # but one query did not come back.
        "stale": bool(snapshot and snapshot.stale),
        "partial": bool(snapshot and snapshot.partial),
        "window_from": _day(window.start if window else None),
        "window_to": _day(window.end if window else None),
        # Last night as a time span, and the day's walks. Both are Fi's
        # own records (rounds 10-11), not inferred from anything.
        "overnight": (night["labels"] if night else None),
        "connection": connection_label(status, zone),
        "walks_today": (
            walk_rows(snapshot.walks, fetched_local, zone) if snapshot and fetched_local else []
        ),
        "steps": _count(activity.steps if activity else None),
        "step_goal": _count(activity.step_goal if activity else None),
        # Distance is deliberately not here: it came back 0 for a day with
        # 3,383 steps, so until it is understood it lives in the JSON only.
        "week_steps": _count(week.steps if week else None),
        "ring": step_ring(
            activity.steps if activity else None, activity.step_goal if activity else None
        ),
        "dial_offset": dial_offset(sleep_hours),
        "dial_scale": f"{DIAL_SCALE_HOURS:.0f}",
        # Only stamped when there is something for it to date. "As of 18:48"
        # over an empty dial reads as "we checked and she slept nothing".
        "as_of": (_hhmm(fetched_local) if fetched_local and snapshot.has_data else None),
        # Shown next to the times only when they are Kona's, so a reader in
        # another timezone knows whose 18:48 that is. Blank on the fallback:
        # the server's clock has no name worth printing.
        "clock_zone": fetched_local.strftime("%Z") if zone and fetched_local else None,
        "problem": snapshot.problem if snapshot else None,
    }


def preview_activity_context() -> dict[str, Any]:
    """A clearly labelled, local-only complete state for reviewing the UI.

    This never enters the Fi cache or the JSON endpoint. It exists so a new
    collar does not force the owner to wait a week before checking whether
    every part of the dashboard reads well.
    """
    from kona_tracker.web.history_preview import SAMPLE_DAY, history_preview

    now = datetime(SAMPLE_DAY.year, SAMPLE_DAY.month, SAMPLE_DAY.day, 11, tzinfo=UTC)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    sample_steps = history_preview("steps", "day", 0, None)
    sample_rest = history_preview("rest", "day", 0, None)
    snapshot = FiSnapshot(
        fetched_at=now,
        pet_name="Kona",
        window=RestWindow(start, start + timedelta(days=1), sample_rest["sleep_total"] * 60, 0),
        today=RestWindow(
            start + timedelta(days=1),
            start + timedelta(days=2),
            0,
            1 * 3600 + 24 * 60,
        ),
        activity=ActivityStats(sample_steps["total"], 28_000, 2100),
        week=ActivityStats(history_preview("steps", "week", 0, None)["total"], None, None),
        profile=PetProfile(
            name="Kona", breed="Labrador Retriever", birthday=date(2025, 8, 15), timezone="UTC"
        ),
        status=CollarStatus(
            battery_percent=57,
            on_base=False,
            signal_percent=78,
            activity="walk",
            activity_since=now - timedelta(minutes=14),
            walk_distance=420,
            area_name="Sample walk",
            positions=(
                LocationPoint(30.2672, -97.7431, now - timedelta(minutes=4), 12),
                LocationPoint(30.2680, -97.7418, now - timedelta(minutes=2), 9),
                LocationPoint(30.2690, -97.7405, now, 8),
            ),
        ),
    )
    context = activity_context(snapshot, configured=True)
    context["preview"] = True
    context["sample_steps_chart"] = sample_steps
    context["sample_rest_chart"] = sample_rest
    return context


def activity_json(snapshot: FiSnapshot | None, configured: bool) -> dict[str, Any]:
    """The same data as the page, for polling later. Never the credentials."""
    window = snapshot.window if snapshot else None
    today = snapshot.today if snapshot else None
    activity = snapshot.activity if snapshot else None
    week = snapshot.week if snapshot else None
    profile = snapshot.profile if snapshot else None
    status = snapshot.status if snapshot else None
    home_position = status.home_location if status else None
    rest_position = status.rest_position if status else None
    return {
        "configured": configured,
        # One entry per day the collar has existed, oldest first, seconds as
        # Fi sends them. `complete` is the only flag needed to decide
        # inclusion in an average; the other two say why a day is not.
        "rest_history": [
            {
                "date": d.window.start.date().isoformat(),  # type: ignore[union-attr]
                "start": d.window.start.isoformat(),  # type: ignore[union-attr]
                "end": d.window.end.isoformat(),  # type: ignore[union-attr]
                "sleep_s": d.window.sleep,
                "nap_s": d.window.nap,
                "total_s": d.total,
                "complete": d.complete,
                "in_progress": d.in_progress,
                "partial_first_day": d.partial_first_day,
            }
            for d in snapshot.rest_days
        ]
        if snapshot
        else None,
        "walks": walks_json(snapshot),
        "overnight": overnight_json(snapshot),
        "hourly": hourly_json(snapshot),
        "breed": profile.breed if profile else None,
        "birthday": profile.birthday.isoformat() if profile and profile.birthday else None,
        # The photo URL itself stays server-side; the page uses /avatar.jpg.
        "has_photo": bool(profile and profile.photo_url),
        "battery_percent": status.battery_percent if status else None,
        "time_to_empty_s": status.time_to_empty_s if status else None,
        "on_base": status.on_base if status else None,
        "signal_percent": status.signal_percent if status else None,
        "activity": status.activity if status else None,
        "activity_since": (
            status.activity_since.isoformat() if status and status.activity_since else None
        ),
        "escaped": status.escaped if status else None,
        "lost": status.lost if status else None,
        "walk_distance_m": status.walk_distance if status else None,
        "led_on": status.led_on if status else None,
        "led_color": status.led_color if status else None,
        "mode": status.mode if status else None,
        "area_name": _location_label(status),
        "positions": (
            [
                {
                    "latitude": point.latitude,
                    "longitude": point.longitude,
                    "recorded_at": point.recorded_at.isoformat() if point.recorded_at else None,
                    "accuracy_m": point.accuracy_m,
                }
                for point in status.positions
            ]
            if status
            else None
        ),
        "home_position": (
            {"latitude": home_position.latitude, "longitude": home_position.longitude}
            if home_position
            else None
        ),
        "positions_carried": status.positions_carried if status else None,
        "rest_position": (
            {
                "latitude": rest_position.latitude,
                "longitude": rest_position.longitude,
                "reported_at": (
                    rest_position.recorded_at.isoformat() if rest_position.recorded_at else None
                ),
            }
            if rest_position
            else None
        ),
        "data_start": snapshot.data_start.isoformat() if snapshot and snapshot.data_start else None,
        "historical_totals_hidden": snapshot.historical_totals_hidden if snapshot else None,
        "fetched_at": snapshot.fetched_at.isoformat() if snapshot else None,
        "pet_name": snapshot.pet_name if snapshot else None,
        "sleep_seconds": window.sleep if window else None,
        "sleep_hours": snapshot.sleep_hours if snapshot else None,
        "window_start": window.start.isoformat() if window and window.start else None,
        "window_end": window.end.isoformat() if window and window.end else None,
        "today_nap_seconds": today.nap if today else None,
        "today_nap_hours": snapshot.nap_hours if snapshot else None,
        "steps": activity.steps if activity else None,
        "step_goal": activity.step_goal if activity else None,
        "week_steps": week.steps if week else None,
        # Metres, and only walks count -- verified on a real walk. A day
        # with thousands of steps and 0 here is a day with no walk.
        "distance_m": activity.distance if activity else None,
        "week_distance_m": week.distance if week else None,
        "problem": snapshot.problem if snapshot else None,
        "stale": bool(snapshot and snapshot.stale),
        # Whose clock the page's HH:MM strings follow: Fi's timezone for the
        # pet, or this server's when that could not be loaded.
        "timezone": profile.timezone if profile else None,
        "clock": (
            None
            if snapshot is None
            else "fi"
            if kona_zone(profile.timezone if profile else None)
            else "server"
        ),
    }


def overnight_json(snapshot: FiSnapshot | None) -> dict[str, Any] | None:
    night = snapshot.overnight if snapshot else None
    if night is None:
        return None
    return {
        "date": night.date.isoformat() if night.date else None,
        "sleep_s": night.sleep_seconds,
        "sleep_start": night.sleep_start.isoformat() if night.sleep_start else None,
        "sleep_end": night.sleep_end.isoformat() if night.sleep_end else None,
        "interruptions": [
            {"start": a.isoformat(), "end": b.isoformat()} for a, b in night.interruptions
        ],
    }
