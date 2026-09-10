"""Turning Fi's JSON into values we are willing to put on a screen.

These parsers live here, not in the probe or the web app, because both read
the same responses and a second copy would eventually disagree with the
first. `probe/run.py` and `fi/service.py` both call them.

The governing rule is that a missing field is never a measured zero, and a
value we cannot interpret is never rendered as though we could. Every parser
returns `None` for absent data and the caller decides how to say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Fi documents no units. The fixture's 30600 is 8.5 hours if it is seconds,
# which is a plausible night for a dog; 30600 minutes is three weeks, and
# 30600 hours is three years. So seconds is the working assumption — but an
# assumption we refuse to hide. Anything outside this range means the unit
# is not what we think, and the caller shows the raw number instead.
MIN_PLAUSIBLE_HOURS = 0.0
MAX_PLAUSIBLE_HOURS = 24.0

SLEEP = "SLEEP"
NAP = "NAP"


def _num(value: Any) -> int | float | None:
    """A real number, or None. `bool` is excluded: `True` is not a step count."""
    if type(value) in (int, float):
        return value
    return None


@dataclass(frozen=True)
class Pet:
    id: str
    name: str


@dataclass(frozen=True)
class RestWindow:
    """One row of `restSummaryFeed`.

    `start`/`end` bound the window Fi grouped the sleep into — a calendar
    day for DAILY — and are **not** the moment Kona fell asleep. Nothing
    here may be labelled "asleep at" without evidence we do not have.
    """

    start: datetime | None
    end: datetime | None
    sleep: int | float | None
    nap: int | float | None


@dataclass(frozen=True)
class ActivityStats:
    steps: int | float | None
    step_goal: int | float | None
    distance: int | float | None  # raw API units; not verified as metres


def hours_from_duration(value: Any) -> float | None:
    """Seconds -> hours, or None if the result is not a plausible duration.

    Returning None is the whole point: if Fi ever switches units, the page
    shows the raw figure marked raw rather than a confident "408 h asleep".
    """
    seconds = _num(value)
    if seconds is None:
        return None
    hours = seconds / 3600.0
    if MIN_PLAUSIBLE_HOURS <= hours <= MAX_PLAUSIBLE_HOURS:
        return hours
    return None


def _moment(value: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    # Fi sends offsets. If one ever arrives bare, treat it as UTC rather than
    # letting a naive/aware comparison blow up inside `split_windows`.
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def pets_from(data: Any) -> list[Pet]:
    """Pets across every household on the account."""
    pets: list[Pet] = []
    if not isinstance(data, dict):
        return pets
    for uh in (data.get("currentUser") or {}).get("userHouseholds") or []:
        for pet in (uh.get("household") or {}).get("pets") or []:
            if pet and pet.get("id") is not None:
                pets.append(Pet(id=str(pet["id"]), name=str(pet.get("name") or "")))
    return pets


def rest_from(data: Any, period: str = "dailyStat") -> list[RestWindow]:
    """Rest windows for one aliased period, newest first as Fi returns them.

    `period` is the alias in the query (`dailyStat`, `weeklyStat`,
    `monthlyStat`), not the enum.
    """
    if not isinstance(data, dict):
        return []
    feed = ((data.get("pet") or {}).get(period) or {}).get("restSummaries") or []
    windows: list[RestWindow] = []
    for summary in feed:
        amounts = (summary.get("data") or {}).get("sleepAmounts") or []
        by_type = {a.get("type"): a.get("duration") for a in amounts if isinstance(a, dict)}
        windows.append(
            RestWindow(
                start=_moment(summary.get("start")),
                end=_moment(summary.get("end")),
                sleep=_num(by_type.get(SLEEP)),
                nap=_num(by_type.get(NAP)),
            )
        )
    return windows


def split_windows(
    windows: list[RestWindow], now: datetime
) -> tuple[RestWindow | None, RestWindow | None]:
    """(the most recent *completed* day, the day containing `now`).

    Measured on Kona's collar: Fi's daily window runs midnight to midnight in
    the owner's timezone and the newest one is **today, still in progress**,
    with SLEEP=0 because tonight has not happened. Last night's sleep sits in
    the window that ended this morning. A page headed "Last night" that read
    the newest window would show 0 h, formatted honestly, and be wrong.
    """
    completed = [w for w in windows if w.end is not None and w.end <= now]
    current = [
        w for w in windows if w.start is not None and w.end is not None and w.start <= now < w.end
    ]
    last = max(completed, key=lambda w: w.end) if completed else None  # type: ignore[arg-type,return-value]
    return last, (current[0] if current else None)


def activity_from(data: Any, period: str = "dailyStat") -> ActivityStats:
    """One `currentActivitySummary` block. Absent fields stay None."""
    stats: Any = {}
    if isinstance(data, dict):
        stats = (data.get("pet") or {}).get(period) or {}
    return ActivityStats(
        steps=_num(stats.get("totalSteps")),
        step_goal=_num(stats.get("stepGoal")),
        distance=_num(stats.get("totalDistance")),
    )
