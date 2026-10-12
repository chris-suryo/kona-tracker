"""The faint text colour has to stay readable, in both themes.

`--ink3` is every small label in the app: the "Checked Fi" lines, the
build stamp, the camera hint, the PASSCODE caption on the login page. Its
comment once said the dark theme was "comfortably above AA" while it
measured 3.07:1. A number in a comment is a claim; this holds it.
"""

import re

import pytest

from kona_tracker.web.app import HERE

CSS = (HERE / "static" / "app.css").read_text(encoding="utf-8")
AA_TEXT = 4.5


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _themes() -> dict[str, dict[str, str]]:
    """Every block that sets --ink3, with the --bg and --ink2 beside it."""
    themes = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*--ink3:[^{}]*)\}", CSS):
        tokens = dict(re.findall(r"--(bg|ink2|ink3):\s*(#[0-9A-Fa-f]{6})", body))
        themes[selector.strip()] = tokens
    return themes


def test_every_theme_that_sets_the_faint_colour_was_found():
    # Light (:root), dark by the phone's setting, and dark by choice.
    assert len(_themes()) == 3, list(_themes())


@pytest.mark.parametrize("selector", sorted(_themes()))
def test_faint_text_meets_aa_and_stays_fainter_than_secondary(selector):
    t = _themes()[selector]
    faint = _ratio(t["ink3"], t["bg"])
    assert faint >= AA_TEXT, f"{selector}: --ink3 is {faint:.2f}:1 against --bg"
    # Lifting it must not erase the hierarchy: --ink3 is the quieter one.
    assert faint < _ratio(t["ink2"], t["bg"]), selector
