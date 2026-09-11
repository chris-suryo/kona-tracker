"""Keep the machine awake while the app is serving, and only while it is.

The obvious way to stop a sleeping PC dropping the camera and the tunnel is
`powercfg /change standby-timeout-ac 0`: never sleep, ever, whether or not
anyone is watching Kona. That is a setting you forget you made, and it is
paid for in electricity every hour of every day.

Windows has a better primitive. `SetThreadExecutionState` lets a running
program say "do not sleep while I am here", and the moment the program
exits, the machine's ordinary power plan applies again. So sleep stays
switched on, `kona serve` holds it off while it runs, and stopping the app
is all it takes to get normal behaviour back.

Two deliberate limits:

- **The screen is allowed to sleep.** `ES_DISPLAY_REQUIRED` is NOT requested.
  A dark monitor is where most of an idle desktop's power goes, and nobody
  is looking at the PC anyway; the phone is the screen.
- **Opt in, and say so out loud.** Changing when someone's computer sleeps
  is not a thing to do quietly as a side effect of starting a web server.
  `KONA_KEEP_AWAKE` turns it on, and `kona serve` prints whether the request
  took, because a keep-awake that silently failed is worse than none: it is
  a promise that the app will be reachable, which it then is not.

Nothing here runs off Windows. Linux and macOS have their own mechanisms
(`systemd-inhibit`, `caffeinate`) and the Pi does not sleep at all, so this
returns False there rather than pretending.
"""

from __future__ import annotations

import ctypes
import logging
import sys

log = logging.getLogger("kona_tracker.web")

#: Keep this state until it is explicitly cleared, rather than for one call.
ES_CONTINUOUS = 0x80000000
#: The system may not sleep. Deliberately without ES_DISPLAY_REQUIRED.
ES_SYSTEM_REQUIRED = 0x00000001


def _set_state(flags: int) -> bool:
    """Call SetThreadExecutionState. False if it is unavailable or refused."""
    if sys.platform != "win32":
        return False
    try:
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    except AttributeError:  # not Windows, or a stubbed ctypes
        return False
    try:
        # Zero means the request was refused; anything else is the previous
        # state, which we do not need.
        return bool(kernel32.SetThreadExecutionState(flags))
    except OSError:
        return False


def keep_awake() -> bool:
    """Ask Windows not to sleep while this thread lives. True if it took.

    Must be called from the thread that stays alive for the life of the
    process: the state belongs to the calling thread and is dropped when
    that thread ends. The app's startup hook runs on the main thread, which
    is the one uvicorn keeps.
    """
    took = _set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
    if took:
        log.info("holding sleep off while serving; the display may still sleep")
    return took


def allow_sleep() -> bool:
    """Release the hold, so the machine's own power plan applies again."""
    released = _set_state(ES_CONTINUOUS)
    if released:
        log.info("released the sleep hold")
    return released
