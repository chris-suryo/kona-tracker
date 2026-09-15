"""Nothing that identifies Chris's home network or machine is in the tree.

The repository went public on 2026-09-14 with a Windows username in the
docs and the robot's LAN address in eleven files, one of them next to the
sentence "no credentials, anyone on the Wi-Fi can watch it". None of that
is a secret in the way a token is -- a private address is unroutable and a
username is not a password -- but a portfolio reader should not be able to
learn the layout of someone's house from the docs, and an example address
in a document should read as an example. So the docs use TEST-NET
(`192.0.2.0/24`, reserved for documentation by RFC 5737) and `<you>` for
the home directory, and this test keeps it that way.

Tests are not scanned: their fixture addresses are fixture values and never
reach a reader. `.env` is gitignored and never scanned either.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCANNED = ["README.md", "PROJECT.md", "docs", "src", "scripts", ".github"]
TEXT = {
    ".md",
    ".py",
    ".js",
    ".cjs",
    ".html",
    ".css",
    ".ps1",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".example",
    ".sh",
}
FORBIDDEN = {
    "the Windows username": re.compile(r"harim"),
    "a home-LAN address": re.compile(r"\b10\.0\.0\.\d+\b"),
    "a Tailscale address": re.compile(r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d+\.\d+\b"),
}


def files():
    for name in SCANNED:
        path = ROOT / name
        if path.is_file():
            yield path
        else:
            yield from (p for p in path.rglob("*") if p.is_file() and p.suffix in TEXT)


@pytest.mark.parametrize("what", list(FORBIDDEN))
def test_nothing_in_the_tree_names_the_home_network(what):
    pattern = FORBIDDEN[what]
    found = [
        f"{path.relative_to(ROOT)}:{n}"
        for path in files()
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
        if pattern.search(line)
    ]
    assert not found, f"{what} appears in: {found}"


def test_the_scan_would_notice():
    """A scanner that matches nothing is indistinguishable from one that
    is pointed at the wrong directory."""
    assert sum(1 for _ in files()) > 50
    assert FORBIDDEN["a home-LAN address"].search("KONA_ROBOT_CONTROL_URL=http://10.0.0.3:9031")
    assert FORBIDDEN["a Tailscale address"].search("reach it at 100.101.102.103")
    assert not FORBIDDEN["a Tailscale address"].search("100.0.0.1 is not in the CGNAT range")
