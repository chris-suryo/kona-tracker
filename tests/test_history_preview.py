"""Sample history must stay private, explicitly fictional and internally consistent."""

import re

import pytest
from fastapi.testclient import TestClient

from kona_tracker.web.app import create_app
from kona_tracker.web.history_preview import history_preview
from kona_tracker.web.settings import Settings


@pytest.mark.parametrize("metric", ["steps", "rest"])
def test_history_totals_and_missing_values(metric):
    day = history_preview(metric, "day", 0, 2)
    assert day["total"] == sum(b["value"] or 0 for b in day["buckets"])
    assert all(b["value"] is None and b["future"] for b in day["buckets"][11:])
    missing = history_preview(metric, "day", 2, 14)
    assert missing["chosen"]["value"] is None
    assert not missing["chosen"]["future"]
    week = history_preview(metric, "week", 0, None)
    assert week["total"] == sum(history_preview(metric, "day", d, None)["total"] for d in range(7))
    if metric == "rest":
        assert day["total"] == day["sleep_total"] + day["nap_total"]
    else:
        assert day["chosen"]["value"] == 0


def test_preview_is_gated_and_never_queries_fi():
    class NoFi:
        def snapshot(self, **kwargs):
            raise AssertionError("A sample page must not fetch live data")

    app = create_app(Settings(passcode="4242", secret="test"), fi_service=NoFi())
    with TestClient(app) as client:
        assert client.get("/preview/steps", follow_redirects=False).status_code == 303
        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        for path in (
            "/preview/steps",
            "/preview/rest?period=week",
            "/preview/steps?day=2&selected=14",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "Fictional readings, not Kona's history." in response.text
            assert not re.search(r"\s(?:on[a-z]+|style)\s*=", response.text)
            assert "script-src 'self'" in response.headers["content-security-policy"]
        assert "No reading" in response.text
        assert client.get("/preview/steps?day=100").status_code == 422
        assert client.get("/preview/steps?selected=-1").status_code == 422
        assert client.get("/preview/unknown").status_code == 404
        assert client.get("/preview/steps?period=year").status_code == 404


def test_sample_overview_and_drilldown_agree_and_bars_fit():
    from kona_tracker.web.views import preview_activity_context

    overview = preview_activity_context()
    assert overview["steps"] == "7,420"
    for day in range(7):
        for metric in ("steps", "rest"):
            context = history_preview(metric, "day", day, None)
            assert all(0 <= b["height"] <= 150 for b in context["buckets"])
            if metric == "rest":
                interval_minutes = sum(i["width"] * 1440 / 340 for i in context["intervals"])
                assert interval_minutes == pytest.approx(context["total"])


def test_weekly_rest_average_excludes_missing_and_in_progress_days():
    context = history_preview("rest", "week", 0, None)
    complete = [b for b in context["buckets"] if not b["partial"]]
    assert context["complete_days"] == 5
    assert context["average"] == round(sum(b["value"] for b in complete) / 5)
    assert context["average"] != round(context["total"] / 7)


def test_overview_charts_are_sample_only():
    app = create_app(Settings(passcode="4242", secret="test"))
    with TestClient(app) as client:
        client.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        sample = client.get("/activity?preview=1").text
        live = client.get("/activity").text
        assert "Steps by hour" not in sample and "Rest by hour" not in sample
        assert (
            sample.index('class="steps-hero')
            < sample.index('class="rest-grid')
            < sample.index('class="location-card')
        )
        assert "Steps by hour" not in live and "/preview/steps" not in live
        assert "Explore sample steps" not in sample
        detail = client.get("/preview/steps").text
        assert "View readings" in detail and "Explore rest" not in detail
