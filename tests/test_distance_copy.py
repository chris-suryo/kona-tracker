"""Distance is allowed on the page only because it is labelled.

`docs/device-capabilities.md` kept Fi's distance out of the UI for weeks while
nobody could explain a day with 3,383 steps and zero miles. Fi's own assistant
resolved it -- distance is GPS and accrues only outdoors, steps come from the
accelerometer and are counted everywhere -- and the doc lifted the block with
two conditions attached:

> that block is now lifted, provided it is **labelled as outdoor or walk
> distance** and **a zero is never presented as "she did not move"**.

We shipped it bare anyway: "46,725 ... of 28,000 - 167% of today's goal - 0.6
mi - checked Fi 11:08 pm", where the "0.6 mi" reads as one of those two
numbers being wrong. These tests exist so that condition is enforced by
something other than a document nobody re-reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kona_tracker.web.views import DISTANCE_NOTE, distance_label, outdoor_distance

STEPS_HTML = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "kona_tracker"
    / "web"
    / "templates"
    / "steps.html"
).read_text()


@pytest.mark.parametrize("metres", [1, 100, 500, 1609, 6449, 42000])
def test_every_non_zero_distance_says_what_kind_of_distance_it_is(metres):
    assert outdoor_distance(metres).endswith(" outdoors")


def test_a_zero_is_words_and_not_a_measurement():
    """The second condition. "0 ft" beside five figures of steps says she was
    still, which is false: it says she did not leave the house."""
    said = outdoor_distance(0)
    assert "0 ft" not in said
    assert "outdoor" in said.lower()


def test_an_absent_reading_stays_absent():
    """None is "Fi did not tell us", which is not the same as zero and must
    not be rendered as one."""
    assert outdoor_distance(None) is None
    assert outdoor_distance(-1) is None


def test_the_underlying_number_is_untouched():
    """The label is the only thing this adds. A units bug hiding behind a
    wording change would be a bad trade."""
    assert outdoor_distance(6449).startswith(distance_label(6449))


def test_the_note_names_both_measurements_and_blames_neither():
    """The reader's question is "which of these two numbers is wrong?", and
    the answer is neither. The sentence has to say what each one measures or
    it does not do its job."""
    lowered = DISTANCE_NOTE.lower()
    assert "gps" in lowered
    assert "step" in lowered
    assert "indoor" in lowered


def test_the_page_shows_the_note_exactly_when_it_shows_a_distance():
    """Shown without the distance it is a non-sequitur; the distance shown
    without it is the thing the doc forbids. They are one unit."""
    # Both appear inside the same `{% if distance %}` discipline: count them.
    assert STEPS_HTML.count("{% if distance %}") == 2
    assert "distance_note" in STEPS_HTML


def test_the_hero_is_no_longer_one_run_on_paragraph():
    """Five facts joined by middots wrapped to three lines on a phone and
    read as a sentence. Each line is its own element now."""
    for cls in ("total-lead", "total-aside", "total-checked", "total-explain"):
        assert f'class="{cls}"' in STEPS_HTML, f"{cls} is gone; the hero has regressed"
