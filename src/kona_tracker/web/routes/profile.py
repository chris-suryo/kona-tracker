"""The Settings page."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from kona_tracker.web.deps import AppDeps
from kona_tracker.web.views import activity_context
from kona_tracker.web.views.system import collar_rows, system_rows


def make_profile_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    settings, templates, fi, build = deps.settings, deps.templates, deps.fi, deps.build
    health_summary = deps.health_summary

    @router.get("/settings", response_class=HTMLResponse)
    def profile_settings(request: Request, from_preview: bool = False):
        # `peek`, not `snapshot`: opening Settings used to be one more way
        # to make this server ask Fi. It shows the reading already held.
        snapshot = fi.peek() if fi else None
        context = activity_context(snapshot, configured=fi is not None)
        # Not a tab. With `tab` set the header drew the Activity/Camera
        # toggle with neither selected, which read as broken, plus a second
        # avatar over the hero's. This page is reached from the avatar and
        # left by its own back link, so it carries no header at all.
        context["tab"] = None
        context["from_preview"] = from_preview
        context["preview_enabled"] = settings.preview_enabled
        context["build"] = build.label
        state = request.app.state
        context["collar_rows"] = collar_rows(snapshot)
        context["system_rows"] = system_rows(
            health_summary(),
            fi.recorder_status() if fi else None,
            getattr(state, "heartbeat", None),
            getattr(state, "started_at", None),
            datetime.now(UTC),
        )
        return templates.TemplateResponse(request, "settings.html", context)

    return router
