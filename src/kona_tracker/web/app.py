"""FastAPI app: passcode gate + Camera tab (live MJPEG) + Activity from the Fi collar."""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
)
from fastapi.responses import (
    HTMLResponse,
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
from kona_tracker.web.history_preview import history_preview
from kona_tracker.web.logs import attach_file_logging, detach_file_logging
from kona_tracker.web.routes.auth import make_auth_router
from kona_tracker.web.routes.camera import make_camera_router
from kona_tracker.web.routes.robot import make_robot_router
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import (
    activity_context,
    activity_json,
    camera_health,
    live_button,
    live_map_context,
    live_map_json,
    map_tile_config,
    preview_activity_context,
    rest_history_context,
    steps_context,
    walk_context,
)

HERE = Path(__file__).parent
PUBLIC_PATHS = {"/login", "/healthz"}

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
#: tile host, a decision already recorded in docs/handoff.md;
#: `Referrer-Policy: no-referrer` means it learns a tile area and nothing
#: else, and map.js deliberately does NOT opt tile images back into sending an
#: origin: an element-level referrerpolicy overrides this header, which would
#: hand the tile host this deployment's hostname -- a tunnel URL included --
#: on the default OSM path as well as the Stadia one. `tiles.stadiamaps.com`
#: is the same bargain as OSM's host for the optional Alidade Smooth Dark
#: basemap, off unless `KONA_MAP_TILES=stadia`; naming both costs nothing
#: while only one can be configured at a time.
#: No HSTS: the LAN address is plain http on purpose.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; "
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


#: Fi ids as seen on Kona's account: 22 URL-safe characters. Generous on
#: length, strict on alphabet, because the value lands in a path.
WALK_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

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

    @app.get("/activity", response_class=HTMLResponse)
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

    @app.post("/live")
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

    @app.get("/live")
    def live_status():
        if fi is None:
            raise HTTPException(status_code=409, detail="No collar is configured.")
        return fi.live_state()

    @app.get("/map", response_class=HTMLResponse)
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

    @app.get("/map.json")
    def live_map_feed():
        """Just the map's own facts, small enough to ask for every 10 s."""
        snapshot = fi.snapshot() if fi else None
        payload = live_map_json(snapshot, configured=fi is not None)
        payload["button"] = live_button(fi.live_state() if fi else None)
        return payload

    @app.get("/rest", response_class=HTMLResponse)
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

    @app.get("/steps", response_class=HTMLResponse)
    def steps_today(request: Request, hour: int | None = Query(default=None, ge=0, le=23)):
        """Today's steps by the hour, from stepFeed(period: DAY) -- the Fi
        app's Day tab. Fi's own day total on top; the bars can lag it."""
        snapshot = fi.snapshot() if fi else None
        context = steps_context(snapshot, configured=fi is not None, hour=hour)
        return templates.TemplateResponse(request, "steps.html", context)

    @app.get("/walks/{walk_id}", response_class=HTMLResponse)
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

    @app.get("/preview/{metric}", response_class=HTMLResponse)
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

    @app.get("/settings", response_class=HTMLResponse)
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

    return app
