"""Talking to the robot -- and only ever through its safety gateway.

Nothing in this package speaks to the TurboPi's own JSON-RPC port (9030).
That port has no authentication, no clamping, and no command expiry: a duty
value sent to it is held until another arrives, so a lost "stop" is a robot
that drives until it hits something. The watchdog that fixes this has to
live on the Pi, because the failure it guards against is *this machine*
becoming unreachable, and a watchdog on the far side of a broken link
cannot fire. So the Pi runs a small gateway that owns the watchdog, the
clamp, the battery refusal and the token, and we talk to that.
"""
