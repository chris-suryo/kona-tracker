"""The app, with fixtures, for capturing docs/screenshots/current-ui/.

Runs the REAL application -- real templates, real stylesheet, real JavaScript
-- against a stub Fi service, a fake camera and a stub robot gateway that
reports a healthy robot. Nothing above the data layer is mocked, so what the
browser draws is what a phone would draw. Port 8140.

Not imported by the app, and it never talks to Fi, a camera or a robot.
See docs/screenshots/README.md.
"""

import datetime as dt
import pathlib
import sys

# Runnable from anywhere, on any machine: the app lives next door, not at an
# absolute path somebody's laptop happens to share.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
import uvicorn

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    HourBucket,
    HourlyDay,
    LocationPoint,
    Overnight,
    PetProfile,
    RestDay,
    RestWindow,
    Walk,
)
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

U = dt.UTC
NOW = dt.datetime(2026, 9, 14, 16, 27, tzinfo=U)
PORT = 8140


def D(*a):
    return dt.datetime(*a, tzinfo=U)


BASE_LAT, BASE_LON = 42.3662, -71.1004
ROUTE = [
    (0.0000, 0.0000),
    (0.0006, 0.0004),
    (0.0012, 0.0011),
    (0.0018, 0.0021),
    (0.0021, 0.0033),
    (0.0019, 0.0046),
    (0.0012, 0.0055),
    (0.0003, 0.0058),
    (-0.0007, 0.0054),
    (-0.0014, 0.0044),
    (-0.0017, 0.0031),
    (-0.0015, 0.0018),
    (-0.0009, 0.0008),
    (-0.0003, 0.0002),
]
walk_path = tuple(LocationPoint(BASE_LAT + a, BASE_LON + b) for a, b in ROUTE)
live_positions = tuple(
    LocationPoint(
        BASE_LAT + a,
        BASE_LON + b,
        recorded_at=D(2026, 9, 14, 15, 20) + dt.timedelta(minutes=2 * i),
        accuracy_m=8 + (i % 3) * 4,
    )
    for i, (a, b) in enumerate(ROUTE)
)

hours = []
for h in range(24):
    if h < 7:
        hours.append(HourBucket(sleep_s=3600, nap_s=0, steps=0))
    elif h < 9:
        hours.append(HourBucket(sleep_s=0, nap_s=1450 if h == 8 else 0, steps=310 * (h - 6)))
    elif h <= 16:
        hours.append(
            HourBucket(
                sleep_s=0,
                nap_s=(1192 if h == 14 else 0),
                steps=[820, 1640, 2980, 1210, 640, 3120, 2440, 1860][h - 9],
            )
        )
    else:
        hours.append(HourBucket(sleep_s=None, nap_s=None, steps=None))
hourly = HourlyDay(
    start=D(2026, 9, 14, 4),
    hours=tuple(hours),
    steps_total=21050,
    rest_present=True,
    steps_present=True,
)

REST = [
    (dt.date(2026, 9, 8), 0, 13576),
    (dt.date(2026, 9, 9), 31210, 14880),
    (dt.date(2026, 9, 10), 29640, 18320),
    (dt.date(2026, 9, 11), 33410, 12055),
    (dt.date(2026, 9, 12), 27832, 19440),
    (dt.date(2026, 9, 13), 35513, 16527),
    (dt.date(2026, 9, 14), 0, 2642),
]
rest_days = []
for day, sleep, nap in REST:
    start = dt.datetime(day.year, day.month, day.day, 4, tzinfo=U)
    end = start + dt.timedelta(days=1) - dt.timedelta(seconds=1)
    win = RestWindow(start=start, end=end, sleep=sleep, nap=nap)
    in_prog = start <= NOW < end
    first = day == dt.date(2026, 9, 8)
    rest_days.append(
        RestDay(
            window=win,
            complete=not in_prog and not first,
            in_progress=in_prog,
            partial_first_day=first,
        )
    )

walks = (
    Walk(
        id="3f0WNDOsmKujNTHK3ByXXo",
        kind="walk",
        start=D(2026, 9, 14, 13, 25, 3),
        end=D(2026, 9, 14, 13, 46, 31),
        steps=3853,
        distance_m=1749,
        area_name="Danehy Park",
        path=walk_path,
    ),
    Walk(
        id="7kQ2ZmBpLr4TcVnWxYs1Ad",
        kind="walk",
        start=D(2026, 9, 14, 11, 2, 14),
        end=D(2026, 9, 14, 11, 34, 50),
        steps=5218,
        distance_m=2410,
        area_name=None,
        path=walk_path[:9],
    ),
    Walk(
        id="9LmRt3XbQn6WdKpZvHy8Ee",
        kind="travel",
        start=D(2026, 9, 14, 9, 12),
        end=D(2026, 9, 14, 9, 41),
        steps=0,
        distance_m=7320,
        area_name=None,
        path=(),
    ),
    Walk(
        id="2BcDeFgHiJkLmNoPqRsTuV",
        kind="walk",
        start=D(2026, 9, 14, 6, 48),
        end=D(2026, 9, 14, 7, 21),
        steps=4106,
        distance_m=1980,
        area_name="Home",
        path=walk_path[3:],
    ),
)

status = CollarStatus(
    battery_percent=68,
    time_to_empty_s=86400,
    on_base=False,
    connection_at=D(2026, 9, 14, 16, 25, 40),
    signal_percent=84,
    led_on=True,
    led_color="Kona Blue",
    mode="NORMAL",
    escaped=False,
    lost=False,
    activity="walk",
    activity_since=D(2026, 9, 14, 16, 5),
    last_report=D(2026, 9, 14, 16, 25, 40),
    walk_distance=878,
    next_update=D(2026, 9, 14, 16, 29),
    area_name="Home",
    home_location=LocationPoint(BASE_LAT, BASE_LON),
    positions=live_positions,
    rest_position=LocationPoint(BASE_LAT, BASE_LON, recorded_at=D(2026, 9, 14, 16, 25, 40)),
)

snap = FiSnapshot(
    fetched_at=NOW,
    pet_name="Kona",
    pet_id="konapet1",
    profile=PetProfile(
        name="Kona",
        breed="Labrador Retriever",
        birthday=dt.date(2021, 4, 18),
        timezone="America/New_York",
        # Never fetched: `stub_avatar` below answers for it. It is here so the
        # screenshots exercise the *photo* path -- the header avatar, the
        # profile picture and, since 2026-09-15, the map marker. Without it
        # every one of them silently falls back to the initial and a reviewer
        # is shown the empty state as though it were the normal one, which is
        # the exact trap `sonar_cm` set in this file once before.
        photo_url="https://example.invalid/kona.jpg",
    ),
    window=RestWindow(
        start=D(2026, 9, 13, 4), end=D(2026, 9, 14, 3, 59, 59), sleep=35513, nap=16527
    ),
    today=RestWindow(start=D(2026, 9, 14, 4), end=D(2026, 9, 15, 3, 59, 59), sleep=0, nap=2642),
    activity=ActivityStats(steps=21050, step_goal=28000, distance=6139),
    week=ActivityStats(steps=118420, step_goal=196000, distance=41220),
    status=status,
    data_start=dt.date(2026, 9, 8),
    rest_days=rest_days,
    walks=walks,
    overnight=Overnight(
        date=D(2026, 9, 13),
        sleep_seconds=35513,
        sleep_start=D(2026, 9, 14, 3, 20, 24),
        sleep_end=D(2026, 9, 14, 11, 4, 17),
        interruptions=(
            (D(2026, 9, 14, 6, 12), D(2026, 9, 14, 6, 31)),
            (D(2026, 9, 14, 9, 40), D(2026, 9, 14, 9, 52)),
        ),
    ),
    hourly=hourly,
    stale=False,
    problem=None,
)


class StubFi:
    _live = False

    def snapshot(self, force=False):
        return snap

    def peek(self):
        return snap

    def start_live(self):
        StubFi._live = True
        return self.live_state()

    def stop_live(self):
        StubFi._live = False
        return self.live_state()

    def live_state(self):
        return {
            "live": StubFi._live,
            "seconds_left": 7200 if StubFi._live else 0,
            "every_seconds": 20,
        }


class StubRobot:
    """A healthy robot, in the gateway's own telemetry shape.

    Copied key-for-key from turbopi's `GET /telemetry` (gateway/robot_gateway.py)
    rather than from memory -- the first draft of this said `sonar_cm`, which
    the real gateway has never sent, and the screenshot duly showed "Ahead
    unknown" as if the sensor were broken. A fixture that misses a key does not
    fail; it quietly renders the empty state and puts it in front of a reviewer
    as though it were the normal one.
    """

    def telemetry(self):
        return {
            "battery_v": 8.1,
            "sonar_mm": 1420,
            "driving": False,
            "demo": False,
            "last_command_age_ms": None,
            "low_battery": False,
            "battery_age_ms": 420,
            "demo_detection": True,
            "stop_owed": False,
            "sonar_guard_mm": 250,
            "max_duty": 55,
            "min_duty": 25,
            "pan_deg": None,
            "tilt_deg": None,
            "sonar_usable": True,
        }

    def drive(self, vx, vy, omega):
        return {"ok": True}

    def stop(self):
        return {"ok": True}

    # `look_at`, which is what the gateway client calls. This was `look`, so
    # /robot/look answered 502 against the audit server and nobody noticed,
    # because no screenshot moves the camera.
    def look_at(self, pan_deg=None, tilt_deg=None, move_ms=None):
        return {"ok": True}

    # The lights, remembering what they were told -- the real gateway does,
    # and a stub that always answered the same thing would have hidden the
    # draw-from-the-answer rule rather than exercised it.
    _led = {"on": True, "r": 120, "g": 220, "b": 90}

    def led(self):
        return dict(self._led)

    def set_led(self, on, r=0, g=0, b=0):
        StubRobot._led = {"on": bool(on), "r": int(r), "g": int(g), "b": int(b)}
        return {"ok": True}

    def stop_quietly(self):
        pass

    def close(self):
        pass


def stub_avatar(url: str):
    """Her photo, without reaching Fi's CDN. A flat green square: the point of
    the screenshots is where the photo sits and what shape it is cropped to,
    not what she looks like."""
    import io  # noqa: PLC0415 - script-only
    import struct  # noqa: PLC0415
    import zlib  # noqa: PLC0415

    size = 96
    raw = b"".join(b"\x00" + bytes([0x35, 0x6B, 0x3C] * size) for _ in range(size))

    def chunk(tag: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body))

    png = io.BytesIO()
    png.write(b"\x89PNG\r\n\x1a\n")
    png.write(chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)))
    png.write(chunk(b"IDAT", zlib.compress(raw)))
    png.write(chunk(b"IEND", b""))
    return png.getvalue(), "image/png"


settings = Settings(
    passcode="4242",
    secret="s" * 20,
    robot_snapshot_url="http://127.0.0.1:9/snap",  # never fetched: stub source below
    robot_control_url="http://127.0.0.1:9031",
    robot_token="t" * 20,
    robot_name="Rover",
    # The sample-data pages are part of the audit set.
    preview_enabled=True,
    # The Stadia basemap, with a key that is not one. Tile requests never leave
    # this machine during a capture -- the capture script fulfils them -- and
    # the point is to exercise the light/dark basemap *choice* that landed on
    # 2026-09-15. Left on `osm` this path was never rendered at all, which is
    # how a bug that only exists under KONA_MAP_TILES=stadia reached a phone.
    map_tiles="stadia",
    stadia_api_key="NOT-A-REAL-KEY",
)
app = create_app(
    settings,
    source_factory=lambda: FakeSource(fps=30),
    fi_service=StubFi(),
    robot_source_factory=lambda: FakeSource(fps=10),
    robot_gateway=StubRobot(),
    avatar_fetch=stub_avatar,
)
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")
