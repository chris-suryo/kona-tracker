"""Four things a visual audit found on 2026-09-13 that tests had not.

Three of them were introduced by the live-map and walk-button work earlier
the same day, which is the useful part: every one passed CI, and every one
was visible to anyone who opened the page. They are pinned here so the next
pass cannot reintroduce them quietly.

The fourth predates that work: a ring that printed "0%" whether she had not
moved yet or no collar was configured at all.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.parse import ActivityStats, CollarStatus
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.app import HERE, create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views import step_ring

NOW = datetime(2026, 9, 13, 16, 27, tzinfo=UTC)
CSS = (HERE / "static" / "app.css").read_text(encoding="utf-8")


def _client(fi=None) -> TestClient:
    app = create_app(
        Settings(passcode="4242", secret="test-secret"),
        source_factory=lambda: FakeSource(fps=100),
        fi_service=fi,
    )
    client = TestClient(app)
    client.__enter__()
    client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
    return client


class StubFi:
    def __init__(self, snapshot: FiSnapshot):
        self._snapshot = snapshot

    def snapshot(self, force: bool = False) -> FiSnapshot:
        return self._snapshot

    def peek(self) -> FiSnapshot:
        return self._snapshot

    def live_state(self) -> dict:
        return {"live": False, "seconds_left": 0, "every_seconds": 20}


def test_the_reduced_motion_block_is_last_in_the_stylesheet():
    """The convention exists because rules added after it are not covered by
    it. The old test only sliced forwards from the media query, so appending
    86 lines of live-map CSS after it broke the convention while the test
    went on passing -- the new rules were inside the slice without being
    governed by it. This asserts the position, which is the actual rule."""
    start = CSS.index("@media (prefers-reduced-motion: reduce)")
    # Walk to the brace that closes the media query, then assert nothing but
    # whitespace follows it. Asserting the *position* is the actual rule;
    # the old test only sliced forwards from here, which any amount of
    # appended CSS satisfies.
    depth = 0
    end = None
    for index in range(start, len(CSS)):
        if CSS[index] == "{":
            depth += 1
        elif CSS[index] == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    assert end is not None, "the reduced-motion block never closes"
    assert CSS[end:].strip() == "", "CSS was appended after the reduced-motion block"


def test_the_live_map_panels_obey_the_hidden_attribute():
    """`display: grid` outranks the browser's own [hidden] rule, so panels
    the server had marked hidden still drew a dash on an empty map."""
    for selector in (
        "live-stat",
        "live-walk",
        "live-recentre",
        "live-note",
        "drive-alarm",
        # The alarm's own containment -- which is what actually failed, and
        # which a [hidden] guard cannot express -- is pinned next to the
        # gateway fixture it needs, in
        # test_robot_drive.py::test_the_stop_alarm_is_not_inside_the_half_that_portrait_hides
        # Added 2026-09-15. `.live-map` was the dangerous one: `.map[hidden]`
        # reads as if it covers it and does not, and the element is already
        # position:absolute inset:0 -- one `display:` away from covering the
        # "map unavailable" message with a blank full-screen map.
        "live-map",
        "live-map-empty",
        "drive-note",
    ):
        assert re.search(rf"\.{selector}\[hidden\][^{{]*{{[^}}]*display:\s*none", CSS), selector


def test_preview_never_links_into_the_real_collar():
    """`/map` reads the real collar. In sample-data mode the "Open full map"
    link led straight out of the fiction and into an empty real map, with
    nothing saying the preview had ended."""
    client = _client()
    preview = client.get("/activity?preview=1").text
    assert "Sample data preview" in preview
    assert 'href="/map"' not in preview
    # Every other way out of preview stays labelled.
    assert "from_preview=1" in preview
    client.__exit__(None, None, None)


def test_the_ring_tells_no_steps_yet_apart_from_no_collar():
    """Both used to print "0%" in the middle of an empty ring. Only one of
    them is a measurement."""
    not_moved = step_ring(0, 28_000)
    assert not_moved["known"] is True and not_moved["percent"] == 0

    for unknown in (step_ring(None, 28_000), step_ring(3_000, None), step_ring(3_000, 0)):
        assert unknown["known"] is False
        assert unknown["percent"] is None
        assert unknown["arc"] == 0.0


def test_an_unconfigured_page_shows_a_dash_rather_than_a_percentage():
    client = _client()
    page = client.get("/activity").text
    assert "Goal progress unavailable" in page
    assert "0%" not in page
    client.__exit__(None, None, None)


def test_a_real_zero_still_prints_zero_percent():
    """The morning before she has moved is a fact about Kona, and the page
    is allowed to state it."""
    snapshot = FiSnapshot(
        fetched_at=NOW,
        activity=ActivityStats(steps=0, step_goal=28_000, distance=0),
        status=CollarStatus(),
    )
    client = _client(StubFi(snapshot))
    page = client.get("/activity").text
    assert "0%" in page
    assert "Goal progress unavailable" not in page
    client.__exit__(None, None, None)


def test_the_stylesheet_covers_the_controls_added_with_the_live_map():
    """A reduced-motion user should not get the transitions that shipped
    with the walk button and the map's recentre control."""
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)") :]
    for selector in (".walk-toggle", ".live-recentre"):
        assert selector in block, selector
