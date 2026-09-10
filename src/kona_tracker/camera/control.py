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
from typing import Protocol

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

    def close(self) -> None: ...


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

    def close(self) -> None:
        return None
