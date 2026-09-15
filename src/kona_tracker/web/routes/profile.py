"""The Settings page."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from kona_tracker.web.deps import AppDeps
from kona_tracker.web.views import activity_context, camera_health


def make_profile_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    settings, templates, hub, robot_hub, fi, build = (
        deps.settings,
        deps.templates,
        deps.hub,
        deps.robot_hub,
        deps.fi,
        deps.build,
    )

    @router.get("/settings", response_class=HTMLResponse)
    def profile_settings(request: Request, from_preview: bool = False):
        snapshot = fi.snapshot() if fi else None
        context = activity_context(snapshot, configured=fi is not None)
        # Not a tab. With `tab` set the header drew the Activity/Camera
        # toggle with neither selected, which read as broken, plus a second
        # avatar over the hero's. This page is reached from the avatar and
        # left by its own back link, so it carries no header at all.
        context["tab"] = None
        # The same statistics camera-doctor reads, so a wedged USB device
        # can be diagnosed from a phone instead of at the machine.
        house_kind = "rtsp" if settings.camera_source == "rtsp" else "usb"
        context["camera"] = camera_health(hub.status(), kind=house_kind)
        context["camera_description"] = settings.camera_description()
        # The robot is a second camera and gets its own rows, in its own
        # words; None when there is no robot and the section is not drawn.
        context["robot"] = (
            camera_health(robot_hub.status(), kind="robot") if robot_hub is not None else None
        )
        context["robot_name"] = settings.robot_name
        context["from_preview"] = from_preview
        context["build"] = build.label
        return templates.TemplateResponse(request, "settings.html", context)

    return router
