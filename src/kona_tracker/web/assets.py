"""Content-addressed URLs for the static files a phone caches too well.

The stylesheet and scripts are served from a stable path, so Safari is free
to keep serving yesterday's copy of `/static/app.css` against today's HTML.
That is not theoretical: it happened on 2026-09-12, and the page looked
broken in three separate ways at once -- black rectangles where the rest
chart should be, a run-together axis, and a link floating outside the block
it belongs to -- because every rule those needed was in a stylesheet the
phone already had a name for and would not fetch again.

A hash of the bytes in the query string fixes it in the only way that
survives a change we have not thought of yet: when a file changes, its URL
changes, so the browser has never seen it and must ask. When a file does
not change, neither does its URL, so the cache still does its job.

Hashes are read once at startup. The files are shipped inside the package
and cannot change under a running server, so re-reading them per request
would buy nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

#: Enough hex to make a collision between two versions of one small file
#: not worth thinking about, and short enough to read in a page source.
DIGEST_CHARS = 10


def asset_versions(static_dir: Path) -> dict[str, str]:
    """Map each static file's relative URL path to a short content hash."""
    versions: dict[str, str] = {}
    if not static_dir.is_dir():
        return versions
    for path in sorted(static_dir.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:DIGEST_CHARS]
            versions[path.relative_to(static_dir).as_posix()] = digest
    return versions


def asset_url(versions: dict[str, str], name: str) -> str:
    """`/static/<name>?v=<hash>`, or the bare path if the file is unknown.

    An unknown name means a template asked for a file that is not there.
    That is a broken page either way; serving the unversioned URL keeps the
    failure a plain 404 in the network tab rather than a confusing one.
    """
    version = versions.get(name)
    return f"/static/{name}?v={version}" if version else f"/static/{name}"
