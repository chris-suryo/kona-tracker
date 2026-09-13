"""What a given camera can actually do.

Chris wants to compare models, so abilities are data rather than
assumptions baked into a template. The C120 he ordered is fixed; the C225
in the same family pans and tilts. Both must render correctly from the same
code, which means the page asks what the camera supports instead of
guessing.

See `docs/device-capabilities.md` for the sourced per-model matrix.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Capabilities:
    """One camera's abilities. Every flag defaults off: a camera earns a
    control by proving it has it, never by us hoping."""

    ptz: bool = False  # motorised pan and tilt
    presets: bool = False  # saved positions to jump back to
    night_vision: bool = False
    privacy: bool = False  # lens blind / privacy mode
    alarm: bool = False  # siren
    led: bool = False  # status light
    motion: bool = False  # motion detection toggle + sensitivity
    # Two-way talk is False on every Tapo and is not an oversight: TP-Link
    # implements ONVIF Profile S, and the audio backchannel is Profile T.
    # It works in the Tapo app, never through ours. Do not flip this on
    # without a working prototype against real hardware.
    talk: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


# Fixed Tapo (C120). Everything but the motors.
TAPO_FIXED = Capabilities(night_vision=True, privacy=True, alarm=True, led=True, motion=True)

# Pan/tilt Tapo (C225, C220, C210). Same local API plus motor control.
TAPO_PAN_TILT = Capabilities(
    ptz=True,
    presets=True,
    night_vision=True,
    privacy=True,
    alarm=True,
    led=True,
    motion=True,
)

# A plain webcam: we can read frames and nothing else.
USB = Capabilities()

# The simulated camera claims pan/tilt, and the three switches a Tapo has,
# so the control surface can be built and judged before any hardware
# arrives. Nothing else is pretended: no alarm, no motion, no talk.
FAKE = Capabilities(ptz=True, presets=True, night_vision=True, privacy=True, led=True)

# `KONA_CAMERA_MODEL` picks one of these. Unknown models fall back to the
# most cautious reading of the source rather than the most generous.
BY_MODEL: dict[str, Capabilities] = {
    "c120": TAPO_FIXED,
    "c110": TAPO_FIXED,
    "c100": TAPO_FIXED,
    "c210": TAPO_PAN_TILT,
    "c220": TAPO_PAN_TILT,
    "c225": TAPO_PAN_TILT,
    "usb": USB,
    "fake": FAKE,
}

MODELS = tuple(sorted(BY_MODEL))


def for_model(model: str, source: str) -> Capabilities:
    """Capabilities for a configured model, falling back on the source type.

    An unrecognised RTSP camera gets nothing beyond video: we would rather
    show too few controls than offer one that silently fails.
    """
    known = BY_MODEL.get(model.strip().lower())
    if known is not None:
        return known
    if source == "fake":
        return FAKE
    return USB
