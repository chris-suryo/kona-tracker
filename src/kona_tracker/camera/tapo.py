"""Drive a Tapo camera's switches over its local API, through pytapo.

Three settings, because three are what this app can honestly offer today:
night vision (auto / on / off), privacy mode (the lens blind -- the picture
goes black until it is off), and the status LED. The C120 has no motors,
so `move` and `goto_preset` refuse like NoControl's do; a pan/tilt model
would need motor code that has not been written, and advertising motion
before it exists is the dead button `capabilities.py` exists to prevent.

The connection is made on first use, not at startup. pytapo probes the
camera when it is constructed, and the server must come up whether or not
the camera is reachable at that moment: a camera that is off should cost
the settings section and nothing else.

Credentials: recent Tapo firmware authenticates the control API with your
TP-Link cloud password as user `admin`; older firmware takes the camera
account. Neither is ever logged, and every error string that leaves this
module has the password scrubbed from it in case pytapo echoed it.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

from kona_tracker.camera.capabilities import Capabilities
from kona_tracker.camera.control import ControlUnsupported, parse_setting

log = logging.getLogger("kona_tracker.camera.tapo")
#: The session token as it appears inside a pytapo request URL.
_STOK = re.compile(r"stok=[^/\s\"']+")


class TapoError(RuntimeError):
    """The camera did not do what was asked. The message is safe to show."""


def _default_client(host: str, user: str, password: str) -> Any:
    from pytapo import Tapo  # imported here: only a configured Tapo pays for it

    return Tapo(host, user, password)


class TapoControl:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        model: Capabilities,
        client_factory: Callable[[str, str, str], Any] = _default_client,
    ):
        self._host = host
        self._user = user
        self._password = password
        self._factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()
        self.model_capabilities = model
        # Only the three switches are driven; motion is not, whatever the
        # model can do, so it is not advertised.
        self._capabilities = Capabilities(
            night_vision=model.night_vision, privacy=model.privacy, led=model.led
        )

    def __repr__(self) -> str:
        return f"TapoControl({self._host})"

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    # -- motors: not driven --------------------------------------------------
    def position(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def move(self, pan: float = 0.0, tilt: float = 0.0) -> tuple[float, float]:
        raise ControlUnsupported("this camera cannot pan or tilt")

    def goto_preset(self, number: int) -> tuple[float, float]:
        raise ControlUnsupported("this camera has no presets")

    # -- switches ------------------------------------------------------------
    def _scrub(self, text: str) -> str:
        """Nothing secret leaves in an error string: not the password, and
        not the camera's session token, which requests echoes as part of
        the URL (`/stok=<token>/ds`) when a cached session hits a dead
        camera. Short-lived and LAN-only, but a log line is forever."""
        if self._password and self._password in text:
            text = text.replace(self._password, "***")
        text = _STOK.sub("stok=***", text)
        return text[:200]

    def _connect(self) -> Any:
        if self._client is None:
            try:
                self._client = self._factory(self._host, self._user, self._password)
            except Exception as e:  # pytapo raises plain Exception
                raise TapoError(
                    f"Could not reach the camera's control API: {self._scrub(str(e))}"
                ) from None
        return self._client

    def _call(self, what: str, fn: Callable[[Any], Any]) -> Any:
        with self._lock:
            client = self._connect()
            try:
                return fn(client)
            except Exception as e:
                # A failed call may mean the session died; forget it so the
                # next call logs in again rather than failing forever.
                self._client = None
                log.warning("tapo %s failed: %s", what, self._scrub(str(e)))
                raise TapoError(f"The camera refused {what}: {self._scrub(str(e))}") from None

    def _offered(self) -> list[str]:
        caps = self._capabilities
        return [
            name
            for name, on in (
                ("night", caps.night_vision),
                ("privacy", caps.privacy),
                ("led", caps.led),
            )
            if on
        ]

    @staticmethod
    def _on(value: Any) -> bool | None:
        """pytapo returns `{"enabled": "on"}` for the switches."""
        if isinstance(value, dict):
            value = value.get("enabled")
        if value in ("on", True):
            return True
        if value in ("off", False):
            return False
        return None

    def settings(self) -> dict[str, Any]:
        offered = self._offered()
        if not offered:
            return {}

        def read(client: Any) -> dict[str, Any]:
            out: dict[str, Any] = {}
            if "night" in offered:
                mode = client.getDayNightMode()
                out["night"] = mode if mode in ("auto", "on", "off") else None
            if "privacy" in offered:
                out["privacy"] = self._on(client.getPrivacyMode())
            if "led" in offered:
                out["led"] = self._on(client.getLED())
            return out

        return self._call("reading its settings", read)

    def apply(self, name: str, value: str) -> dict[str, Any]:
        if name not in self._offered():
            raise ControlUnsupported(f"this camera has no {name} setting")
        parsed = parse_setting(name, value)

        def write(client: Any) -> None:
            if name == "night":
                client.setDayNightMode(parsed)
            elif name == "privacy":
                client.setPrivacyMode(bool(parsed))
            else:
                client.setLEDEnabled(bool(parsed))

        self._call(f"setting {name}", write)
        return self.settings()

    def close(self) -> None:
        with self._lock:
            self._client = None
