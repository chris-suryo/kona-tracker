from conftest import fixture

from kona_tracker.probe.scan import scan_schema


def test_scan_finds_pet_fields_and_keyword_hits():
    scan = scan_schema(fixture("introspection")["data"]["__schema"])
    assert "id: ID!" in scan.pet_fields
    assert "restSummaryFeed(period: RestPeriod, limit: Int): RestSummaryFeed" in scan.pet_fields
    assert "Pet.sleepScore: Int" in scan.keyword_hits
    assert "BehaviorSummary.barkingSeconds: Int" in scan.keyword_hits
    assert "SleepAmountType.NAP (enum value)" in scan.keyword_hits
    assert scan.keyword_types == ["BehaviorSummary", "SleepAmountType"]
    assert not any(h.startswith("__") for h in scan.keyword_hits)
