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

The camera locks its control API for about half an hour after a handful of
failed logins, and a Camera-tab visit is a login -- pytapo even retries
internally, so one visit can be several. So after the camera refuses a login,
or says to wait, this module stops contacting it for a while and answers from
what it already knows. Without that, the page loads themselves keep the camera
locked: seen on 2026-09-30, "Temporary Suspension: Try again in 982 seconds".
"""

from __future__ import annotations

import logging
import math
import re
import threading
import time
from collections.abc import Callable
from typing import Any

from kona_tracker.camera.capabilities import Capabilities
from kona_tracker.camera.control import ControlUnsupported, parse_setting

log = logging.getLogger("kona_tracker.camera.tapo")
#: The session token as it appears inside a pytapo request URL.
_STOK = re.compile(r"stok=[^/\s\"']+")
#: pytapo's words when the camera has locked out its control API.
_SUSPENDED = re.compile(r"Temporary Suspension: Try again in (\d+) seconds")
#: pytapo's words for a login the camera turned down -- a wrong password and
#: a right password on the wrong account read identically (see _default_client).
_REFUSED = "Invalid authentication data"
#: After a refused login, how long before trying again. Long enough that page
#: loads cannot add up to a lockout; short enough that fixing `.env` and
#: restarting is not followed by a wait.
REFUSED_COOLDOWN_SECONDS = 300.0
#: Added to the camera's own countdown, so the first retry lands after it
#: rather than on its last second and re-arms it.
SUSPENSION_MARGIN_SECONDS = 5.0
#: The longest the app will take the camera's word for. Observed lockouts are
#: about half an hour; a garbled or hostile number must not switch the
#: switches off for a day, or overflow a float on its way in.
SUSPENSION_CAP_SECONDS = 3600.0


class TapoError(RuntimeError):
    """The camera did not do what was asked. The message is safe to show."""


def _default_client(host: str, user: str, password: str, cloud_password: str = "") -> Any:
    from pytapo import Tapo  # imported here: only a configured Tapo pays for it

    # What logs in is `user` + `password`: on recent firmware that must be
    # `admin` with the TP-Link account password. pytapo's secure login refuses
    # any non-root account -- the camera account included -- and reports it as
    # "Invalid authentication data", identical to a wrong password. Confirmed
    # on the C120 on 2026-09-30, the first time the switches ever worked.
    #
    # `cloudPassword` is not part of the login; pytapo uses it only for its
    # media-streaming session, which this app does not open. A 2026-09-13
    # theory that the login needed the camera account *plus* this password was
    # never tested against the camera and was wrong. Blank reuses `password`.
    return Tapo(host, user, password, cloudPassword=cloud_password or password)


class TapoControl:
    def __init__(
        self,
        host: str,
        user: str,
        password: str,
        model: Capabilities,
        client_factory: Callable[..., Any] = _default_client,
        cloud_password: str = "",
        clock: Callable[[], float] = time.monotonic,
    ):
        self._host = host
        self._user = user
        self._password = password
        self._cloud_password = cloud_password
        self._factory = client_factory
        self._client: Any = None
        self._lock = threading.Lock()
        self._clock = clock
        #: Until this moment on `clock`, do not contact the camera at all.
        self._quiet_until = 0.0
        #: "suspended" (the camera said wait) or "refused" (it said no).
        self._quiet_why = ""
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
        """Nothing secret leaves in an error string: neither password, and
        not the camera's session token, which requests echoes as part of
        the URL (`/stok=<token>/ds`) when a cached session hits a dead
        camera. Short-lived and LAN-only, but a log line is forever."""
        for secret in (self._password, self._cloud_password):
            if secret and secret in text:
                text = text.replace(secret, "***")
        text = _STOK.sub("stok=***", text)
        return text[:200]

    def _quiet_message(self, now: float) -> str:
        """What the page says while the app is standing back. Plain words:
        whoever reads it is on a phone, not at the PC."""
        minutes = max(1, math.ceil((self._quiet_until - now) / 60))
        when = "about a minute" if minutes == 1 else f"about {minutes} minutes"
        if self._quiet_why == "suspended":
            return (
                "The camera has paused logins to its switches after too many failed "
                f"attempts. The app will try again in {when}."
            )
        return (
            "The camera turned down the login for its switches, so the password the "
            f"app uses needs checking. The app will try again in {when}."
        )

    def _call(self, what: str, fn: Callable[[Any], Any]) -> Any:
        with self._lock:
            if self._clock() < self._quiet_until:
                # Not contacting the camera is the point: every attempt now
                # would count towards, or extend, its lockout.
                raise TapoError(self._quiet_message(self._clock()))
            connecting = self._client is None
            try:
                if connecting:
                    self._client = self._factory(
                        self._host, self._user, self._password, self._cloud_password
                    )
                return fn(self._client)
            except Exception as e:  # pytapo raises plain Exception
                # A failed call may mean the session died; forget it so the
                # next call logs in again rather than failing forever.
                self._client = None
                raw, detail = str(e), self._scrub(str(e))
                suspended = _SUSPENDED.search(raw)
                if suspended or _REFUSED in raw:
                    failed_at = self._clock()
                    if suspended:
                        digits = suspended.group(1)
                        said = SUSPENSION_CAP_SECONDS if len(digits) > 6 else float(digits)
                        wait = min(said, SUSPENSION_CAP_SECONDS) + SUSPENSION_MARGIN_SECONDS
                        self._quiet_why = "suspended"
                    else:
                        wait = REFUSED_COOLDOWN_SECONDS
                        self._quiet_why = "refused"
                    self._quiet_until = failed_at + wait
                    # The log is for whoever fixes it at the PC, so it names
                    # the settings; the page does not.
                    log.warning(
                        "tapo login refused while %s (%s); not contacting the camera for "
                        "%.0fs. Recent firmware wants KONA_TAPO_USER=admin and "
                        "KONA_TAPO_PASSWORD = the TP-Link account password.",
                        what,
                        detail,
                        wait,
                    )
                    raise TapoError(self._quiet_message(failed_at)) from None
                log.warning("tapo %s failed: %s", what, detail)
                if connecting:
                    raise TapoError(f"Could not reach the camera's control API: {detail}") from None
                raise TapoError(f"The camera refused {what}: {detail}") from None

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
