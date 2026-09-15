"""The collar: the Activity page and its refresh, the walk button, the maps,
Steps and Rest, one walk, the sample-data preview, her photo, and the JSON
the pages poll.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse

from kona_tracker.web.deps import AppDeps
from kona_tracker.web.history_preview import history_preview
from kona_tracker.web.views import (
    activity_context,
    activity_json,
    live_button,
    live_map_context,
    live_map_json,
    preview_activity_context,
    rest_history_context,
    steps_context,
    walk_context,
)

#: Fi ids as seen on Kona's account: 22 URL-safe characters. Generous on
#: length, strict on alphabet, because the value lands in a path.
WALK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def make_activity_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    templates, fi, tile_config, avatar_fetch = (
        deps.templates,
        deps.fi,
        deps.tile_config,
        deps.avatar_fetch,
    )

    # One photo, fetched once per URL. Fi rotates the link rarely; the
    # snapshot refresh decides when we look again.
    avatar_cache: dict[str, tuple[bytes, str]] = {}

    @router.get("/activity", response_class=HTMLResponse)
    def activity(request: Request, preview: bool = False, fresh: bool = False):
        # `fresh` is the pull-to-refresh gesture: ask Fi on this request,
        # within the floor FiService enforces, so the swap-in is current.
        snapshot = fi.snapshot(force=fresh) if fi and not preview else None
        context = (
            preview_activity_context()
            if preview
            else activity_context(snapshot, configured=fi is not None)
        )
        context["map_tiles"] = tile_config
        context["live"] = live_button(fi.live_state() if fi and not preview else None)
        return templates.TemplateResponse(request, "activity.html", context)

    @router.post("/live")
    def live_mode(on: str = Form("")):
        """Start or stop the fast cadence: the "Start walk" button.

        Fi decides a walk has begun two to three minutes after it has, which
        on a twenty-minute walk is most of the first mile spent at the
        resting cadence. The person holding the lead already knows, so let
        them say so. Auto-detect stays underneath for the walks nobody
        pressed a button for.
        """
        if fi is None:
            raise HTTPException(status_code=409, detail="No collar is configured.")
        wanted = on.strip().lower() in {"1", "true", "on", "yes", "start"}
        return fi.start_live() if wanted else fi.stop_live()

    @router.get("/live")
    def live_status():
        if fi is None:
            raise HTTPException(status_code=409, detail="No collar is configured.")
        return fi.live_state()

    @router.get("/map", response_class=HTMLResponse)
    def live_map(request: Request, fresh: bool = False):
        """The map, full screen, for watching a walk as it happens.

        Chris asked for it after the 2026-09-13 walk: the Activity card's
        map is a tile that cannot be enlarged, and on a walk the map is the
        whole page. It polls `/map.json` on its own clock rather than
        re-rendering Activity underneath it.
        """
        snapshot = fi.snapshot(force=fresh) if fi else None
        context = live_map_context(snapshot, configured=fi is not None)
        context["map_tiles"] = tile_config
        context["live"] = live_button(fi.live_state() if fi else None)
        return templates.TemplateResponse(request, "map_live.html", context)

    @router.get("/map.json")
    def live_map_feed():
        """Just the map's own facts, small enough to ask for every 10 s."""
        snapshot = fi.snapshot() if fi else None
        payload = live_map_json(snapshot, configured=fi is not None)
        payload["button"] = live_button(fi.live_state() if fi else None)
        return payload

    @router.get("/rest", response_class=HTMLResponse)
    def rest_history(
        request: Request,
        selected: int | None = Query(default=None, ge=0, le=60),
        hour: int | None = Query(default=None, ge=0, le=23),
    ):
        """Kona's real daily rest, one bar per day the collar has existed.

        Days, not hours: Fi reports a daily total of sleep and of naps and
        nothing finer, so that is what this draws. The sample page at
        /preview/rest keeps its hourly and interval sketches; this page has
        neither, on purpose.
        """
        snapshot = fi.snapshot() if fi else None
        context = rest_history_context(
            snapshot, configured=fi is not None, selected=selected, hour=hour
        )
        return templates.TemplateResponse(request, "rest_history.html", context)

    @router.get("/steps", response_class=HTMLResponse)
    def steps_today(request: Request, hour: int | None = Query(default=None, ge=0, le=23)):
        """Today's steps by the hour, from stepFeed(period: DAY) -- the Fi
        app's Day tab. Fi's own day total on top; the bars can lag it."""
        snapshot = fi.snapshot() if fi else None
        context = steps_context(snapshot, configured=fi is not None, hour=hour)
        return templates.TemplateResponse(request, "steps.html", context)

    @router.get("/walks/{walk_id}", response_class=HTMLResponse)
    def walk(request: Request, walk_id: str):
        """One walk from Fi's activity feed, with its route on the map.

        The id is one this app rendered into a link, so an id the current
        snapshot no longer holds is a plain 404: the feed keeps the newest
        dozen, and older walks fall off it. Anything that does not look like
        a Fi id is the same 404 before it reaches the snapshot.
        """
        if not WALK_ID.fullmatch(walk_id):
            raise HTTPException(status_code=404, detail="That walk is no longer in Fi's feed.")
        snapshot = fi.snapshot() if fi else None
        context = walk_context(snapshot, walk_id, configured=fi is not None)
        if context is None:
            raise HTTPException(status_code=404, detail="That walk is no longer in Fi's feed.")
        context["map_tiles"] = tile_config
        return templates.TemplateResponse(request, "walk.html", context)

    @router.get("/preview/{metric}", response_class=HTMLResponse)
    def preview_history(
        request: Request,
        metric: str,
        period: str = "day",
        day: int = Query(default=0, ge=0, le=6),
        selected: int | None = Query(default=None, ge=0, le=23),
    ):
        if metric not in {"steps", "rest"} or period not in {"day", "week"}:
            raise HTTPException(status_code=404)
        return templates.TemplateResponse(
            request, "history_preview.html", history_preview(metric, period, day, selected)
        )

    @router.get("/avatar.jpg")
    def avatar():
        """Her photo from the Fi app, proxied. 404 when there is none, so an
        <img onerror> falls back to the initial rather than a broken icon."""
        snapshot = fi.snapshot() if fi else None
        url = snapshot.profile.photo_url if snapshot and snapshot.profile else None
        if not url:
            return Response(status_code=404)
        if url not in avatar_cache:
            fetched = avatar_fetch(url)
            if fetched is None:
                return Response(status_code=404)
            avatar_cache.clear()  # never hold more than the current photo
            avatar_cache[url] = fetched
        body, ctype = avatar_cache[url]
        return Response(
            content=body,
            media_type=ctype,
            headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"},
        )

    @router.get("/activity.json")
    def activity_data():
        snapshot = fi.snapshot() if fi else None
        return activity_json(snapshot, configured=fi is not None)

    return router
