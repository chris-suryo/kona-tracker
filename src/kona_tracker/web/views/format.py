"""The small formatters every page shares: clocks, durations, counts,
distances, the goal ring, the dial. Nothing here knows what page it is on.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from kona_tracker.fi.parse import hours_from_duration

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
    the second and say nothing new, hence the second cap.

    `known` is the difference between two states this used to collapse into
    one confident "0%": a day on which she genuinely has not moved yet, and
    a server with no collar configured at all, where the steps are unknown
    and there is no goal to measure them against. The second was printing a
    measurement (ChatGPT's visual audit, 2026-09-13). An empty ring is right
    for both; the number in the middle is only right for the first.
    """
    if steps is None or not goal or goal <= 0:
        return {"percent": None, "arc": 0.0, "overflow": 0.0, "known": False}
    percent = float(steps) / float(goal) * 100.0
    return {
        "percent": int(round(percent)),
        "arc": round(min(percent, 100.0), 1),
        "overflow": round(min(max(percent - 100.0, 0.0), 100.0), 1),
        "known": True,
    }


def _hhmm(moment: datetime) -> str:
    """`9:27 pm`. Kona's clock, the way her people read one.

    Built from arithmetic rather than a strftime directive on purpose: the
    no-pad hour is `%-I` on glibc and `%#I` on Windows, and `%-I` raises
    ValueError there. This app is served from a Windows PC, and that exact
    mistake broke its Settings page once already (PR #49). `%I` would pad to
    "09:27 pm", which is not how anyone writes it.

    Lower-case am/pm: it sits beside numbers all over this app, and capitals
    shout next to a 48px figure.
    """
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'}"


def _hour_range(at: datetime) -> str:
    """`9-10 am`, or `11 am-12 pm` when the hour crosses over."""
    end = at + timedelta(hours=1)
    start_h, end_h = at.hour % 12 or 12, end.hour % 12 or 12
    start_m = "am" if at.hour < 12 else "pm"
    end_m = "am" if end.hour < 12 else "pm"
    if start_m == end_m:
        return f"{start_h}\u2013{end_h} {end_m}"
    return f"{start_h} {start_m}\u2013{end_h} {end_m}"


def _since(moment: datetime | None, now: datetime | None, zone: tzinfo | None) -> str | None:
    """`10:42`, or `9 Sep 22:10` once it is no longer today. Kona's clock."""
    if moment is None or now is None:
        return None
    local = _clock(moment, zone)
    if local.date() == now.date():
        return _hhmm(local)
    return f"{_day(local)} {_hhmm(local)}"


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


#: Said next to a step count, so the two numbers cannot be read as rivals.
#:
#: This is the sentence `docs/device-capabilities.md` made a condition of
#: showing the figure at all. Fi's own assistant settled what it measures:
#: *"Fi counts distance based on GPS tracking during outdoor movement, not
#: just step count from the collar's accelerometer."* So a day of 46,725
#: steps and 0.6 mi is not a contradiction and not a bug -- it is a dog who
#: moved all day indoors and went out once. Printed bare, as it was until
#: 2026-09-15, it reads as one of those two numbers being wrong.
DISTANCE_NOTE = (
    "Distance is GPS, so only time outdoors adds to it. "
    "Her steps are counted everywhere, indoors included."
)

#: The same job for the rest chart. Fi splits rest into sleep and naps and
#: never says how; this at least stops the reader inventing a rule.
REST_NOTE = (
    "Fi calls her longest settled stretch overnight sleep, and the shorter "
    "daytime ones naps. The split is Fi's, not ours."
)


def outdoor_distance(metres: int | float | None) -> str | None:
    """`6449` -> `4.0 mi outdoors`. None when Fi did not say.

    The word is load-bearing and is why this exists rather than the page
    calling `distance_label` directly: `docs/device-capabilities.md` lifted
    the block on showing distance "provided it is labelled as outdoor or
    walk distance and a zero is never presented as 'she did not move'".
    A bare "0.6 mi" beside five figures of steps met neither half.

    Zero gets words rather than "0 ft" for the second half of that rule: on a
    day she never left the house the true statement is that there is no
    outdoor distance, not that she was still.
    """
    if metres is None or metres < 0:
        return None
    if metres == 0:
        return "No time outdoors yet"
    return f"{distance_label(metres)} outdoors"


def _span(start: datetime | None, end: datetime | None, zone: tzinfo | None) -> str | None:
    """`14:23 – 15:06` on Kona's clock; None unless both ends are known."""
    if start is None or end is None:
        return None
    return f"{_hhmm(_clock(start, zone))} \u2013 {_hhmm(_clock(end, zone))}"


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


def scale_label(minutes: int | float | None, unit: str) -> str:
    """A chart's top gridline, said the way a person would.

    This is the number beside a chart heading, and it is a *scale* -- the
    height of the top gridline -- not a summary of anything. For steps that
    is fine as a count. For rest it was four digits of minutes: "1,080 min"
    makes a reader divide by sixty to learn the chart tops out at eighteen
    hours, and next to "Average daily rest 15h 34m" it reads like a rival
    total rather than an axis.
    """
    if minutes is None:
        return ""
    if unit != "min":
        return f"{minutes:,.0f} {unit}"
    # Below two hours, minutes are the clearer unit: the hourly chart's
    # ceiling is 60, and "1 h" for a bar that measures minutes within an hour
    # is a conversion the reader did not ask for. The daily chart tops out in
    # the hundreds, where "1,080 min" is the conversion instead.
    if minutes < 120:
        return f"{minutes:,.0f} min"
    hours = minutes / 60.0
    # A whole number of hours needs no decimal; 90 minutes is "1.5 h" rather
    # than "2 h", because rounding an axis away from its data is how a bar
    # comes to touch a ceiling it does not reach.
    return f"{hours:.0f} h" if minutes % 60 == 0 else f"{hours:.1f} h"


def _minutes(seconds: int | float | None) -> int | None:
    """Whole minutes, or None. A missing reading is not a zero-minute day."""
    return None if seconds is None else int(round(seconds / 60))
