"""Runtime settings from the environment (or a .env file). No host lock-in:
the same variables work on the Windows PC, the Pi, or a cloud box."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from kona_tracker.camera.capabilities import Capabilities, for_model
from kona_tracker.camera.redact import has_scheme, redact_url, split_credentials
from kona_tracker.cli_env import read_env_file

CAMERA_SOURCES = ("usb", "rtsp", "fake")

# Below this, warn that the passcode is too short to face the public internet.
MIN_SAFE_PASSCODE = 6


@dataclass(frozen=True, repr=False)
class Settings:
    passcode: str
    secret: str
    camera_source: str = "usb"  # usb | rtsp | fake
    camera_model: str = ""  # c120, c225, ... picks the capability set
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 15
    rtsp_url: str = ""  # bare URL, no credentials
    rtsp_user: str = ""
    rtsp_password: str = ""
    rtsp_transport: str = "tcp"
    stale_seconds: float = 3.0
    hang_seconds: float = 10.0
    cookie_max_age: int = 30 * 24 * 3600
    lockout_attempts: int = 5
    lockout_seconds: int = 30
    # Both off by default: correct on a LAN, and each one is wrong to guess.
    # A trusted header that nobody vouches for lets a visitor choose their
    # own lockout bucket; a Secure cookie over plain http:// is never sent
    # back, so the login silently never takes. `docs/remote-access.md` says
    # when to turn them on.
    trusted_proxy_header: str = ""  # e.g. CF-Connecting-IP behind cloudflared
    #: Peers whose forwarded-address header is believed. Loopback, because
    #: cloudflared runs on this machine; list the tunnel host's address here
    #: if it ever runs elsewhere. Never a LAN range.
    trusted_proxy_ips: tuple[str, ...] = ("127.0.0.1", "::1")
    secure_cookies: bool = False
    #: Directory for a rotating `kona.log`; blank = console only.
    log_dir: str = ""
    #: Hold off Windows sleep while serving, instead of disabling sleep in the
    #: power plan for good. Off by default: when this machine sleeps is the
    #: owner's business, not a side effect of starting a web server.
    keep_awake: bool = False
    #: Dead-man's-switch ping URL. Treated as a secret: whoever holds it can
    #: forge this app's heartbeat and silence the alarm.
    heartbeat_url: str = ""
    heartbeat_seconds: float = 300.0
    # Same two keys the probe already uses, so `.env` stays one file with one
    # Fi login in it rather than two that can drift apart.
    fi_email: str = ""
    fi_password: str = ""
    fi_refresh_seconds: float = 300.0
    fi_data_start: date | None = None

    @property
    def fi_configured(self) -> bool:
        """Both halves, or none: half a login only produces a 401 later."""
        return bool(self.fi_email and self.fi_password)

    @property
    def fake_camera(self) -> bool:
        return self.camera_source == "fake"

    def capabilities(self) -> Capabilities:
        """What this camera can do. Data, not an assumption in a template."""
        return for_model(self.camera_model, self.camera_source)

    def camera_label(self) -> str:
        if self.camera_source == "fake":
            return "fake test pattern"
        if self.camera_source == "rtsp":
            return f"rtsp {redact_url(self.rtsp_url)}"
        return f"usb index {self.camera_index}"

    def camera_description(self) -> str:
        """The camera in the owner's words, for the profile page.

        `camera_label()` is developer language ("usb index 0") and belongs
        in logs and the console. A phone screen gets a sentence. The RTSP
        host is the only detail worth showing and never carries credentials:
        `hostname` excludes userinfo, and the URL is stored bare anyway.
        """
        if self.camera_source == "fake":
            return "Test pattern, no camera"
        if self.camera_source == "rtsp":
            host = urlsplit(self.rtsp_url).hostname
            return f"Network camera at {host}" if host else "Network camera"
        suffix = f", camera {self.camera_index}" if self.camera_index else ""
        return f"Webcam on this computer{suffix}"

    def __repr__(self) -> str:  # never print secrets, even by accident
        return (
            f"Settings(camera={self.camera_label()!r}, passcode='***', secret='***', "
            f"rtsp_user={self.rtsp_user!r}, rtsp_password='***', "
            f"fi_email={'set' if self.fi_email else 'unset'}, fi_password='***', "
            f"heartbeat={'set' if self.heartbeat_url else 'unset'})"
        )


class SettingsError(ValueError):
    pass


def parse_bool(value: str, key: str) -> bool:
    """`1/true/yes/on` and `0/false/no/off`, case-insensitive; blank is False.

    Anything else is refused by name rather than read as False: a typo in a
    security switch must not silently leave it off.
    """
    text = value.strip().lower()
    if text in ("", "0", "false", "no", "off"):
        return False
    if text in ("1", "true", "yes", "on"):
        return True
    raise SettingsError(f"{key} must be true or false, not {value!r}")


def load_settings(env_file: Path | None = Path(".env"), fake_camera: bool = False) -> Settings:
    from_file = read_env_file(env_file) if env_file else {}

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or from_file.get(key, default)

    passcode = get("KONA_PASSCODE")
    if not passcode:
        raise SettingsError("KONA_PASSCODE is not set (put it in .env; see .env.example)")
    if len(passcode) < MIN_SAFE_PASSCODE:
        # Fine on a LAN, dangerous behind a tunnel: once the app has a public
        # URL a short numeric code is guessable. Warn, never block — the user
        # may genuinely be on a closed network.
        print(
            f"KONA_PASSCODE is under {MIN_SAFE_PASSCODE} characters. That is fine on your own "
            "Wi-Fi, but use a longer one before exposing this through a tunnel or port forward.",
            file=sys.stderr,
        )
    secret = get("KONA_SECRET")
    if not secret:
        # Sessions will not survive a restart, which is fine for a first run
        # but worth knowing about; say so on stderr, never generate silently.
        secret = secrets.token_urlsafe(32)
        print(
            "KONA_SECRET not set: generated one for this run; logins reset on restart. "
            "Set KONA_SECRET in .env to keep sessions.",
            file=sys.stderr,
        )
    source = "fake" if fake_camera else get("KONA_CAMERA_SOURCE", "usb").strip().lower()
    if source not in CAMERA_SOURCES:
        raise SettingsError(f"KONA_CAMERA_SOURCE must be one of {CAMERA_SOURCES}, not {source!r}")

    # Credentials belong in their own keys; a URL that carries them is
    # tolerated but split apart so every log/status line stays redacted.
    rtsp_url, url_user, url_pass = split_credentials(get("KONA_RTSP_URL"))
    rtsp_user = get("KONA_RTSP_USER") or url_user
    rtsp_password = get("KONA_RTSP_PASSWORD") or url_pass
    if source == "rtsp" and not rtsp_url:
        raise SettingsError("KONA_CAMERA_SOURCE=rtsp needs KONA_RTSP_URL (see .env.example)")
    if rtsp_url and not has_scheme(rtsp_url):
        # FFmpeg could not open it anyway, and a scheme-less URL is the one
        # shape a credential redactor can get wrong; refuse early.
        raise SettingsError("KONA_RTSP_URL must start with a scheme, e.g. rtsp://<ip>:554/stream1")

    trusted_proxy_header = get("KONA_TRUSTED_PROXY_HEADER").strip()
    trusted_proxy_ips = tuple(
        part.strip() for part in get("KONA_TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    )
    trusted_proxy_ips = tuple(ip for ip in trusted_proxy_ips if ip) or ("127.0.0.1", "::1")
    secure_cookies = parse_bool(get("KONA_SECURE_COOKIES"), "KONA_SECURE_COOKIES")
    keep_awake = parse_bool(get("KONA_KEEP_AWAKE"), "KONA_KEEP_AWAKE")
    if trusted_proxy_header and not secure_cookies:
        # A proxy header only makes sense behind a tunnel, and a tunnel is
        # HTTPS; a session cookie that can also travel over plain http is
        # the one gap left. Warn, never block: the LAN address still works.
        print(
            "KONA_TRUSTED_PROXY_HEADER is set but KONA_SECURE_COOKIES is not. Behind a tunnel "
            "set KONA_SECURE_COOKIES=true so the session cookie only travels over HTTPS.",
            file=sys.stderr,
        )

    data_start_raw = get("KONA_FI_DATA_START").strip()
    try:
        data_start = date.fromisoformat(data_start_raw) if data_start_raw else None
    except ValueError as exc:
        raise SettingsError("KONA_FI_DATA_START must be YYYY-MM-DD") from exc

    return Settings(
        passcode=passcode,
        secret=secret,
        camera_source=source,
        camera_model=get("KONA_CAMERA_MODEL", "").strip().lower(),
        camera_index=int(get("KONA_CAMERA_INDEX", "0")),
        camera_width=int(get("KONA_CAMERA_WIDTH", "1280")),
        camera_height=int(get("KONA_CAMERA_HEIGHT", "720")),
        camera_fps=int(get("KONA_CAMERA_FPS", "15")),
        rtsp_url=rtsp_url,
        rtsp_user=rtsp_user,
        rtsp_password=rtsp_password,
        rtsp_transport=get("KONA_RTSP_TRANSPORT", "tcp").strip().lower() or "tcp",
        stale_seconds=float(get("KONA_STALE_SECONDS", "3")),
        hang_seconds=float(get("KONA_HANG_SECONDS", "10")),
        fi_email=get("FI_EMAIL"),
        fi_password=get("FI_PASSWORD"),
        fi_refresh_seconds=float(get("KONA_FI_REFRESH_SECONDS", "300")),
        fi_data_start=data_start,
        trusted_proxy_header=trusted_proxy_header,
        trusted_proxy_ips=trusted_proxy_ips,
        secure_cookies=secure_cookies,
        log_dir=get("KONA_LOG_DIR").strip(),
        keep_awake=keep_awake,
        heartbeat_url=get("KONA_HEARTBEAT_URL").strip(),
        heartbeat_seconds=float(get("KONA_HEARTBEAT_SECONDS", "300")),
    )
