"""The camera's switches -- night vision, privacy mode, the LED -- from the
driver up to the page. pytapo talks to a real Tapo; here it is a fake that
records calls and answers in pytapo's own shapes, so the driver is tested
against what the library returns rather than what we hope it returns."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kona_tracker.camera.capabilities import TAPO_FIXED, TAPO_PAN_TILT, USB
from kona_tracker.camera.control import ControlUnsupported, FakeControl, NoControl, parse_setting
from kona_tracker.camera.source import FakeSource
from kona_tracker.camera.tapo import TapoControl, TapoError
from kona_tracker.web.app import create_app, default_control
from kona_tracker.web.settings import Settings


class FakePytapo:
    """Answers like pytapo 3.4: switches come back as {"enabled": "on"}."""

    def __init__(self, host, user, password, cloud_password=""):
        self.host, self.user, self.password = host, user, password
        #: pytapo takes it separately but does not log in with it.
        self.cloud_password = cloud_password
        self.calls: list[tuple] = []
        self.night = "auto"
        self.privacy = False
        self.led = True
        self.fail_next = False

    def _maybe_fail(self):
        if self.fail_next:
            self.fail_next = False
            raise Exception(f"Error Code: -40401, camera said no to {self.password}")

    def getDayNightMode(self):
        self.calls.append(("getDayNightMode",))
        self._maybe_fail()
        return self.night

    def setDayNightMode(self, mode):
        self.calls.append(("setDayNightMode", mode))
        self.night = mode

    def getPrivacyMode(self):
        self.calls.append(("getPrivacyMode",))
        return {"enabled": "on" if self.privacy else "off"}

    def setPrivacyMode(self, enabled):
        self.calls.append(("setPrivacyMode", enabled))
        self.privacy = enabled

    def getLED(self):
        self.calls.append(("getLED",))
        return {"enabled": "on" if self.led else "off"}

    def setLEDEnabled(self, enabled):
        self.calls.append(("setLEDEnabled", enabled))
        self.led = enabled


def _tapo(model=TAPO_FIXED):
    made = []

    def factory(host, user, password, cloud_password=""):
        client = FakePytapo(host, user, password, cloud_password)
        made.append(client)
        return client

    return (
        TapoControl(
            "10.0.0.111",
            "admin",
            "cloud-secret",
            model,
            client_factory=factory,
            cloud_password="tp-link-secret",
        ),
        made,
    )


def test_form_values_become_typed_settings_or_a_clear_refusal():
    assert parse_setting("night", "Auto") == "auto"
    assert parse_setting("privacy", "on") is True and parse_setting("led", "OFF") is False
    with pytest.raises(ControlUnsupported):
        parse_setting("night", "dim")
    with pytest.raises(ControlUnsupported):
        parse_setting("alarm", "on")


def test_tapo_connects_on_first_use_not_at_construction():
    control, made = _tapo()
    assert made == [], "the server must come up whether or not the camera is reachable"
    assert control.settings() == {"night": "auto", "privacy": False, "led": True}
    assert len(made) == 1 and made[0].host == "10.0.0.111" and made[0].user == "admin"
    assert control.settings() and len(made) == 1, "one session, reused"


def test_tapo_applies_a_change_and_reports_the_camera_s_own_state_back():
    control, made = _tapo()
    state = control.apply("night", "on")
    assert state["night"] == "on"
    assert ("setDayNightMode", "on") in made[0].calls
    assert control.apply("privacy", "on")["privacy"] is True
    assert ("setPrivacyMode", True) in made[0].calls
    assert control.apply("led", "off")["led"] is False
    assert ("setLEDEnabled", False) in made[0].calls


def test_tapo_advertises_only_the_switches_and_never_motion():
    control, _ = _tapo(TAPO_PAN_TILT)
    caps = control.capabilities
    assert caps.night_vision and caps.privacy and caps.led
    assert not caps.ptz and not caps.presets and not caps.alarm and not caps.motion
    assert control.model_capabilities.ptz, "the model can pan; we just do not drive it"
    with pytest.raises(ControlUnsupported):
        control.move(pan=0.1)
    with pytest.raises(ControlUnsupported):
        control.apply("alarm", "on")


def test_a_failed_call_scrubs_the_password_and_forgets_the_session():
    control, made = _tapo()
    control.settings()
    made[0].fail_next = True
    with pytest.raises(TapoError) as exc:
        control.settings()
    assert "cloud-secret" not in str(exc.value) and "***" in str(exc.value)
    # The camera's session token rides in the request URL that requests
    # echoes on a connection error; it must not reach a log line either.
    assert control._scrub("HTTPSConnectionPool: https://10.0.0.111/stok=AbC123xyz/ds failed") == (
        "HTTPSConnectionPool: https://10.0.0.111/stok=***/ds failed"
    )
    assert control.settings()["night"] == "auto"
    assert len(made) == 2, "logged in again after the failure"


def test_a_camera_with_no_switches_offers_nothing():
    control, made = _tapo(USB)
    assert control.settings() == {} and made == []


def test_default_control_picks_tapo_only_with_a_password_and_a_tapo_model():
    base = dict(
        passcode="4242", secret="s", camera_source="rtsp", rtsp_url="rtsp://10.0.0.111:554/stream1"
    )
    assert isinstance(default_control(Settings(**base, camera_model="c120")), NoControl)
    with_pw = default_control(Settings(**base, camera_model="c120", tapo_password="pw"))
    assert isinstance(with_pw, TapoControl) and repr(with_pw) == "TapoControl(10.0.0.111)"
    assert "pw" not in repr(Settings(**base, camera_model="c120", tapo_password="pw"))
    # A model we cannot name gets no switches, password or not.
    assert isinstance(
        default_control(Settings(**base, camera_model="", tapo_password="pw")), NoControl
    )


def _app(control, model="c120", source="fake"):
    settings = Settings(passcode="4242", secret="s", camera_source=source, camera_model=model)
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100), control=control)
    c = TestClient(app)
    c.post("/login", data={"passcode": "4242"}, follow_redirects=False)
    return app, c


def test_the_page_offers_the_switches_only_when_the_driver_does():
    app, c = _app(FakeControl())
    with c:
        html = c.get("/camera").text
        assert 'id="cam-settings"' in html and 'data-setting="night"' in html
        assert 'data-setting="privacy"' in html and 'data-setting="led"' in html
    app.state.hub.stop()
    app, c = _app(NoControl(TAPO_FIXED), source="rtsp")
    with c:
        html = c.get("/camera").text
        assert 'id="cam-settings"' not in html, "no password, no driver, no dead switches"
        assert c.get("/control/settings").status_code == 409
        assert c.post("/control/setting", data={"name": "led", "value": "on"}).status_code == 409
    app.state.hub.stop()


def test_settings_round_trip_through_the_routes():
    app, c = _app(FakeControl())
    with c:
        assert c.get("/control/settings").json() == {
            "settings": {"night": "auto", "privacy": False, "led": True}
        }
        r = c.post("/control/setting", data={"name": "privacy", "value": "on"})
        assert r.status_code == 200 and r.json()["settings"]["privacy"] is True
        bad = c.post("/control/setting", data={"name": "night", "value": "dim"})
        assert bad.status_code == 409 and "must be one of" in bad.json()["error"]
    app.state.hub.stop()


def test_a_camera_that_does_not_answer_is_a_502_with_a_safe_message():
    control, made = _tapo()
    app, c = _app(control, source="rtsp")
    with c:
        assert c.get("/control/settings").status_code == 200
        made[0].fail_next = True
        r = c.get("/control/settings")
        assert r.status_code == 502 and "cloud-secret" not in r.text
    app.state.hub.stop()


def test_settings_routes_are_behind_the_passcode():
    settings = Settings(passcode="4242", secret="s", camera_source="fake")
    app = create_app(settings, source_factory=lambda: FakeSource(fps=100))
    with TestClient(app) as c:
        assert c.get("/control/settings", follow_redirects=False).status_code == 303
        assert (
            c.post(
                "/control/setting", data={"name": "led", "value": "on"}, follow_redirects=False
            ).status_code
            == 303
        )
    app.state.hub.stop()


def test_both_credentials_reach_the_camera_and_neither_ever_leaks():
    """Whatever is configured is passed through untouched, and neither value
    can survive into an error string. The login itself uses only `password`
    (see camera/tapo.py); this pins the plumbing and the scrubbing, not a
    theory about which one the camera wants."""
    control, made = _tapo()
    control.settings()
    assert made[0].password == "cloud-secret"
    assert made[0].cloud_password == "tp-link-secret"
    # Either one appearing in an error string would outlive the error.
    scrubbed = control._scrub("login failed for cloud-secret / tp-link-secret")
    assert "cloud-secret" not in scrubbed
    assert "tp-link-secret" not in scrubbed
    assert scrubbed.count("***") == 2


def test_the_docs_agree_on_how_the_switches_log_in():
    """They did not, and it cost a camera lockout.

    On 2026-09-30 `.env.example` said `admin` + the TP-Link password while
    `docs/first-run.md` said the camera account + a cloud password. The second
    was an untested theory from 2026-09-13; following it failed, and every
    failed login counts towards the camera locking out its control API for
    half an hour. `admin` + the TP-Link password is what worked -- the first
    time the switches were ever seen working -- so both documents must say
    that and neither may say the other.
    """
    from pathlib import Path  # noqa: PLC0415 - test-only

    root = Path(__file__).resolve().parent.parent
    for name in (".env.example", "docs/first-run.md"):
        text = (root / name).read_text(encoding="utf-8")
        assert "KONA_TAPO_USER=admin" in text, f"{name} must say to log in as admin"
        assert "KONA_TAPO_USER=<the camera account" not in text, f"{name} revived the old theory"
