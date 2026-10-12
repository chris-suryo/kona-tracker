"""Settings' Collar and This server lists.

They answer "is everything working?" in words, from state the server already
holds. What is pinned here: each state reads differently, the bad ones are
flagged, nothing reveals a full path, and opening Settings asks Fi nothing.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from conftest import fake_fi_handler
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.store.recorder import Recorder
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings
from kona_tracker.web.views.system import ago, collar_rows, size_label, system_rows

NOW = datetime(2026, 10, 12, 15, 0, tzinfo=UTC)
OK = {"camera": "live", "fi": "ok", "fi_age_s": 240}


class Beat:
    sent, failures = 12, 0


def test_ages_and_sizes_read_like_a_person_would_say_them():
    assert [ago(s) for s in (5, 240, 7200, 3 * 86400)] == [
        "just now",
        "4 min ago",
        "2 h ago",
        "3 days ago",
    ]
    assert size_label(800) == "1 KB" and size_label(3 * 1024 * 1024 + 200_000) == "3.2 MB"


def test_a_healthy_server_reads_as_healthy_and_nothing_is_flagged():
    rec = {"state": "recording", "file": "kona.db", "size_bytes": 2 * 1024 * 1024}
    rows = system_rows(OK, rec, Beat(), NOW - timedelta(hours=5), NOW)
    words = {r["label"]: r["value"] for r in rows}
    assert words == {
        "Camera": "Live",
        "Fi": "Checked 4 min ago",
        "Recording": "On · kona.db · 2.0 MB",
        "Heartbeat": "On · 12 sent",
        "Server": "Started 5 h ago",
    }
    assert not any(r["warn"] for r in rows)


def test_every_failure_is_flagged_and_says_what_to_do():
    health = {"camera": "disconnected", "fi": "stale", "fi_age_s": 3 * 3600}
    paused = {"state": "paused", "file": "kona.db", "size_bytes": None}
    beat = Beat()
    beat.failures = 3
    rows = {r["label"]: r for r in system_rows(health, paused, beat, None, NOW)}
    assert rows["Camera"]["warn"] and rows["Camera"]["value"] == "Not connected"
    assert rows["Fi"]["value"] == "Not answering · last good reading 3 h ago" and rows["Fi"]["warn"]
    assert rows["Recording"]["value"].startswith("Paused") and rows["Recording"]["warn"]
    assert rows["Heartbeat"]["value"] == "On · 12 sent, 3 failed" and rows["Heartbeat"]["warn"]
    off = {r["label"]: r for r in system_rows(OK, None, None, None, NOW)}
    assert off["Recording"]["value"] == "Off · KONA_DB_PATH is blank" and off["Recording"]["warn"]
    assert off["Heartbeat"]["value"] == "Off" and "Server" not in off


def test_the_recorder_reports_its_file_by_name_never_its_folder(tmp_path):
    db = tmp_path / "private-folder" / "kona.db"
    status = Recorder(str(db)).status()
    assert status == {"state": "recording", "file": "kona.db", "size_bytes": None}
    db.parent.mkdir()
    db.write_bytes(b"x" * 5000)
    status = Recorder(str(db)).status()
    assert status["size_bytes"] == 5000 and "private-folder" not in repr(status)


def _service():
    import httpx

    from kona_tracker.fi.client import FiClient
    from kona_tracker.fi.service import FiService

    def make_client():
        return FiClient(transport=httpx.MockTransport(fake_fi_handler))

    return FiService("chris@example.com", "correct", client_factory=make_client)


def test_collar_rows_say_charger_light_and_next_report_but_not_the_battery():
    snap = _service().snapshot()
    rows = {r["label"]: r for r in collar_rows(snap)}
    # The percentage is in the Activity header; Settings does not repeat it.
    assert "Battery" not in rows
    assert rows["Charger"]["value"] == "On the charger"
    assert rows["Light"]["value"] == "Off"
    due = snap.fetched_at + timedelta(minutes=20)
    ahead = replace(snap, status=replace(snap.status, next_update=due))
    assert {r["label"]: r for r in collar_rows(ahead)}["Next report"]["value"].startswith(
        "Expected by "
    )
    late = replace(
        snap, status=replace(snap.status, next_update=snap.fetched_at - timedelta(hours=2))
    )
    overdue = {r["label"]: r for r in collar_rows(late)}["Next report"]
    assert overdue["value"].startswith("Overdue · was expected ") and overdue["warn"]
    assert collar_rows(None) == []


def test_settings_shows_both_lists_and_never_asks_fi_itself():
    calls = []

    def counting(request):
        calls.append(request.url.path)
        return fake_fi_handler(request)

    import httpx

    from kona_tracker.fi.client import FiClient
    from kona_tracker.fi.service import FiService

    svc = FiService(
        "chris@example.com",
        "correct",
        client_factory=lambda: FiClient(transport=httpx.MockTransport(counting)),
    )
    app = create_app(
        Settings(passcode="4242", secret="s"),
        source_factory=lambda: FakeSource(fps=100),
        fi_service=svc,
    )
    with TestClient(app) as c:
        c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
        page = c.get("/settings").text
        assert calls == [], "opening Settings must not make this server ask Fi"
        assert "This server" in page and "<dt>Camera</dt>" in page and "<dt>Fi</dt>" in page
        assert "Not asked yet" in page
        assert 'id="collar-title"' not in page, "no reading held: no collar list"
        c.get("/activity")
        page = c.get("/settings").text
        assert 'id="collar-title"' in page and "<dt>Charger</dt>" in page
