import json

from kona_tracker.probe.run import run_probe


def test_probe_end_to_end_writes_redacted_files(fake_client, tmp_path):
    fake_client.login("chris@example.com", "correct")
    report = run_probe(fake_client, tmp_path)

    assert report.pets == [{"id": "pet-1", "name": "Kona"}]
    assert report.introspection_ok
    assert report.errors == {}
    names = sorted(p.name for p in report.files)
    assert names == [
        "pet-kona-activity.json",
        "pet-kona-device.json",
        "pet-kona-location.json",
        "pet-kona-profile.json",
        "pet-kona-rest.json",
        "schema.json",
        "summary.md",
    ]

    rest = json.loads((tmp_path / "pet-kona-rest.json").read_text(encoding="utf-8"))
    amounts = rest["pet"]["dailyStat"]["restSummaries"][0]["data"]["sleepAmounts"]
    assert amounts[0] == {"duration": 30600, "type": "SLEEP"}

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Kona (id pet-1)" in summary
    assert "Pet.sleepScore: Int" in summary
    assert 'Did you mean "sleepScore"' in summary
    assert "chris@example.com" not in summary
    for f in report.files:
        assert "chris@example.com" not in f.read_text(encoding="utf-8")
