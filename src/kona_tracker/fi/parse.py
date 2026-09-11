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
from datetime import UTC, date, datetime
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
MAX_LOCATION_POINTS = 250


def _dict(value: Any) -> dict[str, Any]:
    """`value` if it is a dict, else `{}`.

    Every nested lookup goes through this. Fi changing a field from an object
    to a string must read as "absent", not raise inside `fetch_snapshot` and
    take the already-fetched sleep and steps down with it. That is the
    difference between a "Collar:" partial and a blank page.
    """
    return value if isinstance(value, dict) else {}


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
class PetProfile:
    """Who she is, from the Fi profile. Every field measured 2026-09-10."""

    name: str = ""
    breed: str | None = None
    birthday: date | None = None
    #: The photo set in the Fi app. A URL on Fi's CDN; served through our
    #: own `/avatar.jpg` so it never reaches the browser and a dead link
    #: degrades to the initial.
    photo_url: str | None = None


@dataclass(frozen=True)
class LocationPoint:
    """One bounded, validated GPS fix from the collar."""

    latitude: float
    longitude: float
    recorded_at: datetime | None = None
    accuracy_m: int | float | None = None


@dataclass(frozen=True)
class CollarStatus:
    """The collar right now. Measured shapes only; `None` is "not reported".

    Battery is not on `Pet` or `Device` -- both rejected every battery name
    -- it lives inside the `device.info` blob. `on_base` comes from the
    connection state's concrete type: `ConnectedToBase` when she is on the
    charger, `ConnectedToCellular` (with a signal) when she is out.
    """

    battery_percent: int | float | None = None
    time_to_empty_s: int | float | None = None
    on_base: bool | None = None
    signal_percent: int | float | None = None
    led_on: bool | None = None
    led_color: str | None = None
    mode: str | None = None
    #: Measured 2026-09-10: `mode` went NORMAL -> POST_ESCAPE_NOTIFICATION
    #: when she left the safe zone without an owner's phone, and stayed
    #: there through the walk that followed. LOST_DOG is pytryfi's name for
    #: the mode its mutation sets; not yet seen from the API.
    escaped: bool = False
    lost: bool = False
    #: "rest" | "walk" | None, from `ongoingActivity.__typename`.
    activity: str | None = None
    activity_since: datetime | None = None
    last_report: datetime | None = None
    #: Only while `activity == "walk"`.
    walk_distance: int | float | None = None
    next_update: datetime | None = None
    area_name: str | None = None
    place_name: str | None = None
    home_location: LocationPoint | None = None
    #: The walk route, from `OngoingWalk.positions`. Bounded so an
    #: unexpectedly long activity cannot grow the page forever.
    positions: tuple[LocationPoint, ...] = ()
    #: Where she is while resting, from `pet_whereabouts`. Sourced from
    #: pytryfi's `... on OngoingRest { position }` and not yet measured on
    #: Kona's collar; `recorded_at` is the activity's `lastReportTimestamp`
    #: because the position itself carries no date.
    rest_position: LocationPoint | None = None


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


def profile_from(data: Any) -> PetProfile:
    """Name, breed, birthday and photo URL. Absent parts stay None."""
    pet = _dict(_dict(data).get("pet"))
    birthday: date | None = None
    y, m, d = (pet.get("yearOfBirth"), pet.get("monthOfBirth"), pet.get("dayOfBirth"))
    if all(type(v) is int for v in (y, m, d)):
        try:
            birthday = date(y, m, d)
        except ValueError:
            birthday = None
    photo = _dict(_dict(_dict(pet.get("photos")).get("first")).get("image"))
    url = photo.get("fullSize")
    breed = _dict(pet.get("breed")).get("name")
    return PetProfile(
        name=str(pet.get("name") or ""),
        breed=breed if isinstance(breed, str) and breed else None,
        birthday=birthday,
        photo_url=url if isinstance(url, str) and url.startswith("https://") else None,
    )


def status_from(data: Any) -> CollarStatus:
    """The collar and what she is doing, from `pet_status`."""
    pet = _dict(_dict(data).get("pet"))
    device = _dict(pet.get("device"))
    info = _dict(device.get("info"))
    conn = _dict(device.get("lastConnectionState"))
    kind = conn.get("__typename")
    params = _dict(device.get("operationParams"))
    led = _dict(device.get("ledColor"))
    ongoing = _dict(pet.get("ongoingActivity"))
    activity_kind = {"OngoingRest": "rest", "OngoingWalk": "walk"}.get(ongoing.get("__typename"))
    led_name = led.get("name")
    mode = params.get("mode")
    positions: list[LocationPoint] = []
    for raw in ongoing.get("positions") or []:
        item = _dict(raw)
        position = _dict(item.get("position"))
        latitude = _num(position.get("latitude"))
        longitude = _num(position.get("longitude"))
        accuracy = _num(item.get("errorRadius"))
        if latitude is None or longitude is None:
            continue
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
            continue
        positions.append(
            LocationPoint(
                latitude=float(latitude),
                longitude=float(longitude),
                recorded_at=_moment(item.get("date")),
                accuracy_m=accuracy if accuracy is not None and accuracy >= 0 else None,
            )
        )
    positions.sort(key=lambda point: point.recorded_at or datetime.min.replace(tzinfo=UTC))
    area_name = ongoing.get("areaName")
    place_name = _dict(ongoing.get("place")).get("name")
    home_position = _dict(_dict(pet.get("homeLocation")).get("position"))
    home_latitude = _num(home_position.get("latitude"))
    home_longitude = _num(home_position.get("longitude"))
    home_location = None
    if (
        home_latitude is not None
        and home_longitude is not None
        and -90 <= home_latitude <= 90
        and -180 <= home_longitude <= 180
    ):
        home_location = LocationPoint(float(home_latitude), float(home_longitude))
    return CollarStatus(
        battery_percent=_num(info.get("batteryPercent")),
        time_to_empty_s=_num(_dict(info.get("max77658Info")).get("timeToEmptyS")),
        on_base=(
            True if kind == "ConnectedToBase" else False if kind == "ConnectedToCellular" else None
        ),
        signal_percent=_num(conn.get("signalStrengthPercent")),
        led_on=params.get("ledEnabled") if isinstance(params.get("ledEnabled"), bool) else None,
        led_color=led_name if isinstance(led_name, str) and led_name else None,
        mode=mode if isinstance(mode, str) and mode else None,
        escaped=mode == "POST_ESCAPE_NOTIFICATION",
        lost=mode == "LOST_DOG",
        activity=activity_kind,
        activity_since=_moment(ongoing.get("start")),
        last_report=_moment(ongoing.get("lastReportTimestamp")),
        walk_distance=_num(ongoing.get("distance")) if activity_kind == "walk" else None,
        next_update=_moment(device.get("nextLocationUpdateExpectedBy")),
        area_name=area_name if isinstance(area_name, str) and area_name else None,
        place_name=place_name if isinstance(place_name, str) and place_name else None,
        home_location=home_location,
        positions=tuple(positions[-MAX_LOCATION_POINTS:]),
    )


def _coordinates(position: Any) -> tuple[float, float] | None:
    """A (latitude, longitude) pair that is on the planet, or None."""
    position = _dict(position)
    latitude = _num(position.get("latitude"))
    longitude = _num(position.get("longitude"))
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return float(latitude), float(longitude)


def rest_position_from(data: Any) -> LocationPoint | None:
    """Kona's resting position from `pet_whereabouts`, or None.

    None covers every honest case at once: she is walking (the document
    selects nothing on `OngoingWalk`), Fi sent no position, or the shape
    changed. The page then falls back to the home pin rather than guessing.
    """
    ongoing = _dict(_dict(_dict(data).get("pet")).get("ongoingActivity"))
    point = _coordinates(ongoing.get("position"))
    if point is None:
        return None
    return LocationPoint(
        latitude=point[0],
        longitude=point[1],
        recorded_at=_moment(ongoing.get("lastReportTimestamp")),
    )
