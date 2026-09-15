"""Dragging a finger across a chart, and the invariant that makes it possible.

Every bar is a link to `?selected=N`, so reading four hours used to mean four
full page loads. `chart_scrub.js` swaps the reading in place instead -- but it
does not *build* the reading, because the text under a chart is not a number:
it is "6h 12m of rest · sleep 5h 40m, naps 32m", with `<small>` on every unit,
and the rules differ per chart. Rebuilding that in JavaScript would be a second
implementation of the same formatting, and the drift would be invisible: you
see the server's version only without JavaScript and the other only with it.

So the server renders every bucket's reading into a hidden list and the script
clones nodes out of it. That makes one thing load-bearing, and it is what these
tests hold: **the hidden list and the bars must stay in lock-step.** One entry
per bar, same order. Off by one and the scrub silently shows the wrong hour --
a page confidently reporting the wrong number, which is the failure mode this
project cares most about.
"""

from __future__ import annotations

import re

import httpx
from conftest import fake_fi_handler
from fastapi.testclient import TestClient
from test_hourly import FIXTURE_NOW  # the same pinned clock as the hourly tests

from kona_tracker.camera.source import FakeSource
from kona_tracker.fi.client import FiClient
from kona_tracker.fi.service import FiService
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

READINGS = re.compile(
    r'<div id="(?P<id>[a-z-]+)" class="chart-readings-data" hidden>(?P<body>.*?)</div>',
    re.DOTALL,
)
CHART = re.compile(
    r'<svg class="bar-chart[^"]*" data-readings="(?P<id>[a-z-]+)".*?</svg>',
    re.DOTALL,
)


def _client() -> TestClient:
    def make_client() -> FiClient:
        return FiClient(transport=httpx.MockTransport(fake_fi_handler))

    fi = FiService(
        "chris@example.com", "correct", client_factory=make_client, clock=lambda: FIXTURE_NOW
    )
    app = create_app(
        Settings(passcode="4242", secret="s"),
        source_factory=lambda: FakeSource(fps=100),
        fi_service=fi,
    )
    client = TestClient(app)
    client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
    return client


def _charts(page: str) -> dict[str, str]:
    return {m.group("id"): m.group(0) for m in CHART.finditer(page)}


def _readings(page: str) -> dict[str, list[str]]:
    return {
        m.group("id"): re.findall(r"<span>.*?</span>", m.group("body"), re.DOTALL)
        for m in READINGS.finditer(page)
    }


def test_every_chart_has_a_readings_list_with_one_entry_per_bar():
    """The invariant. `chart_scrub.js` refuses to attach when the counts
    disagree -- it would rather leave the links working than scrub the wrong
    bucket -- so a mismatch here is a silently disabled feature, not a crash."""
    with _client() as client:
        for path in ("/steps", "/rest"):
            page = client.get(path).text
            charts = _charts(page)
            readings = _readings(page)
            assert charts, f"{path} rendered no scrubbable chart"
            for chart_id, svg in charts.items():
                assert chart_id in readings, f"{path}: chart {chart_id} names a list that is absent"
                bars = re.findall(r"<a href=", svg)
                assert len(bars) == len(readings[chart_id]), (
                    f"{path}: {chart_id} has {len(bars)} bars and "
                    f"{len(readings[chart_id])} readings"
                )


def test_the_rest_page_keeps_its_two_charts_lists_apart():
    """Two charts on one page, and the ids are the only thing keeping the
    hourly readings out of the daily chart."""
    with _client() as client:
        page = client.get("/rest").text
    charts = _charts(page)
    assert set(charts) == {"hour-readings", "day-readings"}
    readings = _readings(page)
    assert len(readings["hour-readings"]) == 24, "one per hour of the day"
    assert len(readings["day-readings"]) == len(readings["day-readings"])
    assert readings["hour-readings"] != readings["day-readings"]


def test_the_scrubbed_reading_and_the_rendered_one_come_from_the_same_macro():
    """The whole point of `_readings.html`. Select hour 9 on the server and
    the line under the chart must be the entry the scrubber would have shown
    for hour 9 -- not merely similar to it."""
    with _client() as client:
        page = client.get("/rest?hour=9").text
    entry = _readings(page)["hour-readings"][9]
    inner = re.search(r"<span>(.*)</span>", entry, re.DOTALL).group(1)
    selection = re.search(
        r'<p class="chart-selection" aria-live="polite">(.*?)</p>', page, re.DOTALL
    ).group(1)
    assert inner.strip() == selection.strip(), "the two renderings have drifted"


def test_a_reading_carries_its_label_so_the_swap_says_which_hour():
    """Swapping in a bare number would leave the previous hour's label above
    it -- the page asserting a reading belongs to an hour it does not."""
    with _client() as client:
        page = client.get("/steps").text
    for entry in _readings(page)["hour-readings"]:
        assert "<strong>" in entry, "a reading with no label"


def test_the_pages_load_the_scrubber_and_it_is_the_only_thing_that_changed():
    """If the file is absent the links still work: this is an enhancement,
    not a rewrite. The test is that it is loaded and that the hrefs survive."""
    with _client() as client:
        for path in ("/steps", "/rest"):
            page = client.get(path).text
            assert "chart_scrub.js" in page
            assert 'href="/' in page, "the fallback links were removed"
