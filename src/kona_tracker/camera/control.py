"""Driving the camera, as opposed to watching it.

The protocol is the seam. `FakeControl` exists so the whole control surface
— endpoints, buttons, touch handling — can be built and judged before any
hardware arrives, exactly as `FakeSource` let us build the video path and
`httpx.MockTransport` let us build the Fi client.

`TapoControl` is deliberately absent. It cannot be tested without the
camera in hand, and shipping an untested device driver is the mistake the
Fi probe exists to prevent. It lands when the C225 does.
"""

from __future__ import annotations

import threading
from typing import Any, Protocol

from kona_tracker.camera.capabilities import Capabilities

# Pan and tilt are held as fractions of full travel, -1.0 to 1.0, so the UI
# never needs to know a particular camera's degree range.
PAN_MIN, PAN_MAX = -1.0, 1.0
TILT_MIN, TILT_MAX = -1.0, 1.0


class ControlUnsupported(RuntimeError):
    """This camera cannot do that. Raised rather than quietly ignored: a
    button that does nothing is worse than one that says why."""


def _clamp(value: float, low: float, high: float) -> float:
    """Clamp into [low, high], absorbing NaN.

    The operand order is load-bearing. `min(high, value)` compares
    `value < high`, which is False for NaN, so NaN falls out as `high`
    rather than propagating. Written the other way round a NaN would reach
    the viewport maths in `FakeSource` and raise on `int(round(nan))`.
    """
    return max(low, min(high, value))


class CameraControl(Protocol):
    @property
    def capabilities(self) -> Capabilities: ...

    def position(self) -> tuple[float, float]:
        """Current (pan, tilt), each -1.0 to 1.0."""
        ...

    def move(self, pan: float = 0.0, tilt: float = 0.0) -> tuple[float, float]:
        """Nudge by a delta; returns the new clamped position."""
        ...

    def goto_preset(self, number: int) -> tuple[float, float]: ...

    def settings(self) -> dict[str, Any]:
        """The switchable settings this driver can actually read and set:
        `night` ("auto" | "on" | "off"), `privacy` (bool), `led` (bool).
        Only keys the driver drives are present; absence is "not offered"."""
        ...

    def apply(self, name: str, value: str) -> dict[str, Any]:
        """Set one of them from its form value and return the new state."""
        ...

    def close(self) -> None: ...


#: The settings a camera can offer, and how a form value becomes one. Kept
#: as data so the route, the fake and the real driver agree on the words.
SETTING_VALUES: dict[str, tuple[str, ...]] = {
    "night": ("auto", "on", "off"),
    "privacy": ("on", "off"),
    "led": ("on", "off"),
}


def parse_setting(name: str, value: str) -> str | bool:
    """A form value into the setting's own type, or ControlUnsupported."""
    allowed = SETTING_VALUES.get(name)
    if allowed is None:
        raise ControlUnsupported(f"no setting named {name!r}")
    value = (value or "").strip().lower()
    if value not in allowed:
        raise ControlUnsupported(f"{name} must be one of {', '.join(allowed)}")
    return value if name == "night" else value == "on"


class NoControl:
    """A camera we can watch but not drive: USB webcams, and any camera
    whose driver we have not written yet.

    It reports **no** capabilities, whatever the model is theoretically
    able to do. A C225 can pan, but until `TapoControl` exists we cannot
    make it pan, and advertising the ability would put a pad on screen that
    409s on every press. That is the dead button `capabilities.py` exists to
    prevent. The model's own abilities stay on `model_capabilities` for
    status and documentation.
    """

    def __init__(self, capabilities: Capabilities | None = None):
        self.model_capabilities = capabilities or Capabilities()

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities()

    def position(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def move(self, pan: float = 0.0, tilt: float = 0.0) -> tuple[float, float]:
        raise ControlUnsupported("this camera cannot pan or tilt")

    def goto_preset(self, number: int) -> tuple[float, float]:
        raise ControlUnsupported("this camera has no presets")

    def settings(self) -> dict[str, Any]:
        return {}

    def apply(self, name: str, value: str) -> dict[str, Any]:
        raise ControlUnsupported("this camera's settings cannot be changed from here")

    def close(self) -> None:
        return None


class FakeControl:
    """Simulated motors. Holds a position that `FakeSource` renders from,
    so pressing the on-screen pad genuinely moves the picture."""

    #: Preset positions, matching the numbers the UI offers.
    PRESETS: dict[int, tuple[float, float]] = {
        1: (0.0, 0.0),
        2: (-0.8, 0.2),
        3: (0.8, 0.2),
    }

    def __init__(self, capabilities: Capabilities | None = None):
        from kona_tracker.camera.capabilities import FAKE

        self._capabilities = capabilities or FAKE
        self._lock = threading.Lock()
        self._pan = 0.0
        self._tilt = 0.0
        self.moves = 0  # how many nudges landed (tests)
        # Switchable settings, held in memory so the page's controls can be
        # built and judged against the simulated camera before hardware.
        self._settings: dict[str, Any] = {"night": "auto", "privacy": False, "led": True}

    @property
    def capabilities(self) -> Capabilities:
        return self._capabilities

    def position(self) -> tuple[float, float]:
        with self._lock:
            return (self._pan, self._tilt)

    def move(self, pan: float = 0.0, tilt: float = 0.0) -> tuple[float, float]:
        if not self._capabilities.ptz:
            raise ControlUnsupported("this camera cannot pan or tilt")
        with self._lock:
            self._pan = _clamp(self._pan + pan, PAN_MIN, PAN_MAX)
            self._tilt = _clamp(self._tilt + tilt, TILT_MIN, TILT_MAX)
            self.moves += 1
            return (self._pan, self._tilt)

    def goto_preset(self, number: int) -> tuple[float, float]:
        # Presets drive the same motors, so they need ptz as well: otherwise
        # they are a second, separately-gated way to move a camera that the
        # operator marked as unable to move.
        if not (self._capabilities.presets and self._capabilities.ptz):
            raise ControlUnsupported("this camera has no presets")
        try:
            pan, tilt = self.PRESETS[number]
        except KeyError:
            raise ControlUnsupported(f"no preset {number}") from None
        with self._lock:
            self._pan, self._tilt = pan, tilt
            self.moves += 1
            return (self._pan, self._tilt)

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

    def settings(self) -> dict[str, Any]:
        with self._lock:
            return {k: self._settings[k] for k in self._offered()}

    def apply(self, name: str, value: str) -> dict[str, Any]:
        if name not in self._offered():
            raise ControlUnsupported(f"this camera has no {name} setting")
        parsed = parse_setting(name, value)
        with self._lock:
            self._settings[name] = parsed
        return self.settings()

    def close(self) -> None:
        return None
