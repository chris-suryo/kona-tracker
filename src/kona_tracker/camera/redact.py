"""Keep camera credentials out of everything a human might read.

RTSP is the one place credentials must be inside a URL (OpenCV/FFmpeg only
accept them as userinfo), so every string that could carry that URL, error
text included, passes through here before it reaches a log, a status JSON,
or a terminal.
"""

from __future__ import annotations

import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

_USERINFO = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.-]*://)([^/@\s]+)@")


def redact_url(text: str) -> str:
    """Replace `scheme://user:pass@` with `scheme://***@` anywhere in text."""
    return _USERINFO.sub(r"\1***@", text)


def split_credentials(url: str) -> tuple[str, str, str]:
    """(bare_url, user, password) from a URL that may embed credentials."""
    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url, "", ""
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    bare = urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    return bare, unquote(parts.username or ""), unquote(parts.password or "")


def with_credentials(url: str, user: str, password: str) -> str:
    """Insert URL-encoded credentials into a bare URL (idempotent on none)."""
    if not user and not password:
        return url
    parts = urlsplit(url)
    host = parts.hostname or ""
    if parts.port:
        host += f":{parts.port}"
    userinfo = quote(user, safe="") + ":" + quote(password, safe="")
    return urlunsplit((parts.scheme, f"{userinfo}@{host}", parts.path, parts.query, parts.fragment))
