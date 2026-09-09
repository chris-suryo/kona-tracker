"""Runtime settings from the environment (or a .env file). No host lock-in:
the same variables work on the Windows PC, the Pi, or a cloud box."""

from __future__ import annotations

import os
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from kona_tracker.cli_env import read_env_file


@dataclass(frozen=True)
class Settings:
    passcode: str
    secret: str
    camera_index: int = 0
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 15
    fake_camera: bool = False
    cookie_max_age: int = 30 * 24 * 3600
    lockout_attempts: int = 5
    lockout_seconds: int = 30


class SettingsError(ValueError):
    pass


def load_settings(env_file: Path | None = Path(".env"), fake_camera: bool = False) -> Settings:
    from_file = read_env_file(env_file) if env_file else {}

    def get(key: str, default: str = "") -> str:
        return os.environ.get(key) or from_file.get(key, default)

    passcode = get("KONA_PASSCODE")
    if not passcode:
        raise SettingsError("KONA_PASSCODE is not set (put it in .env; see .env.example)")
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
    return Settings(
        passcode=passcode,
        secret=secret,
        camera_index=int(get("KONA_CAMERA_INDEX", "0")),
        camera_width=int(get("KONA_CAMERA_WIDTH", "1280")),
        camera_height=int(get("KONA_CAMERA_HEIGHT", "720")),
        camera_fps=int(get("KONA_CAMERA_FPS", "15")),
        fake_camera=fake_camera,
    )
