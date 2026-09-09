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
)


def is_sensitive_key(key: str) -> bool:
    k = key.lower()
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
