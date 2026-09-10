"""Regression coverage for privacy, independent queries, and report evidence."""

import json

import httpx
import pytest
from conftest import fake_fi_handler
from typer.testing import CliRunner

from kona_tracker.cli import app
from kona_tracker.fi.client import FiClient, FiError, FiLoginError
from kona_tracker.probe.run import _metric_lines, run_probe


def test_login_response_body_never_enters_error():
    def handler(request):
        return httpx.Response(401, json={"error": {"sessionId": "private-session"}})

    with FiClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(FiLoginError) as exc:
            client.login("private-email", "private-password")
        assert "private-" not in str(exc.value)


def test_errors_are_safe_in_reports_and_timeout_does_not_stop_activity(tmp_path):
    def handler(request):
        if request.url.path == "/graphql":
            query = json.loads(request.content)["query"]
            if "KonaRest" in query:
                raise httpx.ReadTimeout("private-password", request=request)
            if "KonaSpeculative" in query:
                return httpx.Response(
                    200,
                    json={
                        "errors": [
                            {
                                "message": "denied for private-email, session=private-session",
                                "extensions": {"token": "private-token"},
                            }
                        ]
                    },
                )
        return fake_fi_handler(request)

    with FiClient(transport=httpx.MockTransport(handler)) as client:
        client.login("chris@example.com", "correct")
        report = run_probe(client, tmp_path)
    assert "rest:kona" in report.errors
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "totalSteps=4210" in summary
    for path in report.files:
        assert "private-" not in path.read_text(encoding="utf-8")


def test_summary_includes_returned_values_without_guessing_units(fake_client, tmp_path):
    fake_client.login("chris@example.com", "correct")
    run_probe(fake_client, tmp_path)
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    for value in (
        "SLEEP duration=30600",
        "NAP duration=5400",
        "totalSteps=4210",
        "stepGoal=9000",
        "totalDistance=3120.5",
        "2026-09-09",
        "raw API units",
        "remain unconfirmed",
    ):
        assert value in summary


def test_null_and_zero_are_distinct():
    lines = _metric_lines("activity", {"pet": {"dailyStat": {"totalSteps": 0}}}, "kona")
    assert "totalSteps=0" in lines[0]
    assert "stepGoal=unavailable" in lines[0]
    lines = _metric_lines(
        "rest", {"pet": {"dailyStat": {"restSummaries": [{"data": None}]}}}, "kona"
    )
    assert all("duration=unavailable" in line for line in lines)


def test_login_network_failure_is_clean_cli_error(monkeypatch):
    def fail(self, email, password):
        raise FiError("Fi login connection failed; check connectivity and try again.")

    monkeypatch.setenv("FI_EMAIL", "fake-email")
    monkeypatch.setenv("FI_PASSWORD", "fake-password")
    monkeypatch.setattr(FiClient, "login", fail)
    result = CliRunner().invoke(app, ["probe"])
    assert result.exit_code == 1
    assert "connection failed" in result.output
    assert "fake-password" not in result.output


@pytest.mark.parametrize("operation", ["KonaPets", "KonaIntrospect", "KonaSpeculative"])
def test_other_step_timeouts_still_save_summary(operation, tmp_path):
    def handler(request):
        if request.url.path == "/graphql" and operation in json.loads(request.content)["query"]:
            raise httpx.ConnectError("private-address", request=request)
        return fake_fi_handler(request)

    with FiClient(transport=httpx.MockTransport(handler)) as client:
        client.login("chris@example.com", "correct")
        report = run_probe(client, tmp_path)
    assert report.errors
    assert (tmp_path / "summary.md").exists()
    assert "private-address" not in (tmp_path / "summary.md").read_text()
