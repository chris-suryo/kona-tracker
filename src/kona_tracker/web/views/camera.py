"""The camera status rows on the Settings page, in words a person can act on."""

from __future__ import annotations

from typing import Any

#: `CameraHub.status()` in words a phone can act on. The error kinds are the
#: hub's own; the sentences are `camera-doctor`'s verdicts, so the settings
#: page says from the road what the doctor would say at the machine. One
#: table per kind of source, because "unplug the USB cable" is the right
#: advice for a webcam and nonsense for a network camera or a robot that is
#: simply switched off (ChatGPT's copy audit, 2026-09-13).
_CAMERA_STATES = {
    "live": "Delivering frames",
    "stale": "Frames have stopped",
    "connecting": "Opening the camera",
    "disconnected": "Not connected",
    "idle": "Idle · opens when viewed",
}
_CAMERA_PROBLEMS = {
    "usb": {
        "black_frame": (
            "Image fully dark. Lens cover, or a wedged USB device: "
            "unplug the camera and plug it back in."
        ),
        "open": "Could not open the camera. Another program may be holding it.",
        "hung": "The camera stopped answering. A reconnect was requested.",
        "reader_limit": (
            "Camera recovery is stuck. For USB, unplug and reconnect; otherwise restart the server."
        ),
        "read": "Reading frames failed.",
        "empty_frames": (
            "The camera opened but delivered no frames: unplug it and plug it back in."
        ),
    },
    "rtsp": {
        "black_frame": (
            "Image fully dark. Check the lens cover, and privacy mode in the camera's settings."
        ),
        "open": "Could not reach the camera at its address. Is it powered and on the Wi-Fi?",
        "hung": "The camera stopped sending frames. A reconnect was requested.",
        "reader_limit": "Camera recovery is stuck. Power-cycle the camera or restart the server.",
        "read": "Reading frames failed.",
        "empty_frames": "The camera connected but sent no frames. Power-cycle the camera.",
    },
    "robot": {
        "black_frame": "No usable picture from the robot. Is its lens covered?",
        "open": "Could not reach the robot. It is off, or off the Wi-Fi.",
        "hung": "The robot stopped sending frames. A reconnect was requested.",
        "reader_limit": (
            "Robot recovery is stuck. Turn the robot off and on, or restart the server."
        ),
        "read": "Reading frames from the robot failed.",
        "empty_frames": "The robot answered but sent no frames. Turn it off and on.",
    },
}


def camera_health(status: dict[str, Any], kind: str = "usb") -> dict[str, Any]:
    """Rows for the settings page. Nothing here is invented: an unknown
    state or error kind is shown as the raw word, never dressed up. `kind`
    is the source the hub reads (usb, rtsp, robot) and picks the advice."""
    state = status.get("state")
    error = status.get("last_error_kind")
    age = status.get("last_frame_age")
    problems = _CAMERA_PROBLEMS.get(kind, _CAMERA_PROBLEMS["usb"])
    return {
        "state": _CAMERA_STATES.get(state, str(state)),
        "live": state == "live",
        "last_frame": None if age is None else f"{age:.0f} s ago",
        "problem": problems.get(error, error) if error else None,
        "reconnects": status.get("reconnects") or 0,
    }
