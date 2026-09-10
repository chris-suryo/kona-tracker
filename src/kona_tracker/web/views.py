"""Turning an `FiSnapshot` into the exact strings the Activity page prints.

Formatting lives here rather than in the template so it can be tested, and
so the "we do not know this" cases are decided once in Python instead of
scattered through Jinja conditionals. Anything Fi did not return comes back
as `None`, and the template renders the muted dash for it.
"""

from __future__ import annotations

from typing import Any

from kona_tracker.fi.service import FiSnapshot

# The dial's visible track is a 270 degree arc; 603 is its length in user
# units, taken straight from the `stroke-dasharray` in app.css. Keep the two
# in step: the arc is drawn by offsetting this exact number.
TRACK = 603.0

# What a full ring means. Fi publishes no target for sleep the way it does
# for steps, so this is our scale, not Fi's, and the page says so.
DIAL_SCALE_HOURS = 12.0


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
    sleep_hours = snapshot.sleep_hours if snapshot else None

    return {
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
        "as_of": (
            snapshot.fetched_at.astimezone().strftime("%H:%M")
            if snapshot and snapshot.has_data
            else None
        ),
        "problem": snapshot.problem if snapshot else None,
    }


def activity_json(snapshot: FiSnapshot | None, configured: bool) -> dict[str, Any]:
    """The same data as the page, for polling later. Never the credentials."""
    window = snapshot.window if snapshot else None
    today = snapshot.today if snapshot else None
    activity = snapshot.activity if snapshot else None
    week = snapshot.week if snapshot else None
    return {
        "configured": configured,
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
        # Raw and unexplained: 0 on a day with thousands of steps. Not on the
        # page until somebody knows what it measures.
        "distance_raw": activity.distance if activity else None,
        "week_distance_raw": week.distance if week else None,
        "problem": snapshot.problem if snapshot else None,
        "stale": bool(snapshot and snapshot.stale),
    }
