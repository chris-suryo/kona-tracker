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

from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    HourlyDay,
    LocationPoint,
    Overnight,
    PetProfile,
    RestWindow,
    Walk,
    hours_from_duration,
)
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


def duration_parts(seconds: int | float | None) -> list[tuple[str, str]] | None:
    """`30600` -> `[("8", "h"), ("30", "m")]`; `1290` -> `[("22", "m")]`.

    Pairs rather than a string so the template keeps its display-numeral
    look: a big tabular figure with a small unit beside it. Zero is a real
    reading (`[("0", "m")]`, "no naps yet"), and only a figure that seconds
    cannot explain comes back as None, the same plausibility rule the hours
    used to go through, so a unit change still shows as raw rather than as
    a confident wrong number.
    """
    if seconds is None:
        return None
    if seconds != 0 and hours_from_duration(seconds) is None:
        return None
    minutes = int(round(float(seconds) / 60.0))
    hours, minutes = divmod(minutes, 60)
    parts: list[tuple[str, str]] = []
    if hours:
        parts.append((str(hours), "h"))
    if minutes or not hours:
        parts.append((str(minutes), "m"))
    return parts


def step_ring(steps: int | float | None, goal: int | float | None) -> dict[str, Any]:
    """The goal ring's three numbers, none of them capped at "exactly done".

    `percent` is the true figure for the label; `arc` is the first lap,
    which stops at 100; `overflow` is the surplus drawn as a second lap on
    top of the first, also capped at 100. A day at 150% shows a full ring
    with half of a brighter one over it. A third lap would only paint over
    the second and say nothing new, hence the second cap. No goal, or no
    steps, is an empty ring rather than a division by zero in the template.
    """
    if not steps or not goal or goal <= 0:
        return {"percent": 0, "arc": 0.0, "overflow": 0.0}
    percent = float(steps) / float(goal) * 100.0
    return {
        "percent": int(round(percent)),
        "arc": round(min(percent, 100.0), 1),
        "overflow": round(min(max(percent - 100.0, 0.0), 100.0), 1),
    }


def _since(moment: datetime | None, now: datetime | None, zone: tzinfo | None) -> str | None:
    """`10:42`, or `9 Sep 22:10` once it is no longer today. Kona's clock."""
    if moment is None or now is None:
        return None
    local = _clock(moment, zone)
    if local.date() == now.date():
        return local.strftime("%H:%M")
    return f"{_day(local)} {local:%H:%M}"


def _count(value: int | float | None) -> str | None:
    if value is None:
        return None
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _day(moment: Any) -> str | None:
    """`8 Sep`. Built by hand because `%-d` is not portable to Windows."""
    if moment is None:
        return None
    return f"{moment.day} {moment:%b}"


def distance_label(metres: int | float | None) -> str | None:
    """`6449` -> `4.0 mi`; short hops in feet. Chris's phone is set to miles.

    Fi's distance is metres (verified 2026-09-10 and again on the walk log
    2026-09-13). Under about a tenth of a mile, tenths of a mile round to
    nothing useful, so feet it is, to the nearest ten.
    """
    if metres is None or metres < 0:
        return None
    feet = metres * 3.28084
    if feet < 528:  # a tenth of a mile
        return f"{int(round(feet / 10.0) * 10)} ft"
    return f"{metres / 1609.344:.1f} mi"


def _span(start: datetime | None, end: datetime | None, zone: tzinfo | None) -> str | None:
    """`14:23 – 15:06` on Kona's clock; None unless both ends are known."""
    if start is None or end is None:
        return None
    return f"{_clock(start, zone):%H:%M} \u2013 {_clock(end, zone):%H:%M}"


def _age_seconds(moment: datetime | None, now: datetime | None) -> int | None:
    """Whole seconds between a collar fix and now, never negative.

    Sent as a number rather than a timestamp on purpose: the page counts up
    from it locally, so a phone whose clock disagrees with the server's --
    which is every phone, by a few seconds at least -- still shows an age
    that is right, instead of one skewed by the difference between clocks.
    """
    if moment is None or now is None:
        return None
    return max(0, int((now - moment).total_seconds()))


def fix_age_label(seconds: int | None) -> str | None:
    """`47 s ago`, `4 min ago`, `2 h ago`. The unit a person would say.

    Not `age_label`, which is Kona's age in years; this is the age of a GPS
    fix in seconds, and the two live in the same module.
    """
    if seconds is None:
        return None
    if seconds < 90:
        return f"{seconds} s ago"
    if seconds < 5400:  # an hour and a half
        return f"{round(seconds / 60)} min ago"
    return f"{round(seconds / 3600)} h ago"


def walk_rows(walks: tuple[Walk, ...], on: datetime, zone: tzinfo | None) -> list[dict[str, Any]]:
    """The day's activities as rows for the page, newest first as Fi sends them.

    "Today" is Kona's calendar day, the same day the steps total belongs
    to; a walk that started before midnight her time is yesterday's even
    if it is today's in UTC. Car rides are kept as quieter rows with no
    page of their own: they have no route, and a day that went "walk, car,
    walk" reads wrong with the car removed.
    """
    rows: list[dict[str, Any]] = []
    for walk in walks:
        if walk.start is None or _clock(walk.start, zone).date() != on.date():
            continue
        rows.append(
            {
                "id": walk.id,
                "kind": walk.kind,
                "label": "Walk" if walk.kind == "walk" else "Car ride",
                "span": _span(walk.start, walk.end, zone),
                "duration": duration_parts(walk.seconds),
                "steps": _count(walk.steps) if walk.kind == "walk" else None,
                "distance": distance_label(walk.distance_m),
                "area": walk.area_name,
                "href": f"/walks/{walk.id}" if walk.kind == "walk" and walk.path else None,
            }
        )
    return rows


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


#: Alidade Smooth Dark. `{r}` is Leaflet's retina placeholder and is what
#: makes this sharp on a phone; it resolves to "@2x" on a HiDPI screen.
STADIA_DARK = "https://tiles.stadiamaps.com/tiles/alidade_smooth_dark/{z}/{x}/{y}{r}.png"
STADIA_ATTRIBUTION = (
    '&copy; <a href="https://stadiamaps.com/">Stadia Maps</a>, '
    '&copy; <a href="https://openmaptiles.org/">OpenMapTiles</a>, '
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)
#: The key rides in the query string because the app sends no referrer
#: header for domain auth to read. See settings.stadia_api_key.
STADIA_TILES_QUERY = "{base}?api_key={key}"
OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OSM_ATTRIBUTION = (
    '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
)


def map_tile_config(map_tiles: str, stadia_api_key: str = "") -> dict[str, Any]:
    """Tile layer settings for `map.js`, rendered as a JSON data block.

    A separate function, and the only place the Stadia key is written into a
    URL, so there is exactly one line to audit. `dark` says whether the CSS
    filter that fakes a dark basemap should run: Alidade Smooth Dark already
    is dark, and filtering it darkens it twice.

    Falls back to OpenStreetMap rather than raising. A missing key is refused
    at settings load (`settings.py`), so by the time a request renders, the
    only way to be here without one is `map_tiles="osm"`.
    """
    if map_tiles == "stadia" and stadia_api_key:
        return {
            "url": STADIA_TILES_QUERY.format(base=STADIA_DARK, key=stadia_api_key),
            "attribution": STADIA_ATTRIBUTION,
            "maxZoom": 20,
            "dark": True,
        }
    return {
        "url": OSM_TILES,
        "attribution": OSM_ATTRIBUTION,
        "maxZoom": 19,
        "dark": False,
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
        "sleep_parts": duration_parts(window.sleep if window else None),
        "nap_parts": duration_parts(today.nap if today else None),
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
        # Last night as a time span, and the day's walks. Both are Fi's
        # own records (rounds 10-11), not inferred from anything.
        "overnight": overnight_labels(snapshot.overnight if snapshot else None, zone),
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


#: The chart's y-axis floor, in minutes: twelve hours. A quiet week must not
#: stretch a 40-minute nap to the full height and read as a big day.
REST_CHART_FLOOR_MIN = 720
#: Chart geometry shared with the sample page so the same CSS draws both.
CHART_WIDTH = 336.0
CHART_HEIGHT = 150.0


def _minutes(seconds: int | float | None) -> int | None:
    """Whole minutes, or None. A missing reading is not a zero-minute day."""
    return None if seconds is None else int(round(seconds / 60))


def rest_history_context(
    snapshot: FiSnapshot | None,
    configured: bool,
    selected: int | None = None,
    hour: int | None = None,
) -> dict[str, Any]:
    """Everything `rest_history.html` needs: one bar per day the collar has
    existed, from `FiSnapshot.rest_days`, with nothing invented on the way.

    What Fi gives is a daily total of sleep and a daily total of naps. It
    does not give hours, and it does not give when she fell asleep or woke.
    So this page draws days, not hours, and has no interval timeline -- the
    sample page's timeline is a design sketch of data Fi does not send, and
    inferring intervals from totals is the one thing every note in this
    project says not to do.

    Averages cover complete days only, and the page says how many that is.
    Today is in progress; the collar's first day was partial. Both draw as
    bars so the week is visibly the week, and both are labelled.
    """
    days = list(snapshot.rest_days) if snapshot else []
    profile = snapshot.profile if snapshot else None
    zone = kona_zone(profile.timezone if profile else None)
    fetched_local = _clock(snapshot.fetched_at, zone) if snapshot else None

    buckets: list[dict[str, Any]] = []
    for d in days:
        # A day is named by its window's start as Fi sent it, exactly as the
        # hero's "9 Sep to 10 Sep" is (`window_from`, above). Fi anchors the
        # window at midnight in the owner's zone, so that date *is* the day;
        # re-deriving it through Kona's timezone can only disagree with the
        # hero, and did, by one day, when the two were first drawn together.
        start = d.window.start
        buckets.append(
            {
                "date": start.date().isoformat(),  # type: ignore[union-attr]
                "label": f"{_day(start)}",
                "short": start.strftime("%a"),  # type: ignore[union-attr]
                "value": _minutes(d.total),
                "sleep": _minutes(d.window.sleep),
                "nap": _minutes(d.window.nap),
                "complete": d.complete,
                "in_progress": d.in_progress,
                "partial_first_day": d.partial_first_day,
                # The sample page's vocabulary, so its CSS applies unchanged.
                "partial": not d.complete,
                "future": False,
            }
        )

    complete = [b for b in buckets if b["complete"]]

    def _avg(key: str) -> int | None:
        readings = [b[key] for b in complete if b[key] is not None]
        return int(round(sum(readings) / len(readings))) if readings else None

    peak = max((b["value"] or 0 for b in buckets), default=0)
    maximum = max(REST_CHART_FLOOR_MIN, ((peak + 59) // 60) * 60)
    if buckets:
        spacing = CHART_WIDTH / len(buckets)
        for i, b in enumerate(buckets):
            b["x"] = round(2 + i * spacing, 2)
            b["width"] = round(spacing - 12, 2)
            b["height"] = round((b["value"] or 0) / maximum * CHART_HEIGHT, 2)
            b["sleep_height"] = round((b["sleep"] or 0) / maximum * CHART_HEIGHT, 2)
            b["nap_height"] = round((b["nap"] or 0) / maximum * CHART_HEIGHT, 2)
            b["href"] = f"/rest?selected={i}#chart-title"

    chosen = buckets[selected] if selected is not None and selected < len(buckets) else None
    first, last = (buckets[0], buckets[-1]) if buckets else (None, None)
    # Say only what was actually left out. With no collar cutoff configured
    # there is no "first day" to exclude, and the sentence must not claim one.
    left_out = []
    if any(b["in_progress"] for b in buckets):
        left_out.append("today")
    if any(b["partial_first_day"] for b in buckets):
        left_out.append("the collar's first day")
    excluded_note = (
        f"{' and '.join(left_out)} {'are' if len(left_out) > 1 else 'is'} excluded"
        if left_out
        else None
    )
    return {
        "tab": None,
        "preview": False,
        "configured": configured,
        "has_days": bool(buckets),
        "stale": bool(snapshot and snapshot.stale),
        "problem": snapshot.problem if snapshot else None,
        "fetched_label": fetched_local.strftime("%H:%M") if fetched_local else None,
        "clock_zone": fetched_local.strftime("%Z") if zone and fetched_local else None,
        "excluded_note": excluded_note,
        "range_label": (
            f"{first['label']} – {last['label']}"
            if first and last and first != last
            else first["label"]
            if first
            else None
        ),
        "buckets": buckets,
        "complete_days": len(complete),
        "total_days": len(buckets),
        "average": _avg("value"),
        "average_sleep": _avg("sleep"),
        "average_nap": _avg("nap"),
        "maximum": maximum,
        "selected": selected,
        "chosen": chosen,
        # Today by the hour, from restFeed(period: DAY) -- the Fi app's Day
        # tab. Landed 2026-09-13, after eleven probe rounds.
        **hourly_context(snapshot, "rest", hour, "/rest"),
    }


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
    "reader_limit": (
        "Camera recovery is stuck. For USB, unplug and reconnect; otherwise restart the server."
    ),
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


def walk_context(
    snapshot: FiSnapshot | None, walk_id: str, configured: bool
) -> dict[str, Any] | None:
    """Everything `walk.html` needs for one walk, or None when it is not in
    the snapshot -- which is a 404, not an empty page: the id came from a
    link this app rendered, so its absence means the feed has moved on."""
    if snapshot is None:
        return None
    walk = next((w for w in snapshot.walks if w.id == walk_id), None)
    if walk is None:
        return None
    profile = snapshot.profile
    zone = kona_zone(profile.timezone if profile else None)
    fetched_local = _clock(snapshot.fetched_at, zone)
    start_local = _clock(walk.start, zone) if walk.start else None
    if start_local is None:
        day = None
    elif start_local.date() == fetched_local.date():
        day = "Today"
    elif start_local.date() == fetched_local.date() - timedelta(days=1):
        day = "Yesterday"
    else:
        day = f"{start_local:%a} {_day(start_local)}"
    seconds = walk.seconds
    pace = None
    if seconds and walk.distance_m and walk.distance_m > 0:
        minutes_per_mile = (seconds / 60.0) / (walk.distance_m / 1609.344)
        if 3 <= minutes_per_mile <= 120:
            pace = f"{int(minutes_per_mile)}:{int(round((minutes_per_mile % 1) * 60)):02d} /mi"
    return {
        "tab": None,
        "configured": configured,
        "walk_id": walk.id,
        "kind": walk.kind,
        "title": "Walk" if walk.kind == "walk" else "Car ride",
        "day": day,
        "span": _span(walk.start, walk.end, zone),
        "elapsed": duration_parts(seconds),
        "steps": _count(walk.steps),
        "distance": distance_label(walk.distance_m),
        "pace": pace,
        "area": walk.area_name,
        "points": len(walk.path),
        "map_points": [
            {"lat": p.latitude, "lon": p.longitude, "accuracy": None} for p in walk.path
        ],
        "map_kind": "walk",
        "stale": bool(snapshot.stale),
        "as_of": fetched_local.strftime("%H:%M"),
        "clock_zone": fetched_local.tzname() or "",
    }


def walks_json(snapshot: FiSnapshot | None) -> list[dict[str, Any]] | None:
    if snapshot is None:
        return None
    return [
        {
            "id": w.id,
            "kind": w.kind,
            "start": w.start.isoformat() if w.start else None,
            "end": w.end.isoformat() if w.end else None,
            "seconds": w.seconds,
            "steps": w.steps,
            "distance_m": w.distance_m,
            "area_name": w.area_name,
            "path_points": len(w.path),
        }
        for w in snapshot.walks
    ]


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


#: An hour holds sixty minutes, so the rest chart's ceiling is fixed; the
#: steps chart floors at the sample page's 3,000 and grows to the next
#: thousand above the busiest hour, so a quiet day is not a wall of bars
#: and a big walk is not clipped.
HOUR_REST_MAX_MIN = 60
HOUR_STEPS_FLOOR = 3000


def hourly_buckets(
    day: HourlyDay | None, metric: str, now: datetime | None, zone: tzinfo | None, href: str
) -> list[dict[str, Any]]:
    """Twenty-four bars for today, in the sample page's vocabulary so its CSS
    draws them unchanged. Hours after `now` are `future`; the hour in
    progress is not, because Fi has already begun counting it.

    Bucket `i` is `start + i hours` on Kona's clock. `start` is Fi's own
    midnight for her, so the labels come out as 00:00, 01:00 ... without
    any timezone arithmetic of ours; the zone is used only to decide which
    hours have not happened yet.
    """
    if day is None or day.start is None:
        return []
    present = day.rest_present if metric == "rest" else day.steps_present
    if not present:
        return []
    start_local = _clock(day.start, zone)
    now_local = _clock(now, zone) if now else None
    buckets: list[dict[str, Any]] = []
    for i, hour in enumerate(day.hours):
        at = start_local + timedelta(hours=i)
        future = bool(now_local and at > now_local)
        if metric == "rest":
            value = None if future else _minutes(hour.rest_s)
            sleep, nap = (None, None) if future else (_minutes(hour.sleep_s), _minutes(hour.nap_s))
        else:
            value = None if future else (int(hour.steps) if hour.steps is not None else None)
            sleep = nap = None
        buckets.append(
            {
                "label": f"{at:%H:%M}\u2013{(at + timedelta(hours=1)):%H:%M}",
                "short": f"{at:%H}",
                "value": value,
                "sleep": sleep,
                "nap": nap,
                "future": future,
                "partial": False,
                "href": f"{href}?hour={i}#hours-title",
            }
        )
    if metric == "rest":
        maximum = HOUR_REST_MAX_MIN
    else:
        peak = max((b["value"] or 0 for b in buckets), default=0)
        maximum = max(HOUR_STEPS_FLOOR, ((peak + 999) // 1000) * 1000)
    spacing = CHART_WIDTH / len(buckets)
    for i, b in enumerate(buckets):
        b["x"] = round(2 + i * spacing, 2)
        b["width"] = round(spacing - 3, 2)
        b["height"] = round(min(b["value"] or 0, maximum) / maximum * CHART_HEIGHT, 2)
        b["sleep_height"] = round(min(b["sleep"] or 0, maximum) / maximum * CHART_HEIGHT, 2)
        b["nap_height"] = round(min(b["nap"] or 0, maximum) / maximum * CHART_HEIGHT, 2)
    return buckets


def hourly_context(
    snapshot: FiSnapshot | None, metric: str, hour: int | None, href: str
) -> dict[str, Any]:
    """The hourly section for `/rest` (metric "rest") or the `/steps` page."""
    day = snapshot.hourly if snapshot else None
    profile = snapshot.profile if snapshot else None
    zone = kona_zone(profile.timezone if profile else None)
    now = snapshot.fetched_at if snapshot else None
    buckets = hourly_buckets(day, metric, now, zone, href)
    chosen = buckets[hour] if hour is not None and buckets and hour < len(buckets) else None
    counted = [b for b in buckets if not b["future"]]
    if metric == "rest":
        maximum = HOUR_REST_MAX_MIN
        sleep_total = sum(b["sleep"] for b in counted if b["sleep"] is not None)
        nap_total = sum(b["nap"] for b in counted if b["nap"] is not None)
        total = sleep_total + nap_total if counted else None
    else:
        peak = max((b["value"] or 0 for b in buckets), default=0)
        maximum = max(HOUR_STEPS_FLOOR, ((peak + 999) // 1000) * 1000)
        sleep_total = nap_total = None
        # Fi's own day total, not a sum of the bars: the bars can lag it.
        total = day.steps_total if day and day.steps_present else None
    return {
        "hours": buckets,
        "hours_maximum": maximum,
        "hours_through": (f"Through {_clock(now, zone):%H:%M}" if buckets and now else None),
        "hour": hour,
        "hour_chosen": chosen,
        "hours_total": total,
        "hours_sleep": sleep_total,
        "hours_nap": nap_total,
        "hours_date": _day(_clock(day.start, zone)) if day and day.start else None,
    }


def steps_context(
    snapshot: FiSnapshot | None, configured: bool, hour: int | None = None
) -> dict[str, Any]:
    """Everything `steps.html` needs: Fi's day total and the hour buckets."""
    activity = snapshot.activity if snapshot else None
    profile = snapshot.profile if snapshot else None
    zone = kona_zone(profile.timezone if profile else None)
    fetched_local = _clock(snapshot.fetched_at, zone) if snapshot else None
    ctx = hourly_context(snapshot, "steps", hour, "/steps")
    ctx.update(
        {
            "tab": None,
            "preview": False,
            "configured": configured,
            "stale": bool(snapshot and snapshot.stale),
            "problem": snapshot.problem if snapshot else None,
            "steps": _count(activity.steps if activity else None),
            "step_goal": _count(activity.step_goal if activity else None),
            "ring": step_ring(
                activity.steps if activity else None, activity.step_goal if activity else None
            ),
            "distance": distance_label(activity.distance if activity else None),
            "fetched_label": fetched_local.strftime("%H:%M") if fetched_local else None,
            "clock_zone": fetched_local.strftime("%Z") if zone and fetched_local else None,
        }
    )
    return ctx


def hourly_json(snapshot: FiSnapshot | None) -> dict[str, Any] | None:
    day = snapshot.hourly if snapshot else None
    if day is None:
        return None
    return {
        "start": day.start.isoformat() if day.start else None,
        "rest_present": day.rest_present,
        "steps_present": day.steps_present,
        "steps_total": day.steps_total,
        "hours": [{"sleep_s": h.sleep_s, "nap_s": h.nap_s, "steps": h.steps} for h in day.hours],
    }


# --------------------------------------------------------------------------
# The full-screen live map.
#
# Chris asked for it after the 2026-09-13 walk: the Activity card's map is a
# tile you cannot enlarge, and on a walk the map is the whole point. This is
# its own page so it can hold what a live map needs -- distance, elapsed, how
# old the fix is -- and poll on its own clock without the rest of Activity
# re-rendering underneath it.
# --------------------------------------------------------------------------
#: What the map page calls each state. `activity_context` decides which one
#: applies; this only names it, so both pages cannot disagree.
MAP_TITLES = {
    "current": "On a walk",
    "rest": "Resting",
    "last": "Last GPS fix",
    "home": "Home",
}


def live_map_context(snapshot: FiSnapshot | None, configured: bool) -> dict[str, Any]:
    """Everything `map_live.html` needs, borrowed from the Activity page.

    Deliberately a thin layer over `activity_context` rather than its own
    reading of the snapshot: the decision about what the map may honestly
    claim (current / rest / last / home, and the staleness rules behind it)
    is subtle and already made once. A second copy would drift, and the two
    pages would eventually disagree about where the dog is.
    """
    context = activity_context(snapshot, configured=configured)
    status = snapshot.status if snapshot else None
    elapsed = None
    if status and status.activity_since and snapshot and snapshot.fetched_at:
        elapsed = duration_parts(
            max(0.0, (snapshot.fetched_at - status.activity_since).total_seconds())
        )
    context.update(
        {
            "tab": None,  # full-bleed: the map is the page, not a tab within it
            "map_title": MAP_TITLES.get(context["map_kind"] or "", "Location unavailable"),
            "elapsed": elapsed,
            "fix_age": fix_age_label(context["fix_age_s"]),
        }
    )
    return context


def live_map_json(snapshot: FiSnapshot | None, configured: bool) -> dict[str, Any]:
    """The same, small enough to poll every few seconds while walking.

    Its own endpoint rather than `/activity.json`, which carries the rest
    history, the walk log and the hourly buckets -- kilobytes that do not
    change while someone watches a dot move.
    """
    context = live_map_context(snapshot, configured=configured)
    return {
        "configured": configured,
        "points": context["map_points"],
        "kind": context["map_kind"],
        "title": context["map_title"],
        "area": context["area_name"],
        "distance": context["walk_distance"],
        "elapsed": context["elapsed"],
        "activity": context["activity"],
        "activity_since": context["activity_since"],
        # Seconds, not a timestamp: the page counts up from it, so a phone
        # clock that disagrees with this one does not corrupt the age.
        "fix_age_s": context["fix_age_s"],
        "reported": context["location_updated"],
        "live": context["location_live"],
        "stale": context["stale"],
        "partial": context["partial"],
        "escaped": context["escaped"],
        "lost": context["lost"],
        "signal": context["signal"],
        "on_base": context["on_base"],
    }
