"""The dead-man's switch: the one alarm that works when the machine does not."""

import json
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.source import FakeSource
from kona_tracker.web.app import create_app
from kona_tracker.web.heartbeat import Heartbeat
from kona_tracker.web.settings import Settings

URL = "https://hc-ping.invalid/2f1b-secret-token"


def test_the_first_ping_goes_out_immediately_not_one_interval_later():
    """A typo in the URL has to show up while you are still sitting there,
    not in five minutes once you have walked away believing it works."""
    sent = []
    beat = Heartbeat(URL, lambda: {"status": "ok"}, 3600, post=lambda *a, **k: sent.append((a, k)))
    beat.start()
    for _ in range(100):
        if sent:
            break
        time.sleep(0.01)
    beat.stop()
    assert len(sent) == 1 and sent[0][0][0] == URL
    assert beat.sent == 1 and beat.failures == 0


def test_the_ping_carries_the_health_summary_so_the_log_shows_what_it_was_doing():
    seen = {}

    def post(url, content=None, timeout=None):
        seen["content"] = content
        seen["timeout"] = timeout

    beat = Heartbeat(URL, lambda: {"camera": "live", "fi": "stale"}, 3600, post=post)
    beat._send()
    assert json.loads(seen["content"]) == {"camera": "live", "fi": "stale"}
    assert seen["timeout"] == 10.0, "a hung request must not sit in front of shutdown"


def test_a_failing_ping_is_logged_loudly_but_never_leaks_the_url(caplog):
    """Whoever holds the ping URL can forge this app's heartbeat and silence
    the alarm that says the house is dark, so it is a secret like any other."""

    def boom(*args, **kwargs):
        raise OSError("network is unreachable")

    beat = Heartbeat(URL, lambda: {"status": "ok"}, 3600, post=boom)
    with caplog.at_level(logging.WARNING, logger="kona_tracker.web"):
        assert beat._send() is False
    assert beat.failures == 1 and beat.sent == 0
    text = caplog.text
    assert "heartbeat ping failed" in text and "OSError" in text
    assert URL not in text and "secret-token" not in text


def test_http_failure_is_not_counted_as_a_success(caplog):
    import httpx

    beat = Heartbeat(URL, lambda: {}, post=lambda *a, **kw: httpx.Response(503))
    assert beat._send() is False
    assert beat.sent == 0 and beat.failures == 1
    assert "503" in caplog.text


def test_exception_containing_ping_url_is_not_logged(caplog):
    def fail(*args, **kwargs):
        raise RuntimeError(f"request failed for {URL}")

    beat = Heartbeat(URL, lambda: {}, post=fail)
    assert beat._send() is False
    assert "RuntimeError" in caplog.text and "secret-token" not in caplog.text


def test_a_broken_summary_still_pings():
    """The point of the signal is its presence. A bug in what it says about
    itself must not become silence, which reads as "the house is down"."""
    sent = []

    def summary():
        raise RuntimeError("status blew up")

    beat = Heartbeat(URL, summary, 3600, post=lambda *a, **k: sent.append(k))
    assert beat._send() is True
    assert sent == [{"content": "", "timeout": 10.0}]


def test_stopping_does_not_wait_out_the_interval():
    beat = Heartbeat(URL, lambda: {}, 3600, post=lambda *a, **k: None)
    beat.start()
    started = time.monotonic()
    beat.stop()
    assert time.monotonic() - started < 2.0, "waits on an event, never sleeps the interval"
    assert not any(t.name == "kona-heartbeat" for t in threading.enumerate())


def test_the_app_runs_no_heartbeat_unless_a_url_is_set():
    app = create_app(
        Settings(passcode="4242", secret="s", camera_source="fake"),
        source_factory=lambda: FakeSource(fps=100),
    )
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert app.state.heartbeat is None
    app.state.hub.stop()


def test_the_heartbeat_sends_exactly_what_healthz_serves(monkeypatch):
    """Two descriptions of the same thing drift. There is only one here."""
    sent = []
    monkeypatch.setattr("httpx.post", lambda url, **kw: sent.append((url, kw["content"])))
    app = create_app(
        Settings(
            passcode="4242",
            secret="s",
            camera_source="fake",
            heartbeat_url=URL,
            heartbeat_seconds=3600,
        ),
        source_factory=lambda: FakeSource(fps=100),
    )
    with TestClient(app) as c:
        served = c.get("/healthz").json()
        for _ in range(100):
            if sent:
                break
            time.sleep(0.01)
    app.state.hub.stop()
    assert sent, "a configured heartbeat pings on startup"
    url, content = sent[0]
    assert url == URL and json.loads(content) == served


def test_the_ping_url_is_masked_in_the_settings_repr():
    s = Settings(passcode="4242", secret="s", heartbeat_url=URL)
    assert URL not in repr(s) and "secret-token" not in repr(s)
    assert "heartbeat='set'" in repr(s) or "heartbeat=set" in repr(s)
    assert "heartbeat=unset" in repr(
        Settings(passcode="4242", secret="s")
    ) or "heartbeat='unset'" in repr(Settings(passcode="4242", secret="s"))


def test_settings_read_the_heartbeat_keys(tmp_path, monkeypatch):
    from kona_tracker.web.settings import load_settings

    for key in ("KONA_HEARTBEAT_URL", "KONA_HEARTBEAT_SECONDS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("KONA_PASSCODE", "123456")
    monkeypatch.setenv("KONA_SECRET", "s")
    s = load_settings(tmp_path / "none.env", fake_camera=True)
    assert s.heartbeat_url == "" and s.heartbeat_seconds == 300.0
    monkeypatch.setenv("KONA_HEARTBEAT_URL", f"  {URL}  ")
    monkeypatch.setenv("KONA_HEARTBEAT_SECONDS", "60")
    s = load_settings(tmp_path / "none.env", fake_camera=True)
    assert s.heartbeat_url == URL and s.heartbeat_seconds == 60.0


@pytest.mark.parametrize("interval", [0.0, -5.0, 1.0])
def test_the_interval_has_a_floor(interval):
    """Nothing a config typo can do should turn this into a request flood."""
    assert Heartbeat(URL, lambda: {}, interval)._interval >= 5.0
