"""One walk, and the list of today's: the rows under the Activity card and
the /walks/{id} page.
"""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any

from kona_tracker.fi.parse import Walk
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views.format import (
    _clock,
    _count,
    _day,
    _hhmm,
    _span,
    distance_label,
    duration_parts,
    kona_zone,
)


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
        "as_of": _hhmm(fetched_local),
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
