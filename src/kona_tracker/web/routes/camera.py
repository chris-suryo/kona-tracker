"""The house camera: its page, the frame it serves one at a time, and the
Tapo switches behind /control/*. `hub_for` is here because the frame routes
are the only ones that take a `cam=` query.
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from kona_tracker.camera.control import ControlUnsupported
from kona_tracker.camera.hub import BOUNDARY, MAX_STREAMS, CameraHub
from kona_tracker.web.deps import AppDeps


def make_camera_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    settings, templates, hub, robot_hub, control, capabilities = (
        deps.settings,
        deps.templates,
        deps.hub,
        deps.robot_hub,
        deps.control,
        deps.capabilities,
    )

    def hub_for(cam: str) -> CameraHub:
        """The hub a `cam=` query names. `house` is the default and what
        every pre-robot URL means; `robot` exists only when configured.
        Anything else is a 404. The value is compared, never used: it
        reaches no path, no filename and no log line."""
        if cam == "house":
            return hub
        if cam == "robot" and robot_hub is not None:
            return robot_hub
        raise HTTPException(status_code=404, detail="no such camera")

    @router.get("/camera", response_class=HTMLResponse)
    def camera(request: Request):
        return templates.TemplateResponse(
            request,
            "camera.html",
            # `source` lets poll.js pick advice for the kind of camera it
            # is: "unplug it" is right for a webcam and nonsense for one on
            # the Wi-Fi.
            {"tab": "camera", "caps": capabilities, "source": settings.camera_source},
        )

    @router.get("/stream.mjpg")
    def stream(frames: int | None = None):
        # `frames` caps the stream (curl debugging, tests); browsers omit it.
        # The phone no longer uses this; it polls /snapshot.jpg. What remains
        # is for curl and a desktop, and it is capped so abandoned streams can
        # never again pile up silently until nothing can start. The check
        # lives here and not in the generator because by the time the
        # generator runs, the 200 and the multipart headers are already on
        # the wire. The check-then-act gap is real and benign for a household.
        if hub.status()["streams"] >= MAX_STREAMS:
            return Response(
                content=f"{MAX_STREAMS} streams are already open; poll /snapshot.jpg instead.\n",
                status_code=503,
                media_type="text/plain",
                headers={"Retry-After": "5"},
            )
        return StreamingResponse(
            hub.mjpeg(max_frames=frames),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @router.get("/snapshot.jpg")
    def snapshot(after: int = Query(0, ge=0), cam: str = Query("house")):
        """One frame, and the truth about it in the same response.

        `after` is the seq the caller last received. The hub holds the
        request until a newer frame exists, for at most `stale_after`, so a
        polling page costs one request per frame and a slow link skips
        frames rather than queueing them. `after=0` returns the current
        frame at once; that is the capture button and a page's first poll.

        The body is always an image so an <img> can show it; the headers are
        the truth. `X-Kona-State: live` means a real frame. The placeholder
        never travels as live, because the hub waits at least `stale_after`
        before giving up and a frame older than that is stale by definition.
        `X-Kona-Error` is the hub's last error *kind*, a short token, never
        the message, which can carry a redacted camera host.

        `cam` picks the camera; a query rather than a path prefix because
        the gate's bare-401 rule for an <img> is keyed on the path.
        """
        snap = hub_for(cam).snapshot(after_seq=after)
        headers = {
            "Cache-Control": "no-store",
            "X-Kona-State": snap.state,
            "X-Kona-Seq": str(snap.seq),
            "X-Kona-Error": snap.error_kind or "",
        }
        if snap.frame_age is not None:
            headers["X-Kona-Frame-Age"] = f"{snap.frame_age:.2f}"
        return Response(content=snap.jpeg, media_type="image/jpeg", headers=headers)

    @router.get("/status.json")
    def status(cam: str = Query("house")):
        if cam != "house":
            # The robot has no control driver in this phase: its status is
            # the hub's alone, with none of the house camera's numbers.
            return hub_for(cam).status()
        pan, tilt = control.position()
        return {
            **hub.status(),
            "capabilities": capabilities.as_dict(),
            "position": {"pan": round(pan, 3), "tilt": round(tilt, 3)},
        }

    @router.get("/control/settings")
    def control_settings():
        """The camera's switches as they are now. 409 when there are none,
        502 when the camera did not answer -- the page says which."""
        try:
            state = control.settings()
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except Exception as e:  # TapoError and anything the driver let through
            return JSONResponse({"error": str(e)[:200]}, status_code=502)
        if not state:
            return JSONResponse(
                {"error": "this camera has no settings that can be changed from here"},
                status_code=409,
            )
        return {"settings": state}

    @router.post("/control/setting")
    def control_setting(name: str = Form(...), value: str = Form(...)):
        try:
            return {"settings": control.apply(name, value)}
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        except Exception as e:
            return JSONResponse({"error": str(e)[:200]}, status_code=502)

    @router.post("/control/move")
    def control_move(pan: float = Form(0.0), tilt: float = Form(0.0)):
        # A camera that cannot pan must say so; a dead button is worse than
        # an honest error.
        try:
            new_pan, new_tilt = control.move(pan=pan, tilt=tilt)
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"pan": round(new_pan, 3), "tilt": round(new_tilt, 3)}

    @router.post("/control/preset")
    def control_preset(number: int = Form(...)):
        try:
            new_pan, new_tilt = control.goto_preset(number)
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"pan": round(new_pan, 3), "tilt": round(new_tilt, 3)}

    return router
