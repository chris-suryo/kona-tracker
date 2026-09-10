"""Keep camera credentials out of everything a human might read.

RTSP is the one place credentials must be inside a URL (OpenCV/FFmpeg only
accept them as userinfo), so every string that could carry that URL, error
text included, passes through here before it reaches a log, a status JSON,
or a terminal. The matcher is deliberately shape-agnostic: it does not need
a scheme, and it tolerates `/` inside the password, because the failure
mode of a strict pattern is a password on a status page.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote

# `//` (with or without a scheme), then the shortest run up to an `@` that is
# NOT followed by another `@` before the host ends (`/ ? #`, space, or end).
# That picks the last `@` of the userinfo even when the password holds `@`
# or `/`. Over-matching (an `@` in a path) only redacts more, never less.
_USERINFO = re.compile(r"(//)(\S+?)@(?=[^\s@]*(?:[/?#\s]|$))")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_PARTS = re.compile(r"^(?P<scheme>[a-zA-Z][a-zA-Z0-9+.-]*://)(?P<rest>.*)$", re.S)


def redact_url(text: str) -> str:
    """Replace `//user:pass@` with `//***@` anywhere in text, scheme or not."""
    return _USERINFO.sub(r"\1***@", text)


def has_scheme(url: str) -> bool:
    return bool(_SCHEME.match(url))


def _split_netloc(rest: str) -> tuple[str, str, str]:
    """rest = everything after `scheme://` -> (userinfo, host, path+)."""
    path_start = len(rest)
    # host ends at the first `/`, `?` or `#` that comes after the last `@`
    # preceding any `/`... simpler: take the last `@` before the first `/`
    # that is not inside userinfo. Userinfo may hold `/`, so scan for the
    # last `@` whose following segment looks like a host (no `@`, no `/`).
    at = -1
    i = rest.rfind("@")
    while i != -1:
        host_end = i + 1
        while host_end < len(rest) and rest[host_end] not in "/?#":
            host_end += 1
        if "@" not in rest[i + 1 : host_end]:
            at = i
            path_start = host_end
            break
        i = rest.rfind("@", 0, i)
    if at == -1:
        host_end = 0
        while host_end < len(rest) and rest[host_end] not in "/?#":
            host_end += 1
        return "", rest[:host_end], rest[host_end:]
    return rest[:at], rest[at + 1 : path_start], rest[path_start:]


def split_credentials(url: str) -> tuple[str, str, str]:
    """(bare_url, user, password) from a URL that may embed credentials.
    Works for IPv6 hosts and for `/` inside the password."""
    m = _PARTS.match(url)
    if not m:
        return url, "", ""
    userinfo, host, tail = _split_netloc(m.group("rest"))
    if not userinfo:
        return url, "", ""
    user, _, password = userinfo.partition(":")
    return m.group("scheme") + host + tail, unquote(user), unquote(password)


def with_credentials(url: str, user: str, password: str) -> str:
    """Insert URL-encoded credentials into a bare URL (no-op without any)."""
    if not user and not password:
        return url
    m = _PARTS.match(url)
    if not m:
        raise ValueError("camera URL needs a scheme, e.g. rtsp://host:554/stream1")
    old_userinfo, host, tail = _split_netloc(m.group("rest"))
    userinfo = quote(user, safe="") + ":" + quote(password, safe="")
    return f"{m.group('scheme')}{userinfo}@{host}{tail}"
