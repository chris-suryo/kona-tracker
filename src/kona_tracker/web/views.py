"""Turning an `FiSnapshot` into the exact strings the Activity page prints.

Formatting lives here rather than in the template so it can be tested, and
so the "we do not know this" cases are decided once in Python instead of
scattered through Jinja conditionals. Anything Fi did not return comes back
as `None`, and the template renders the muted dash for it.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kona_tracker.fi.parse import ActivityStats, CollarStatus, LocationPoint, PetProfile, RestWindow
from kona_tracker.fi.service import FiSnapshot

# The dial's visible track is a 270 degree arc; 603 is its length in user
# units, taken straight from the `stroke-dasharray` in app.css. Keep the two
# in step: the arc is drawn by offsetting this exact number.
TRACK = 603.0

# What a full ring means. Fi publishes no target for sleep the way it does
# for steps, so this is our scale, not Fi's, and the page says so.
DIAL_SCALE_HOURS = 12.0


def _location_label(status: Any) -> str | None:
    """A useful place label that does not publish a street address."""
    if status is None:
        return None
    if status.area_name:
        return status.area_name
    if not status.place_name:
        return None
    if status.activity == "rest" and re.match(r"^\s*\d+\s+\S", status.place_name):
        return "Home"
    return status.place_name


def kona_zone(timezone: str | None) -> tzinfo | None:
    """Kona's timezone, from Fi, or None when it cannot be loaded.

    Times on the page are *her* times -- "last night" means her night, and
    the map's "Last report" is when it happened where she is, whatever zone
    the phone reading it is in. None falls back to the server's clock, which
    is the same thing while the PC sits at home with her, and is labelled in
    the JSON so it is never mistaken for the deliberate answer. Windows has
    no timezone database of its own: without the `tzdata` package this is
    always None there.
    """
    if not timezone:
        return None
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None


def _clock(moment: datetime, zone: tzinfo | None) -> datetime:
    return moment.astimezone(zone) if zone else moment.astimezone()


def _hours(value: float | None) -> str | None:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value is not None else None


def _count(value: int | float | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _day(moment: Any) -> str | None:
    """`8 Sep`. Built by hand because `%-d` is not portable to Windows."""
    if moment is None:
        return None
    return f"{moment.day} {moment:%b}"


def age_label(birthday: date | None, on: datetime) -> str | None:
    """`13 months`, `1 year 1 month`, `3 years`. None without a birthday."""
    if birthday is None:
        return None
    months = (on.year - birthday.year) * 12 + on.month - birthday.month
    if on.day < birthday.day:
        months -= 1
    if months < 0:
        return None
    if months < 12:
        return f"{months} month{'s' if months != 1 else ''}"
    years, rest = divmod(months, 12)
    label = f"{years} year{'s' if years != 1 else ''}"
    if years < 2 and rest:
        label += f" {rest} month{'s' if rest != 1 else ''}"
    return label


def dial_offset(hours: float | None) -> float:
    """`stroke-dashoffset` that reveals `hours` of the ring.

    No data leaves the arc empty rather than drawing a guess, and more than
    a full ring clamps instead of wrapping back around to look like less.
    """
    if hours is None:
        return TRACK
    fraction = min(max(hours / DIAL_SCALE_HOURS, 0.0), 1.0)
    return round(TRACK * (1.0 - fraction), 1)


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
    positions = status.positions if status else ()
    rest_position = status.rest_position if status else None
    home_position = status.home_location if status else None
    stale = bool(snapshot and snapshot.stale)
    walking = bool(positions and status and status.activity == "walk")
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
        "escaped": status.escaped if status else None,
        "lost": status.lost if status else None,
        # Metres, walk-only, verified 2026-09-10: a 285.8 m OngoingWalk
        # became totalDistance 286 for the day. A true 0 is a real "no walk".
        "distance_m": _count(activity.distance if activity else None),
        "walk_distance_m": _count(status.walk_distance) if status else None,
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
            _clock(last_position.recorded_at, zone).strftime("%H:%M")
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
        "tab": "activity",
        "configured": configured,
        "has_data": bool(snapshot and snapshot.has_data),
        "pet_name": (snapshot.pet_name if snapshot else "") or "Kona",
        "sleep_hours": _hours(sleep_hours),
        "nap_hours": _hours(snapshot.nap_hours if snapshot else None),
        # The collar was paired today: there is a day in progress but no
        # completed night yet. Say so, rather than "no data".
        "night_pending": window is None and today is not None,
        # Kept so a unit change shows the real figure instead of nothing.
        "sleep_raw": window.sleep if window else None,
        "nap_raw": today.nap if today else None,
        "unit_suspect": bool(snapshot and snapshot.unit_suspect),
        # Two different failures that must not share a sentence: "stale"
        # means these numbers are old, "partial" means they are current
        # but one query did not come back.
        "stale": bool(snapshot and snapshot.stale),
        "partial": bool(snapshot and snapshot.partial),
        "window_from": _day(window.start if window else None),
        "window_to": _day(window.end if window else None),
        "steps": _count(activity.steps if activity else None),
        "step_goal": _count(activity.step_goal if activity else None),
        # Distance is deliberately not here: it came back 0 for a day with
        # 3,383 steps, so until it is understood it lives in the JSON only.
        "week_steps": _count(week.steps if week else None),
        "dial_offset": dial_offset(sleep_hours),
        "dial_scale": f"{DIAL_SCALE_HOURS:.0f}",
        # Only stamped when there is something for it to date. "As of 18:48"
        # over an empty dial reads as "we checked and she slept nothing".
        "as_of": (fetched_local.strftime("%H:%M") if fetched_local and snapshot.has_data else None),
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
    now = datetime.now(UTC)
    start = (now - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    snapshot = FiSnapshot(
        fetched_at=now,
        pet_name="Kona",
        window=RestWindow(start, start + timedelta(days=1), 8 * 3600 + 12 * 60, 0),
        today=RestWindow(
            start + timedelta(days=1),
            start + timedelta(days=2),
            0,
            1 * 3600 + 24 * 60,
        ),
        activity=ActivityStats(18_240, 28_000, 2100),
        week=ActivityStats(142_300, 196_000, None),
        profile=PetProfile(name="Kona", breed="Labrador Retriever", birthday=date(2025, 8, 15)),
        status=CollarStatus(
            battery_percent=57,
            on_base=False,
            signal_percent=78,
            activity="walk",
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


#: `CameraHub.status()` in words a phone can act on. The error kinds are the
#: hub's own; the sentences are `camera-doctor`'s verdicts, so the settings
#: page says from the road what the doctor would say at the machine.
_CAMERA_STATES = {
    "live": "Delivering frames",
    "stale": "Frames have stopped",
    "connecting": "Opening the camera",
    "disconnected": "Not connected",
    "idle": "Released (nobody is watching)",
}
_CAMERA_PROBLEMS = {
    "black_frame": (
        "Image fully dark. Lens cover, or a wedged USB device: "
        "unplug the camera and plug it back in."
    ),
    "open": "Could not open the camera. Another program may be holding it.",
    "hung": "The camera stopped answering. A reconnect was requested.",
    "read": "Reading frames failed.",
    "empty_frames": "The camera opened but delivered no frames: unplug it and plug it back in.",
}


def camera_health(status: dict[str, Any]) -> dict[str, Any]:
    """Rows for the settings page. Nothing here is invented: an unknown
    state or error kind is shown as the raw word, never dressed up."""
    state = status.get("state")
    kind = status.get("last_error_kind")
    age = status.get("last_frame_age")
    return {
        "state": _CAMERA_STATES.get(state, str(state)),
        "live": state == "live",
        "last_frame": None if age is None else f"{age:.0f} s ago",
        "problem": _CAMERA_PROBLEMS.get(kind, kind) if kind else None,
        "reconnects": status.get("reconnects") or 0,
    }
