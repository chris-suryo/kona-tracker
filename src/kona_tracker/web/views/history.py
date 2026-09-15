"""The Steps and Rest pages: hourly and daily buckets drawn as bars, and the
reading under the chart for the selected one.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any

from kona_tracker.fi.parse import HourlyDay
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views.format import (
    DISTANCE_NOTE,
    REST_NOTE,
    _clock,
    _count,
    _day,
    _hhmm,
    _hour_range,
    _minutes,
    kona_zone,
    outdoor_distance,
    scale_label,
    step_ring,
)

#: The chart's y-axis floor, in minutes: twelve hours. A quiet week must not
#: stretch a 40-minute nap to the full height and read as a big day.
REST_CHART_FLOOR_MIN = 720
#: Chart geometry shared with the sample page so the same CSS draws both.
CHART_WIDTH = 336.0
CHART_HEIGHT = 150.0


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
        "fetched_label": _hhmm(fetched_local) if fetched_local else None,
        "clock_zone": fetched_local.strftime("%Z") if zone and fetched_local else None,
        "excluded_note": excluded_note,
        "rest_note": REST_NOTE,
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
        "maximum_label": scale_label(maximum, "min"),
        "selected": selected,
        "chosen": chosen,
        # Today by the hour, from restFeed(period: DAY) -- the Fi app's Day
        # tab. Landed 2026-09-13, after eleven probe rounds.
        **hourly_context(snapshot, "rest", hour, "/rest"),
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
                # Hour labels are always on the hour, so the minutes carry
                # nothing: "9-10 am" rather than "9:00 am - 10:00 am", which
                # is twice the width of the tick it sits under. The suffix
                # appears once unless the hour crosses noon or midnight.
                "label": _hour_range(at),
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
        "hours_maximum_label": scale_label(maximum, "min" if metric == "rest" else "steps"),
        "hours_through": (f"Through {_hhmm(_clock(now, zone))}" if buckets and now else None),
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
            "distance": outdoor_distance(activity.distance if activity else None),
            "distance_note": DISTANCE_NOTE,
            "fetched_label": _hhmm(fetched_local) if fetched_local else None,
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
