"""Client for the Pi-side robot gateway: the only thing that moves the robot.

The gateway (built by the robot session, 2026-09-14, 62 checks passing)
listens on port 9031, forwards to the TurboPi's JSON-RPC on localhost:9030,
and owns every safety rule -- a background watchdog that zeroes the motors
when commands stop arriving, the mecanum kinematics, the duty cap, the
battery refusal, and a shared token. This module is the other half of that
contract and deliberately knows nothing about motors: we send a body
velocity, never a motor id.

Two facts from the gateway's own report shape this file:

* **Its RPC server handles one request at a time** (`run_simple()` with
  threading off) and an unnecessary `StopFunc` blocks two seconds. So we
  send `/drive` every 200 ms against a 500 ms TTL -- two chances to refresh
  before the watchdog fires, at half the load of a 100 ms loop -- and a
  stop must never queue behind our own telemetry.
* **`/stop` answers 503 when port 9030 is silent.** A stop that did not land
  is the most dangerous state this app can be in, so it travels as an error
  the page shows loudly, never as a swallowed success.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("kona_tracker.robot")

#: How long the gateway should hold a drive command before its watchdog
#: zeroes the motors. **The browser never sends this.** A page choosing the
#: length of its own dead-man switch could ask for the maximum and then
#: crash, leaving the robot driving for two seconds with nobody holding it.
#: The gateway clamps to [100, 2000]; we sit near the bottom of that.
DRIVE_TTL_MS = 500

#: Send interval the page uses, kept here so the two numbers are read
#: together: it must stay comfortably under DRIVE_TTL_MS so one dropped
#: request does not stutter the robot.
DRIVE_INTERVAL_MS = 200

#: A drive command that has not landed within this is already past the TTL
#: it was asking for -- the watchdog has fired and the robot has stopped.
#: Failing fast beats a late command arriving after the operator let go.
DRIVE_TIMEOUT_SECONDS = 1.0

#: Everything else: reaching a Pi on the LAN, or finding out it is not there.
DEFAULT_TIMEOUT_SECONDS = 2.0

#: The gateway clamps too. We clamp first so a bad value never leaves this
#: machine, and so the numbers in a log line are the numbers we meant.
LOOK_LIMIT_DEG = 45.0


class RobotError(Exception):
    """Base for everything this module raises. Never carries the token."""


class RobotUnreachable(RobotError):
    """The gateway did not answer, or answered that the robot did not.

    Both are the same thing to a person holding a joystick: the command did
    not land. Routes turn this into a 503.
    """


class RobotRefused(RobotError):
    """The gateway understood and said no -- a flat battery, or a built-in
    demo already driving the motors. Carries the gateway's own reason so
    the page can say which. Routes turn this into a 409."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class RobotFault(RobotError):
    """The gateway answered with something wrong: a rejected token, a
    malformed body, or the robot's own error text passed through. Routes
    turn this into a 502."""


def _clamp(value: Any, limit: float = 1.0) -> float:
    """A number in [-limit, limit], or a rejection. Anything non-numeric is
    a programming error on our side or a hand-crafted request; either way it
    must not reach the robot as a zero that looks deliberate."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RobotFault(f"{value!r} is not a number") from None
    if number != number:  # NaN: comparisons below would silently pass it
        raise RobotFault("not a number")
    return max(-limit, min(limit, number))


class RobotGateway:
    """One long-lived client for the gateway, with the token on every call.

    Built once per app and closed from the lifespan, like `CameraHub`. The
    token goes on as a default header rather than per call so no call site
    can forget it, and `_scrub` runs over every string that leaves here so
    it cannot travel back out in an error.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"X-Robot-Token": token},
            transport=transport,
        )
        self._owns_client = client is None

    def __repr__(self) -> str:
        # The host is worth showing; the token is not, and is not here.
        return f"RobotGateway({self._base_url})"

    def _scrub(self, text: str) -> str:
        """The token never leaves this module, in any string, ever. The
        gateway is unlikely to echo it, but an error string is forever and
        this is the one secret we hold. Same shape as `TapoControl._scrub`.
        """
        if self._token and self._token in text:
            text = text.replace(self._token, "***")
        return text[:200]

    def _reason(self, response: httpx.Response) -> str:
        """The gateway's own explanation, scrubbed, or its status code.

        The body is written by the gateway, not by the robot's operator, but
        it can carry the robot's raw error text straight through, so it is
        treated as untrusted string data on the way to a screen.
        """
        try:
            body = response.json()
        except ValueError:
            return f"HTTP {response.status_code}"
        if isinstance(body, dict) and body.get("reason"):
            return self._scrub(str(body["reason"]))
        return f"HTTP {response.status_code}"

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as e:
            # Only the exception's class name: its message can carry the URL
            # and, on some transports, the request headers with it.
            # A sentence, not a fragment. This string is shown to a person --
            # drive.js prefixes it with "The stop did not reach the robot. "
            # and the result was "...robot. could not reach the robot gateway:
            # ConnectTimeout", seen on Chris's phone 2026-09-14. The class
            # name stays because ConnectTimeout and ReadTimeout mean different
            # things to whoever is debugging; only the shape changes.
            raise RobotUnreachable(
                f"The robot's gateway is not answering ({type(e).__name__})."
            ) from None
        if response.status_code == 401:
            # Worth its own words: this is a wrong KONA_ROBOT_TOKEN, which
            # no amount of retrying fixes and which the page should say.
            raise RobotFault("The robot's gateway rejected our token. Check KONA_ROBOT_TOKEN.")
        if response.status_code == 409:
            raise RobotRefused(self._reason(response))
        if response.status_code == 503:
            raise RobotUnreachable(self._reason(response))
        if response.status_code >= 400:
            raise RobotFault(self._reason(response))
        try:
            body = response.json()
        except ValueError:
            raise RobotFault("the robot gateway did not answer with JSON") from None
        if not isinstance(body, dict):
            raise RobotFault("the robot gateway answered with an unexpected shape")
        if body.get("ok") is False:
            # A 200 that says it failed. Believe the body, not the status.
            raise RobotFault(self._reason(response))
        return body

    # -- reads ---------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Is the gateway up, and did the robot answer it recently. The one
        endpoint that needs no token and never touches the motors."""
        return self._request("GET", "/health")

    def telemetry(self) -> dict[str, Any]:
        """Battery, sonar, and what the gateway thinks it is doing.

        Passed through as the gateway sends it, including the two keys its
        author added beyond the contract: `battery_age_ms`, and
        `demo_detection` -- which is False when the robot's own
        `GetRunningFunc` is unpatched and the "a demo is driving" guard
        therefore cannot be enforced. The page says so rather than implying
        a guard that is not there.
        """
        return self._request("GET", "/telemetry")

    def look(self) -> dict[str, Any]:
        """The last pan/tilt the gateway was asked for."""
        return self._request("GET", "/look")

    # -- writes --------------------------------------------------------------

    def drive(self, vx: Any, vy: Any, omega: Any) -> dict[str, Any]:
        """A body velocity, held for DRIVE_TTL_MS and then dropped.

        `vx` forward, `vy` left, `omega` counter-clockwise, each in [-1, 1].
        The gateway owns the mecanum kinematics and the motor wiring
        inversion; we never send a motor id, and we never send a TTL the
        caller chose.
        """
        return self._request(
            "POST",
            "/drive",
            json={
                "vx": _clamp(vx),
                "vy": _clamp(vy),
                "omega": _clamp(omega),
                "ttl_ms": DRIVE_TTL_MS,
            },
            timeout=DRIVE_TIMEOUT_SECONDS,
        )

    def stop(self) -> dict[str, Any]:
        """All four motors to zero. Works under a flat battery and with a
        demo running; the gateway only calls the robot's own `StopFunc`
        when one is actually loaded, because an unnecessary one blocks the
        single-threaded RPC server for two seconds -- which would mean a
        stop delayed by the previous stop."""
        return self._request("POST", "/stop")

    def stop_quietly(self) -> bool:
        """A stop that cannot fail the caller, for shutdown and error paths.

        Returns whether it landed. Used where there is nobody left to tell:
        the app is going down, or we are already answering an error. On a
        screen a failed stop is shouted about; here it is logged, because
        raising inside a `finally` would mask what we were already handling.
        """
        try:
            self.stop()
        except RobotError as e:
            log.warning("robot stop failed: %s", self._scrub(str(e)))
            return False
        except Exception as e:
            # Deliberately broader than RobotError. This runs from the
            # lifespan's `finally`; anything raised here would mask whatever
            # was already being handled and could take the shutdown with it.
            log.warning("robot stop failed: %s", type(e).__name__)
            return False
        return True

    def look_at(self, pan_deg: Any, tilt_deg: Any) -> dict[str, Any]:
        """Point the camera. Clamped here and again on the Pi: a servo
        driven into its mechanical stop stalls, draws full current and
        strips its own gears."""
        return self._request(
            "POST",
            "/look",
            json={
                "pan_deg": _clamp(pan_deg, LOOK_LIMIT_DEG),
                "tilt_deg": _clamp(tilt_deg, LOOK_LIMIT_DEG),
            },
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()
