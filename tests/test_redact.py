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


def test_where_kona_lives_and_stands_never_reaches_the_summary():
    """`probe-out/summary.md` gets pasted into chats; it says locations are
    redacted, so they have to actually be."""
    from kona_tracker.probe.redact import REDACTED, redact

    out = redact(
        {
            "pet": {
                "name": "Kona",
                "homeCityState": "Austin, TX",
                "ongoingActivity": {"areaName": "Elm Street Dog Park"},
                "photos": {"first": {"image": {"fullSize": "https://cdn/kona.jpg"}}},
            }
        }
    )
    pet = out["pet"]
    assert pet["name"] == "Kona", "her name is not a secret and is useful"
    assert pet["homeCityState"] == REDACTED
    assert pet["ongoingActivity"]["areaName"] == REDACTED
    assert pet["photos"]["first"]["image"]["fullSize"] == REDACTED


def test_redaction_does_not_eat_the_answer_the_probe_exists_to_find():
    """A bare "state" rule would blank `lastConnectionState` wholesale."""
    from kona_tracker.probe.redact import redact

    out = redact(
        {
            "device": {
                "lastConnectionState": {
                    "__typename": "ConnectedToCellular",
                    "signalStrengthPercent": 72,
                }
            }
        }
    )
    assert out["device"]["lastConnectionState"]["signalStrengthPercent"] == 72


def test_the_exceptions_keep_shape_without_leaking_coordinates():
    """Caught in security review: two rules were eating the answer.

    `nextLocationUpdateExpectedBy` matched "location" but is a timestamp, and
    `positions` matched "position" but is the array whose `date` and
    `errorRadius` we specifically queried for. Both now survive -- while the
    coordinates one level down still do not.
    """
    from kona_tracker.probe.redact import REDACTED, redact

    out = redact(
        {
            "device": {"nextLocationUpdateExpectedBy": "2026-09-10T20:00:00Z"},
            "ongoingActivity": {
                "positions": [
                    {
                        "date": "2026-09-10T19:25:00Z",
                        "errorRadius": 8,
                        "position": {"latitude": 30.2672, "longitude": -97.7431},
                    }
                ]
            },
        }
    )
    assert out["device"]["nextLocationUpdateExpectedBy"] == "2026-09-10T20:00:00Z"

    point = out["ongoingActivity"]["positions"][0]
    assert point["date"] == "2026-09-10T19:25:00Z", "the shape is the point of the probe"
    assert point["errorRadius"] == 8
    assert point["position"] == REDACTED, "where she actually is, is not"


def test_an_exception_must_not_reopen_a_leak():
    """The exceptions are containers and timestamps only.

    A key that is itself private must never be listed, so the singular
    `position` and the plain location keys stay redacted.
    """
    from kona_tracker.probe.redact import REDACTED, is_sensitive_key, redact

    for key in ("position", "location", "latitude", "longitude", "homeCityState", "areaName"):
        assert is_sensitive_key(key), key
    assert redact({"position": {"latitude": 1.0}})["position"] == REDACTED


def test_the_cellular_block_and_wifi_scan_never_reach_the_summary():
    """Found on the walk probe: once the collar was on cellular, `device.info`
    grew a `cell` block and Wi-Fi scan results, and none of the keys matched.
    Home SSID, IMEI, ICCIDs, the eUICC EID and the serving cell id all went
    into a file that gets pasted into chats."""
    import json

    from kona_tracker.probe.redact import redact

    info = {
        "batteryPercent": 57,
        "cell": {
            "imei": "355025938471560",
            "iccid": "89011701324691489154",
            "serviceCellId": 15936785,
            "serviceMcc": 310,
            "serviceMnc": 410,
            "snr": 22,
        },
        "wifiNetworkNames": ["2101 (2.4 Ghz)"],
        "wifiStats": {"key": 996575936, "ssidStats": [{"ssid": "2101 (2.4 Ghz)"}]},
        "euiccInfo": {
            "eid": "89044045930000000000001582691347",
            "profiles": [{"iccid": "89148000013280779376", "serviceProvider": "Verizon"}],
        },
        "credentialPackHash": "rXDZTa4Dga0SX5UW0Sjed5svwqnD/eGsJdwUbG0aCBE=",
        "max77658Info": {"timeToEmptyS": 105969, "rcellMohm": 2371584},
    }
    device = {
        "info": info,
        "lastConnectionState": {"__typename": "ConnectedToCellular", "signalStrengthPercent": 29},
        "operationParams": {"mode": "POST_ESCAPE_NOTIFICATION"},
    }
    out = redact({"pet": {"device": device}})
    flat = json.dumps(out)
    for secret in (
        "355025938471560",
        "89011701324691489154",
        "15936785",
        "2101 (2.4 Ghz)",
        "89044045930000000000001582691347",
        "89148000013280779376",
        "rXDZTa4D",
    ):
        assert secret not in flat, secret
    kept = out["pet"]["device"]
    assert kept["info"]["batteryPercent"] == 57
    assert kept["info"]["max77658Info"]["timeToEmptyS"] == 105969
    assert kept["lastConnectionState"]["signalStrengthPercent"] == 29
    assert kept["operationParams"]["mode"] == "POST_ESCAPE_NOTIFICATION"
