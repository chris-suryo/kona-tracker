"""FastAPI app: passcode gate + Camera tab (live MJPEG) + Activity from the Fi collar."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kona_tracker.camera.control import CameraControl, ControlUnsupported, FakeControl, NoControl
from kona_tracker.camera.hub import BOUNDARY, CameraHub
from kona_tracker.camera.source import FakeSource, FrameSource, OpenCVSource, RtspSource
from kona_tracker.fi.service import FiService
from kona_tracker.web.auth import COOKIE_NAME, Lockout, PasscodeAuth
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import activity_context, activity_json

HERE = Path(__file__).parent
PUBLIC_PATHS = {"/login", "/healthz"}

#: Kona's photo is a few hundred KB; anything bigger is not a photo.
AVATAR_MAX_BYTES = 5 * 1024 * 1024
#: Raster only. SVG is an image type that can carry script, and this is
#: served from our own origin.
AVATAR_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})

AvatarFetch = Callable[[str], tuple[bytes, str] | None]


def fetch_avatar(url: str) -> tuple[bytes, str] | None:
    """Fetch the profile photo from Fi's CDN, or None if it is not an image.

    The URL comes from Fi's own response, never from a request, and it is
    still held to https -- on the *final* hop too, since httpx follows a
    redirect to plain http without complaint -- and to a raster image type.
    A dead or expiring link returns None and the page shows the initial.
    """
    import httpx

    if not url.startswith("https://"):
        return None
    try:
        resp = httpx.get(url, timeout=10.0, follow_redirects=True)
    except httpx.HTTPError:
        return None
    if resp.url.scheme != "https":
        return None
    ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    if not resp.is_success or ctype not in AVATAR_TYPES:
        return None
    if len(resp.content) > AVATAR_MAX_BYTES:
        return None
    return resp.content, ctype


def default_control(s: Settings) -> CameraControl:
    """The thing that drives the camera, as opposed to reading from it.

    Only the simulated camera can be driven today; TapoControl lands with
    the pan/tilt hardware. A camera we cannot drive gets NoControl, which
    refuses loudly rather than no-opping.
    """
    caps = s.capabilities()
    if s.camera_source == "fake":
        return FakeControl(caps)
    return NoControl(caps)


def default_fi_service(s: Settings) -> FiService | None:
    """None when FI_EMAIL/FI_PASSWORD are absent.

    An unconfigured collar is a state the page explains, not an error: the
    Camera tab still works, and the Activity tab says which two lines are
    missing from `.env` instead of showing a broken dial.
    """
    if not s.fi_configured:
        return None
    return FiService(
        s.fi_email,
        s.fi_password,
        s.fi_refresh_seconds,
        data_start=s.fi_data_start,
    )


def default_source_factory(s: Settings, control: CameraControl | None = None):
    if s.camera_source == "fake":
        steerable = control if (control and control.capabilities.ptz) else None
        return lambda: FakeSource(fps=s.camera_fps, control=steerable)
    if s.camera_source == "rtsp":
        return lambda: RtspSource(s.rtsp_url, s.rtsp_user, s.rtsp_password, s.rtsp_transport)
    return lambda: OpenCVSource(s.camera_index, s.camera_width, s.camera_height, s.camera_fps)


def create_app(
    settings: Settings,
    source_factory: Callable[[], FrameSource] | None = None,
    control: CameraControl | None = None,
    fi_service: FiService | None = None,
    avatar_fetch: AvatarFetch = fetch_avatar,
):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        hub.stop()  # release the webcam on shutdown

    app = FastAPI(
        title="kona-tracker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")

    auth = PasscodeAuth(
        settings.passcode,
        settings.secret,
        settings.cookie_max_age,
        Lockout(settings.lockout_attempts, settings.lockout_seconds),
    )
    control = control if control is not None else default_control(settings)
    capabilities = control.capabilities
    hub = CameraHub(
        source_factory or default_source_factory(settings, control),
        max_fps=settings.camera_fps,
        stale_after=settings.stale_seconds,
        hang_after=settings.hang_seconds,
    )
    fi = fi_service if fi_service is not None else default_fi_service(settings)
    app.state.hub = hub
    app.state.auth = auth
    app.state.control = control
    app.state.fi = fi
    # One photo, fetched once per URL. Fi rotates the link rarely; the
    # snapshot refresh decides when we look again.
    avatar_cache: dict[str, tuple[bytes, str]] = {}

    def authed(request: Request) -> bool:
        return auth.valid_cookie(request.cookies.get(COOKIE_NAME))

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static/") or authed(request):
            return await call_next(request)
        # An <img> can't follow a redirect to a login page; give it a 401.
        if path.startswith(("/stream", "/snapshot", "/avatar")):
            return Response(status_code=401)
        return RedirectResponse("/login", status_code=303)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request):
        if authed(request):
            return RedirectResponse("/camera", status_code=303)
        return templates.TemplateResponse(request, "login.html", {"error": None})

    @app.post("/login", response_class=HTMLResponse)
    def login(request: Request, passcode: str = Form("")):
        key = request.client.host if request.client else "?"
        if auth.lockout.blocked(key):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Too many tries. Wait a moment."},
                status_code=429,
            )
        if not auth.check(passcode):
            auth.lockout.fail(key)
            return templates.TemplateResponse(
                request, "login.html", {"error": "That's not it."}, status_code=401
            )
        auth.lockout.clear(key)
        resp = RedirectResponse("/camera", status_code=303)
        resp.set_cookie(
            COOKIE_NAME,
            auth.issue_cookie(),
            max_age=settings.cookie_max_age,
            httponly=True,
            samesite="lax",
        )
        return resp

    @app.post("/logout")
    def logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE_NAME)
        return resp

    @app.get("/")
    def root():
        return RedirectResponse("/camera", status_code=303)

    @app.get("/camera", response_class=HTMLResponse)
    def camera(request: Request):
        return templates.TemplateResponse(
            request, "camera.html", {"tab": "camera", "caps": capabilities}
        )

    @app.get("/activity", response_class=HTMLResponse)
    def activity(request: Request):
        snapshot = fi.snapshot() if fi else None
        return templates.TemplateResponse(
            request, "activity.html", activity_context(snapshot, configured=fi is not None)
        )

    @app.get("/avatar.jpg")
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

    @app.get("/activity.json")
    def activity_data():
        snapshot = fi.snapshot() if fi else None
        return activity_json(snapshot, configured=fi is not None)

    @app.get("/stream.mjpg")
    def stream(frames: int | None = None):
        # `frames` caps the stream (curl debugging, tests); browsers omit it.
        return StreamingResponse(
            hub.mjpeg(max_frames=frames),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    @app.get("/snapshot.jpg")
    def snapshot():
        # Always an image (an <img> fallback can show it); the header is the truth.
        frame, state = hub.snapshot()
        return Response(
            content=frame,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store", "X-Kona-State": state},
        )

    @app.get("/status.json")
    def status():
        pan, tilt = control.position()
        return {
            **hub.status(),
            "capabilities": capabilities.as_dict(),
            "position": {"pan": round(pan, 3), "tilt": round(tilt, 3)},
        }

    @app.post("/control/move")
    def control_move(pan: float = Form(0.0), tilt: float = Form(0.0)):
        # A camera that cannot pan must say so; a dead button is worse than
        # an honest error.
        try:
            new_pan, new_tilt = control.move(pan=pan, tilt=tilt)
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"pan": round(new_pan, 3), "tilt": round(new_tilt, 3)}

    @app.post("/control/preset")
    def control_preset(number: int = Form(...)):
        try:
            new_pan, new_tilt = control.goto_preset(number)
        except ControlUnsupported as e:
            return JSONResponse({"error": str(e)}, status_code=409)
        return {"pan": round(new_pan, 3), "tilt": round(new_tilt, 3)}

    return app
