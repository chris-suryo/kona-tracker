"""FastAPI app: passcode gate + Camera tab (live MJPEG) + Activity placeholder."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kona_tracker.camera.hub import BOUNDARY, CameraHub
from kona_tracker.camera.source import FakeSource, FrameSource, OpenCVSource, RtspSource
from kona_tracker.web.auth import COOKIE_NAME, Lockout, PasscodeAuth
from kona_tracker.web.settings import Settings

HERE = Path(__file__).parent
PUBLIC_PATHS = {"/login", "/healthz"}


def default_source_factory(s: Settings) -> Callable[[], FrameSource]:
    if s.camera_source == "fake":
        return lambda: FakeSource(fps=s.camera_fps)
    if s.camera_source == "rtsp":
        return lambda: RtspSource(s.rtsp_url, s.rtsp_user, s.rtsp_password, s.rtsp_transport)
    return lambda: OpenCVSource(s.camera_index, s.camera_width, s.camera_height, s.camera_fps)


def create_app(settings: Settings, source_factory: Callable[[], FrameSource] | None = None):
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
    hub = CameraHub(
        source_factory or default_source_factory(settings),
        max_fps=settings.camera_fps,
        stale_after=settings.stale_seconds,
        hang_after=settings.hang_seconds,
    )
    app.state.hub = hub
    app.state.auth = auth

    def authed(request: Request) -> bool:
        return auth.valid_cookie(request.cookies.get(COOKIE_NAME))

    @app.middleware("http")
    async def gate(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static/") or authed(request):
            return await call_next(request)
        # An <img> can't follow a redirect to a login page; give it a 401.
        if path.startswith("/stream") or path.startswith("/snapshot"):
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
        return templates.TemplateResponse(request, "camera.html", {"tab": "camera"})

    @app.get("/activity", response_class=HTMLResponse)
    def activity(request: Request):
        return templates.TemplateResponse(request, "activity.html", {"tab": "activity"})

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
        return hub.status()

    return app
