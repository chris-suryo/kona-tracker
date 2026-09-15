"""Turning an `FiSnapshot` into the exact strings the Activity page prints.

Formatting lives here rather than in the template so it can be tested, and
so the "we do not know this" cases are decided once in Python instead of
scattered through Jinja conditionals. Anything Fi did not return comes back
as `None`, and the template renders the muted dash for it.

The package split by page in 2026-09: `format` is shared by everything,
`walks` and `history` build on it, `activity` on those, `map` on `activity`.
Every name is re-exported here so `from kona_tracker.web.views import X`
keeps working, private helpers included -- the tests reach for `_hhmm`.
"""

from __future__ import annotations

from kona_tracker.web.views.activity import (
    CONNECTION_CURRENT_SECONDS,
    activity_context,
    activity_json,
    connection_label,
    last_night,
    overnight_json,
    overnight_labels,
    preview_activity_context,
)
from kona_tracker.web.views.format import (
    DIAL_SCALE_HOURS,
    DISTANCE_NOTE,
    REST_NOTE,
    TRACK,
    _age_seconds,
    _clock,
    _count,
    _day,
    _hhmm,
    _hour_range,
    _location_label,
    _minutes,
    _since,
    _span,
    age_label,
    dial_offset,
    distance_label,
    duration_parts,
    fix_age_label,
    kona_zone,
    outdoor_distance,
    scale_label,
    step_ring,
)
from kona_tracker.web.views.history import (
    CHART_HEIGHT,
    CHART_WIDTH,
    HOUR_REST_MAX_MIN,
    HOUR_STEPS_FLOOR,
    REST_CHART_FLOOR_MIN,
    hourly_buckets,
    hourly_context,
    hourly_json,
    rest_history_context,
    steps_context,
)
from kona_tracker.web.views.map import (
    MAP_TITLES,
    OSM_ATTRIBUTION,
    OSM_TILES,
    STADIA_ATTRIBUTION,
    STADIA_DARK,
    STADIA_LIGHT,
    STADIA_TILES_QUERY,
    live_button,
    live_map_context,
    live_map_json,
    map_tile_config,
)
from kona_tracker.web.views.robot import (
    _ROBOT_REFUSALS,
    robot_refusal,
)
from kona_tracker.web.views.walks import (
    walk_context,
    walk_rows,
    walks_json,
)

__all__ = [
    "CHART_HEIGHT",
    "CHART_WIDTH",
    "CONNECTION_CURRENT_SECONDS",
    "DIAL_SCALE_HOURS",
    "DISTANCE_NOTE",
    "HOUR_REST_MAX_MIN",
    "HOUR_STEPS_FLOOR",
    "MAP_TITLES",
    "OSM_ATTRIBUTION",
    "OSM_TILES",
    "REST_CHART_FLOOR_MIN",
    "REST_NOTE",
    "STADIA_ATTRIBUTION",
    "STADIA_DARK",
    "STADIA_LIGHT",
    "STADIA_TILES_QUERY",
    "TRACK",
    "_ROBOT_REFUSALS",
    "_age_seconds",
    "_clock",
    "_count",
    "_day",
    "_hhmm",
    "_hour_range",
    "_location_label",
    "_minutes",
    "_since",
    "_span",
    "activity_context",
    "activity_json",
    "age_label",
    "connection_label",
    "dial_offset",
    "distance_label",
    "duration_parts",
    "fix_age_label",
    "hourly_buckets",
    "hourly_context",
    "hourly_json",
    "kona_zone",
    "last_night",
    "live_button",
    "live_map_context",
    "live_map_json",
    "map_tile_config",
    "outdoor_distance",
    "overnight_json",
    "overnight_labels",
    "preview_activity_context",
    "rest_history_context",
    "robot_refusal",
    "scale_label",
    "step_ring",
    "steps_context",
    "walk_context",
    "walk_rows",
    "walks_json",
]
