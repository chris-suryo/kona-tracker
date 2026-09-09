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
