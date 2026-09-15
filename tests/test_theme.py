"""Light and dark by choice, not only by phone.

Two rules here are the kind that fail silently and are noticed weeks later by
someone squinting at a phone in bed, so both are pinned.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "src" / "kona_tracker" / "web"
CSS = (WEB / "static" / "app.css").read_text()
BASE = (WEB / "templates" / "base.html").read_text()
SETTINGS = (WEB / "templates" / "settings.html").read_text()
THEME_JS = (WEB / "static" / "theme.js").read_text()


def _block(selector: str) -> str:
    """The declarations inside the first rule matching `selector`."""
    start = CSS.index(selector)
    open_brace = CSS.index("{", start)
    depth, index = 0, open_brace
    while index < len(CSS):
        if CSS[index] == "{":
            depth += 1
        elif CSS[index] == "}":
            depth -= 1
            if depth == 0:
                break
        index += 1
    body = CSS[open_brace + 1 : index]
    # Normalise indentation only: the media-query copy is nested one level
    # deeper than the attribute-selector copy, which is not a difference.
    return "\n".join(line.strip() for line in body.splitlines() if line.strip())


def test_the_two_dark_token_blocks_have_not_drifted_apart():
    """Plain CSS cannot share a token body, so dark is written twice: once
    for the phone's setting and once for an explicit choice. Two definitions
    that drift is a bug nobody sees until one screen is wrong in one mode --
    and the mode you are not in is the one you never look at."""
    automatic = _block(':root:not([data-theme="light"]) {')
    chosen = _block(':root[data-theme="dark"] {')
    assert automatic == chosen, "the automatic and chosen dark themes disagree"
    assert "--bg:#121611" in chosen, "this should still be the dark ground"


def test_an_explicit_light_choice_beats_a_dark_phone():
    """Without the `:not([data-theme="light"])` guard the media query wins on
    a dark phone and the Light button does nothing -- which looks exactly
    like a broken button."""
    assert ':root:not([data-theme="light"])' in CSS


@pytest.mark.parametrize("token", ["--bg", "--ink", "--t4", "--bad", "--dim"])
def test_every_theme_token_is_defined_for_both_paths(token):
    for selector in (':root:not([data-theme="light"]) {', ':root[data-theme="dark"] {'):
        assert f"{token}:" in _block(selector), f"{token} missing from {selector}"


def test_the_theme_script_is_not_deferred():
    """`defer` would make it run after the document is parsed, so every page
    would paint in the phone's theme and then snap to the chosen one. A flash
    of the wrong colours on every navigation is worse than no choice at all.

    It cannot be inline either -- the CSP is `script-src 'self'` -- which is
    why this is a separate blocking file rather than two lines in the head.
    """
    tag = re.search(r"<script[^>]*theme\.js[^>]*>", BASE)
    assert tag, "theme.js is not loaded from base.html"
    assert "defer" not in tag.group(0), "theme.js must block: see its own comment"
    assert "async" not in tag.group(0), "async has the same flash as defer"


def test_the_theme_script_runs_before_the_stylesheet_would_paint():
    """It has to be in the head, before the body exists."""
    assert BASE.index("theme.js") < BASE.index("{% block body %}")


def test_a_blocked_localStorage_does_not_take_the_page_down():
    """Private browsing and blocked site data make localStorage *throw*, not
    return null. A colour preference is never worth a broken page."""
    assert THEME_JS.count("try {") >= 2
    assert "catch" in THEME_JS


def test_the_choice_includes_going_back_to_following_the_phone():
    """A two-state toggle cannot express "automatic", so once you picked one
    you could never get back to the default. Three buttons, and the empty
    value is the one that removes the attribute."""
    assert 'data-theme-choice=""' in SETTINGS
    assert 'data-theme-choice="light"' in SETTINGS
    assert 'data-theme-choice="dark"' in SETTINGS


def test_the_dark_map_filter_follows_the_choice_too():
    """The tile filter is a theme rule like any other. Left behind, a chosen
    dark page would sit under a bright white map -- which is how a missed
    rule announces itself."""
    assert ':root[data-theme="dark"] .map:not(.tiles-dark) .leaflet-tile-pane' in CSS
