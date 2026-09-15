"""Building the app: settings in, a FastAPI instance out.

`create_app()` owns everything that exists once per process -- the security
headers, the passcode gate, the camera hubs, the robot gateway, the Fi
service, the lifespan that stops them -- and hands it to the routers in
`routes/` through `deps.AppDeps`. The handlers themselves live there, one
module per domain; the strings they render are built in `views/`.
"""

from __future__ import annotations

import logging
import mimetypes
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    Request,
    Response,
)
from fastapi.responses import (
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from kona_tracker.camera.control import CameraControl, FakeControl, NoControl
from kona_tracker.camera.hub import CameraHub
from kona_tracker.camera.placeholder import ROBOT_OFF_JPEG
from kona_tracker.camera.source import (
    FakeSource,
    FrameSource,
    OpenCVSource,
    RtspSource,
    SnapshotSource,
)
from kona_tracker.fi.service import FiService
from kona_tracker.robot.gateway import (
    RobotGateway,
)
from kona_tracker.store import Recorder
from kona_tracker.web.assets import asset_url, asset_versions
from kona_tracker.web.auth import COOKIE_NAME, Lockout, PasscodeAuth
from kona_tracker.web.awake import allow_sleep, keep_awake
from kona_tracker.web.build import read_build
from kona_tracker.web.deps import AppDeps, AvatarFetch
from kona_tracker.web.heartbeat import Heartbeat
from kona_tracker.web.logs import attach_file_logging, detach_file_logging
from kona_tracker.web.routes.activity import make_activity_router
from kona_tracker.web.routes.auth import make_auth_router
from kona_tracker.web.routes.camera import make_camera_router
from kona_tracker.web.routes.profile import make_profile_router
from kona_tracker.web.routes.robot import make_robot_router
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import map_tile_config

HERE = Path(__file__).parent
PUBLIC_PATHS = {"/login", "/healthz"}

#: Python's own mimetypes table has no `.woff2`. It resolves on this machine
#: only because the image happens to ship /etc/mime.types, which Windows --
#: where this app actually runs -- does not. Left alone, Starlette serves the
#: vendored font as `application/octet-stream`, and every response here
#: carries `X-Content-Type-Options: nosniff`: exactly the pair a browser is
#: entitled to refuse a font on. It would work on the machine that vendored
#: the font and fail on the machine that serves it, which is the worst shape
#: a bug can have. Module level, so the registration happens once and lands
#: on top of whatever the platform's own table says.
mimetypes.add_type("font/woff2", ".woff2")

#: Sent with every response, static files and 401s included. Read against the
#: threat that matters once there is a public URL: a page with a live camera
#: on it. Nothing here is a nonce -- every script the pages use is a file
#: under /static, so `script-src 'self'` is enough and the JS stays cacheable.
#: `data:` is for Leaflet, which points aborted tile images at a base64 GIF.
#: `blob:` is for the Camera tab, which fetches each frame and hands the
#: <img> an object URL; without it the picture is a silent black rectangle.
#: A blob URL can only be minted by script already running in the page, and
#: with script-src 'self' and no inline that means only /static/*.js, so it
#: concedes nothing `data:` did not already. `img-src` names OpenStreetMap's
#: tile host, a decision already recorded in docs/history/handoff.md;
#: `Referrer-Policy: no-referrer` means it learns a tile area and nothing
#: else, and map.js deliberately does NOT opt tile images back into sending an
#: origin: an element-level referrerpolicy overrides this header, which would
#: hand the tile host this deployment's hostname -- a tunnel URL included --
#: on the default OSM path as well as the Stadia one. `tiles.stadiamaps.com`
#: is the same bargain as OSM's host for the optional Alidade Smooth Dark
#: basemap, off unless `KONA_MAP_TILES=stadia`; naming both costs nothing
#: while only one can be configured at a time.
#: `style-src` and `font-src` are `'self'` and nothing else because the
#: webfont is vendored under `static/fonts/`. Bricolage Grotesque used to
#: arrive as a stylesheet from one Google host naming files on another, which
#: put two third-party origins in this header, a render-blocking request on
#: every page load, and a third party in a position to learn which of these
#: pages get opened and from where. Note that `font-src` previously had no
#: `'self'` at all -- a directive replaces the `default-src` fallback rather
#: than extending it -- so a self-hosted font would have been blocked with
#: nothing but a console line on a phone nobody reads. That is the one
#: failure this change could have shipped silently; tests/test_web.py pins it.
#: No HSTS: the LAN address is plain http on purpose.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
        "img-src 'self' data: blob: https://tile.openstreetmap.org "
        "https://tiles.stadiamaps.com; connect-src 'self'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'; "
        "manifest-src 'self'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}

#: Kona's photo is a few hundred KB; anything bigger is not a photo.
AVATAR_MAX_BYTES = 5 * 1024 * 1024
#: Raster only. SVG is an image type that can carry script, and this is
#: served from our own origin.
AVATAR_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


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
    if (
        s.camera_source == "rtsp"
        and s.tapo_password
        and (caps.night_vision or caps.privacy or caps.led)
    ):
        host = urlsplit(s.rtsp_url).hostname
        if host:
            from kona_tracker.camera.tapo import TapoControl

            return TapoControl(
                host, s.tapo_user, s.tapo_password, caps, cloud_password=s.tapo_cloud_password
            )
    return NoControl(caps)


def default_fi_service(s: Settings) -> FiService | None:
    """None when FI_EMAIL/FI_PASSWORD are absent.

    An unconfigured collar is a state the page explains, not an error: the
    Camera tab still works, and the Activity tab says which two lines are
    missing from `.env` instead of showing a broken dial.
    """
    if not s.fi_configured:
        return None
    # Recording is opt-in via KONA_DB_PATH. Building the Recorder cannot fail
    # and does not touch the disk: it opens the file on the first refresh, so
    # a bad path costs a log line then rather than a server that will not
    # start. See docs/recording.md.
    recorder = Recorder(s.db_path) if s.db_path else None
    return FiService(
        s.fi_email,
        s.fi_password,
        s.fi_refresh_seconds,
        live_seconds=s.fi_live_seconds,
        live_max_seconds=s.fi_live_max_seconds,
        data_start=s.fi_data_start,
        recorder=recorder,
    )


def default_source_factory(s: Settings, control: CameraControl | None = None):
    if s.camera_source == "fake":
        steerable = control if (control and control.capabilities.ptz) else None
        return lambda: FakeSource(fps=s.camera_fps, control=steerable)
    if s.camera_source == "rtsp":
        return lambda: RtspSource(
            s.rtsp_url, s.rtsp_user, s.rtsp_password, s.rtsp_transport, max_width=s.camera_width
        )
    return lambda: OpenCVSource(s.camera_index, s.camera_width, s.camera_height, s.camera_fps)


log = logging.getLogger("kona_tracker.web")


def create_app(
    settings: Settings,
    source_factory: Callable[[], FrameSource] | None = None,
    control: CameraControl | None = None,
    fi_service: FiService | None = None,
    avatar_fetch: AvatarFetch = fetch_avatar,
    robot_source_factory: Callable[[], FrameSource] | None = None,
    robot_gateway: RobotGateway | None = None,
):
    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        log_handler = attach_file_logging(Path(settings.log_dir)) if settings.log_dir else None
        # The hold belongs to this thread and dies with the process, which is
        # the point: stopping the app gives the machine its power plan back.
        holding = keep_awake() if settings.keep_awake else False
        app.state.keeping_awake = holding
        beat = (
            Heartbeat(
                settings.heartbeat_url,
                lambda: app.state.health_summary(),
                settings.heartbeat_seconds,
            )
            if settings.heartbeat_url
            else None
        )
        app.state.heartbeat = beat
        if beat is not None:
            beat.start()
        if settings.keep_awake and not holding:
            # Never let a failed hold pass for a working one: the whole reason
            # to ask is so the page is reachable while nobody is at the PC.
            print(
                "KONA_KEEP_AWAKE is set but this machine would not hold sleep off "
                "(not Windows, or the request was refused). The app will still serve, "
                "but the PC may sleep and take the camera and tunnel with it.",
                file=sys.stderr,
            )
        try:
            yield
        finally:
            hub.stop()  # release the webcam on shutdown
            if robot_hub is not None:
                robot_hub.stop()
            if robot is not None:
                # The watchdog on the Pi would zero the motors half a second
                # after we stop refreshing anyway; this is the explicit half
                # of the contract, and it costs one request on the way out.
                robot.stop_quietly()
                robot.close()
            if beat is not None:
                beat.stop()
            if holding:
                allow_sleep()
            if log_handler is not None:
                detach_file_logging(log_handler)

    app = FastAPI(
        title="kona-tracker", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    templates = Jinja2Templates(directory=str(HERE / "templates"))
    app.mount("/static", StaticFiles(directory=str(HERE / "static")), name="static")
    # Every stylesheet and script URL carries a hash of its own bytes, so a
    # phone that cached one cannot serve it against newer HTML. See assets.py
    # for the day that cost us.
    versions = asset_versions(HERE / "static")
    templates.env.globals["asset"] = lambda name: asset_url(versions, name)
    # The header grows a Robot tab only when there is a robot to show. Set
    # once here rather than threaded through every page's context.
    templates.env.globals["robot_configured"] = settings.robot_configured
    # Read once here rather than per request: it shells out to git, and the
    # answer cannot change while the process is running.
    build = read_build()

    auth = PasscodeAuth(
        settings.passcode,
        settings.secret,
        settings.cookie_max_age,
        Lockout(settings.lockout_attempts, settings.lockout_seconds),
    )
    control = control if control is not None else default_control(settings)
    # Built once: it never changes at runtime and it is the only place the
    # Stadia key is written into a URL.
    tile_config = map_tile_config(settings.map_tiles, settings.stadia_api_key)
    capabilities = control.capabilities
    hub = CameraHub(
        source_factory or default_source_factory(settings, control),
        idle_stop_seconds=settings.camera_idle_seconds,
        reopen_cooldown_seconds=settings.camera_reopen_seconds,
        max_fps=settings.camera_fps,
        stale_after=settings.stale_seconds,
        hang_after=settings.hang_seconds,
    )
    # The robot is a second camera with its own hub: own reader thread, own
    # backoff (it is off more than on), own placeholder, and a lower frame
    # rate because every frame is one HTTP GET to the Pi. Built only when
    # KONA_ROBOT_SNAPSHOT_URL is set; with it blank nothing here changes.
    robot_hub: CameraHub | None = None
    if settings.robot_configured:
        robot_hub = CameraHub(
            robot_source_factory or (lambda: SnapshotSource(settings.robot_snapshot_url)),
            idle_stop_seconds=settings.camera_idle_seconds,
            reopen_cooldown_seconds=settings.camera_reopen_seconds,
            max_fps=settings.robot_fps,
            stale_after=settings.stale_seconds,
            hang_after=settings.hang_seconds,
            placeholder=ROBOT_OFF_JPEG,
            name="robot",
        )
    fi = fi_service if fi_service is not None else default_fi_service(settings)
    # Driving. Its own predicate, not `robot_configured`: until the Pi-side
    # safety gateway is installed the robot is watchable and not drivable,
    # and that is the normal state rather than a broken one.
    robot: RobotGateway | None = robot_gateway
    if robot is None and settings.robot_drive_configured:
        robot = RobotGateway(settings.robot_control_url, settings.robot_token)
    app.state.hub = hub
    app.state.robot_hub = robot_hub
    app.state.robot = robot
    app.state.auth = auth
    app.state.control = control
    app.state.fi = fi

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

    # Registered after `gate`, which makes it the outer layer: the headers
    # land on the login redirect, the 401 for an <img>, and /static too.
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    def health_summary() -> dict[str, Any]:
        """Is the process up, is the camera delivering, how old is the Fi
        reading. Deliberately nothing else -- no error text (it can carry a
        redacted camera host), no coordinates, and no Fi round trip, so a
        stranger cannot make us talk to Fi. Shared by the public /healthz and
        the outbound heartbeat so the two can never disagree."""
        camera = hub.status()
        snapshot = fi.peek() if fi else None
        age = (datetime.now(UTC) - snapshot.fetched_at).total_seconds() if snapshot else None
        return {
            "status": "ok",
            "camera": camera["state"],
            "camera_error": camera["last_error_kind"],
            "fi": "unconfigured"
            if fi is None
            else "pending"
            if snapshot is None
            else "stale"
            if snapshot.stale
            else "unavailable"
            if not snapshot.has_data
            else "partial"
            if snapshot.partial
            else "ok",
            "fi_age_s": None if age is None else round(age),
        }

    app.state.health_summary = health_summary

    deps = AppDeps(
        settings=settings,
        templates=templates,
        auth=auth,
        hub=hub,
        robot_hub=robot_hub,
        robot=robot,
        fi=fi,
        control=control,
        capabilities=capabilities,
        tile_config=tile_config,
        build=build,
        avatar_fetch=avatar_fetch,
        health_summary=health_summary,
    )
    app.include_router(make_auth_router(deps))
    app.include_router(make_camera_router(deps))
    app.include_router(make_robot_router(deps))
    app.include_router(make_activity_router(deps))
    app.include_router(make_profile_router(deps))

    return app
