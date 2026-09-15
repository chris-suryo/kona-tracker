"""What every router is built from.

`create_app()` builds the hubs, the gateway, the Fi service and the
templates once, then hands them to one router factory per domain through
this object. A frozen dataclass rather than `request.app.state` or
`Depends()`, on purpose: it keeps every handler a plain closure over plain
names, exactly as they were written when they all lived inside one
function, and it means no routes module ever imports `kona_tracker.web.app`
-- which would be a cycle, since app.py imports the routes.

`HOME` lives here rather than in app.py for the same reason: the login
routes redirect to it, and app.py imports the login routes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi.templating import Jinja2Templates

from kona_tracker.camera.capabilities import Capabilities
from kona_tracker.camera.control import CameraControl
from kona_tracker.camera.hub import CameraHub
from kona_tracker.fi.service import FiService
from kona_tracker.robot.gateway import RobotGateway
from kona_tracker.web.auth import PasscodeAuth
from kona_tracker.web.build import Build
from kona_tracker.web.settings import Settings

#: Where the app opens: signing in, "/", and the home-screen icon all land
#: here. It was "/camera" from the days when the camera was the only thing
#: this app did. Activity is what you open it for -- the camera is one tap
#: away and the dog is not.
HOME = "/activity"

AvatarFetch = Callable[[str], tuple[bytes, str] | None]


@dataclass(frozen=True)
class AppDeps:
    settings: Settings
    templates: Jinja2Templates
    auth: PasscodeAuth
    hub: CameraHub
    #: None without KONA_ROBOT_SNAPSHOT_URL; the robot tab 404s.
    robot_hub: CameraHub | None
    #: None without a control URL and token; every drive route 404s.
    robot: RobotGateway | None
    #: None without FI_EMAIL/FI_PASSWORD; the pages say what is missing.
    fi: FiService | None
    control: CameraControl
    capabilities: Capabilities
    #: Built once; the only place the Stadia key is written into a URL.
    tile_config: dict[str, Any]
    build: Build
    avatar_fetch: AvatarFetch
    #: Shared by /healthz and the outbound heartbeat so they cannot disagree.
    health_summary: Callable[[], dict[str, Any]]
