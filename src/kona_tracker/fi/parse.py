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
from datetime import datetime
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
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


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


def rest_from(data: Any) -> list[RestWindow]:
    """Rest windows, newest first as Fi returns them."""
    if not isinstance(data, dict):
        return []
    feed = ((data.get("pet") or {}).get("restSummaryFeed") or {}).get("restSummaries") or []
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
