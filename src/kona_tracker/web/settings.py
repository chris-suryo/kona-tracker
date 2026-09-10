"""Runtime settings from the environment (or a .env file). No host lock-in:
the same variables work on the Windows PC, the Pi, or a cloud box."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

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

    def __repr__(self) -> str:  # never print secrets, even by accident
        return (
            f"Settings(camera={self.camera_label()!r}, passcode='***', secret='***', "
            f"rtsp_user={self.rtsp_user!r}, rtsp_password='***')"
        )


class SettingsError(ValueError):
    pass


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
    )
