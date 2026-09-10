"""Blank private values before anything is written to disk.

The probe's output is meant to be pasted into a chat or committed to docs, so
it must never carry account identifiers or Kona's whereabouts. Matching is
by key name (case-insensitive substring) because we do not know the schema
in advance; that is the point of the probe. Numeric durations, step counts,
and field NAMES are untouched: those are what we are trying to learn.
"""

from __future__ import annotations

from typing import Any

REDACTED = "<redacted>"

# Substrings of key names whose VALUES get blanked. Kept deliberately broad.
SENSITIVE_KEY_PARTS = (
    "email",
    "password",
    "session",
    "token",
    "cookie",
    "secret",
    "latitude",
    "longitude",
    "lat",
    "lng",
    "lon",
    "address",
    "place",
    "position",
    "location",
    "phone",
    "chip",
    "moduleid",
    "serial",
    # Added when the profile/location queries landed: the summary already
    # promised "locations, addresses" and these slipped through it.
    # `homeCityState` is the town Kona lives in and `areaName` is where she
    # is standing right now -- both go into a file Chris pastes into chats.
    "city",
    "area",
    "zip",
    "postal",
    "street",
    "region",
    "neighborhood",
    "geo",
    "coord",
    "timezone",
    # Photo URLs are shareable links to pictures of the dog and the house.
    # The key survives, so the probe still proves the field exists.
    "fullsize",
    "url",
)
# Deliberately NOT here: a bare "state". It would match `lastConnectionState`
# and blank the whole nested object -- including the charge and signal fields
# the probe exists to discover. Redaction must not eat the answer.

# ...which it then did anyway, twice, caught in review. Both of these match a
# rule above but carry nothing private themselves, and blanking them destroys
# the shape the probe exists to learn:
#
#   nextLocationUpdateExpectedBy  matches "location", but is a timestamp.
#   positions                     matches "position", but is the ARRAY. Its
#                                 elements' `date` and `errorRadius` are what
#                                 we queried for; the coordinates inside are
#                                 still blanked by the `position`, `lat` and
#                                 `lon` rules one level down.
#
# Anything added here must be a container or a non-private scalar whose
# sensitive leaves are individually covered above. Check that before adding.
NOT_SENSITIVE_KEYS = frozenset(
    {
        "nextlocationupdateexpectedby",
        "positions",
    }
)


def is_sensitive_key(key: str) -> bool:
    k = key.lower()
    if k in NOT_SENSITIVE_KEYS:
        return False
    return any(part in k for part in SENSITIVE_KEY_PARTS)


def redact(obj: Any) -> Any:
    """Return a deep copy with sensitive values replaced by REDACTED."""
    if isinstance(obj, dict):
        return {
            k: (REDACTED if is_sensitive_key(str(k)) and v is not None else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj
