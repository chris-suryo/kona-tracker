"""The maps: which tiles to draw and how to name them, the live walk page,
and the Start walk button's label.
"""

from __future__ import annotations

from typing import Any

from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views.activity import activity_context
from kona_tracker.web.views.format import duration_parts, fix_age_label

#: Alidade Smooth, light and dark. `{r}` is Leaflet's retina placeholder and
#: is what makes these sharp on a phone; it resolves to "@2x" on a HiDPI
#: screen. Both are sent to the page and the browser picks, because the theme
#: is a client-side choice (localStorage) and the server cannot know it.
STADIA_LIGHT = "https://tiles.stadiamaps.com/tiles/alidade_smooth/{z}/{x}/{y}{r}.png"
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

    **Both themes are sent, and the browser picks.** This used to return one
    layer and it was always the dark one: `KONA_MAP_TILES=stadia` requested
    Alidade Smooth *Dark* whatever the page looked like, so choosing Light in
    Settings gave a light page sitting on a black map. The server cannot fix
    that by choosing better, because since 2026-09-15 the theme is a
    client-side choice living in `localStorage` -- the server does not know
    it and must not guess. So it hands over both and `map.js` resolves the
    theme the same way the CSS does.

    A separate function, and the only place the Stadia key is written into a
    URL, so there is exactly one line to audit -- now two, and they are next
    to each other on purpose.

    `dark` says whether the CSS filter that fakes a dark basemap should be
    suppressed: Alidade Smooth Dark already is dark, and filtering it darkens
    it twice. OSM has no dark raster, so both of its variants are the same
    light tiles and the filter does the work in a dark theme -- which is why
    `dark` is False on both and not a copy of the theme name.

    Falls back to OpenStreetMap rather than raising. A missing key is refused
    at settings load (`settings.py`), so by the time a request renders, the
    only way to be here without one is `map_tiles="osm"`.
    """
    if map_tiles == "stadia" and stadia_api_key:
        return {
            "light": {
                "url": STADIA_TILES_QUERY.format(base=STADIA_LIGHT, key=stadia_api_key),
                "attribution": STADIA_ATTRIBUTION,
                "maxZoom": 20,
                "dark": False,
            },
            "dark": {
                "url": STADIA_TILES_QUERY.format(base=STADIA_DARK, key=stadia_api_key),
                "attribution": STADIA_ATTRIBUTION,
                "maxZoom": 20,
                "dark": True,
            },
        }
    osm = {
        "url": OSM_TILES,
        "attribution": OSM_ATTRIBUTION,
        "maxZoom": 19,
        "dark": False,
    }
    return {"light": osm, "dark": dict(osm)}


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


def live_button(state: dict[str, Any] | None) -> dict[str, Any]:
    """What the "Start walk" control should say right now.

    `state` is `FiService.live_state()`, or None when no collar is
    configured, in which case there is nothing to start and the button is
    not offered at all rather than offered and dead.
    """
    if not state:
        return {"offered": False, "on": False, "label": None, "note": None}
    on = bool(state.get("live"))
    left = int(state.get("seconds_left") or 0)
    return {
        "offered": True,
        "on": on,
        "label": "Stop walk" if on else "Start walk",
        # Off, the button says what it does and needs no caption. On, the
        # one thing worth saying is that it turns itself off -- so nobody
        # leaves it running and flattens the collar. Our polling interval
        # was on screen here and is a fact about this server, not about
        # Kona; Chris's words were "I don't ever need to see that".
        "note": (f"Stops on its own in {max(1, round(left / 60))} min" if on else ""),
    }


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
