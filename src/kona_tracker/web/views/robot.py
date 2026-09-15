"""What a robot refusal means, in words. The gateway answers with a reason
token; the page needs a sentence.
"""

from __future__ import annotations

#: Every reason the robot gateway can send, in words that name what to do
#: about it. Read off its source (chris-suryo/turbopi, gateway/robot_gateway.py)
#: rather than from its summary, which is how `no_token_configured` was found
#: -- a 503 that means the *gateway* is misconfigured, not that the robot is
#: unreachable, and which would otherwise have reached the screen as a raw
#: token under a sentence about turning the robot off and on.
#:
#: Anything unrecognised is still shown raw. Inventing a sentence for a reason
#: nobody has seen would be worse than showing the token: at least the token
#: can be searched for.
#:
#: No entry for `unauthorized`: a 401 is intercepted in `RobotGateway._request`
#: before a reason is ever read, and it already raises the sentence this table
#: would have held. An entry here would be dead code that looked alive.
_ROBOT_REFUSALS = {
    "low_battery": "The robot's battery is too low to drive. Put it on charge.",
    "demo_running": "A built-in demo is driving the robot. Stop the demo first.",
    "turbopi_unreachable": "The robot's own software is not answering. Turn it off and on.",
    "no_token_configured": (
        "The robot's gateway has no access token set up. Check the secret file on the Pi."
    ),
    "invalid_body": "The robot's gateway did not understand that command.",
    "obstacle": (
        "Something is right in front of the robot. Back up, strafe or turn — those still work."
    ),
}


def robot_refusal(reason: str) -> str:
    """A reason token as a sentence. Applied to *every* robot failure, not
    just refusals: a 503 and a 502 reach the same screen and the person
    reading it has no more use for `turbopi_unreachable` than for
    `low_battery`."""
    return _ROBOT_REFUSALS.get(reason, reason)
