import pytest

from kona_tracker.camera.redact import redact_url, split_credentials, with_credentials
from kona_tracker.probe.redact import REDACTED, redact


def test_redacts_identity_and_location_but_keeps_measurements():
    raw = {
        "email": "chris@example.com",
        "sessionId": "abc",
        "position": {"latitude": 1.0, "longitude": 2.0},
        "sleepAmounts": [{"type": "SLEEP", "duration": 30600}],
        "totalSteps": 4210,
        "name": "Kona",
        "placeName": None,
    }
    out = redact(raw)
    assert out["email"] == REDACTED
    assert out["sessionId"] == REDACTED
    assert out["position"] == REDACTED
    assert out["sleepAmounts"] == [{"type": "SLEEP", "duration": 30600}]
    assert out["totalSteps"] == 4210
    assert out["name"] == "Kona"
    assert out["placeName"] is None  # nothing to hide, stays None so shape is visible
    assert raw["email"] == "chris@example.com"  # input untouched


@pytest.mark.parametrize(
    "text, expected",
    [
        ("rtsp://kona:hunter2@10.0.0.9:554/stream1", "rtsp://***@10.0.0.9:554/stream1"),
        ("open failed: rtsp://u:p%40ss@cam/x (timeout)", "open failed: rtsp://***@cam/x (timeout)"),
        ("http://user@host/", "http://***@host/"),
        ("rtsp://10.0.0.9:554/stream1", "rtsp://10.0.0.9:554/stream1"),
        ("no url here", "no url here"),
        # the shapes a strict regex got wrong (security review 2026-09-10)
        ("could not open //kona:hunter2@/10.0.0.9:554/s", "could not open //***@/10.0.0.9:554/s"),
        ("rtsp://kona:sec/ret@10.0.0.9:554/stream1", "rtsp://***@10.0.0.9:554/stream1"),
        (
            "rtsp://kona:p@ss@[fe80::1]:554/s and rtsp://a:b@h/x",
            "rtsp://***@[fe80::1]:554/s and rtsp://***@h/x",
        ),
    ],
)
def test_redact_url(text, expected):
    assert redact_url(text) == expected


def test_split_handles_raw_slash_in_password_and_ipv6():
    assert split_credentials("rtsp://kona:sec/ret@10.0.0.9:554/stream1") == (
        "rtsp://10.0.0.9:554/stream1",
        "kona",
        "sec/ret",
    )
    url = with_credentials("rtsp://[fe80::1]:554/s?x=1", "u", "p@w")
    assert url == "rtsp://u:p%40w@[fe80::1]:554/s?x=1"
    assert split_credentials(url) == ("rtsp://[fe80::1]:554/s?x=1", "u", "p@w")
    with pytest.raises(ValueError):
        with_credentials("10.0.0.9:554/stream1", "u", "p")


def test_credentials_round_trip_with_special_characters():
    url = with_credentials("rtsp://cam.local:554/stream1", "kona", "p@ss:w/rd #1")
    assert "p@ss" not in url and "%40" in url
    bare, user, password = split_credentials(url)
    assert (bare, user, password) == ("rtsp://cam.local:554/stream1", "kona", "p@ss:w/rd #1")
    assert split_credentials("rtsp://cam.local:554/stream1") == (
        "rtsp://cam.local:554/stream1",
        "",
        "",
    )
    assert with_credentials("rtsp://cam.local/x", "", "") == "rtsp://cam.local/x"
