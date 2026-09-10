"""Minimal KEY=VALUE .env reader: no python-dotenv dependency for a handful of
variables. Ignores blank lines and '#' comments; strips one layer of matching
quotes. Shared by the CLI and the web settings."""

from __future__ import annotations

from pathlib import Path


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        values[key.strip()] = val
    return values
