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
    # [0] is today, in progress, SLEEP=0; last night is [1].
    amounts = rest["pet"]["dailyStat"]["restSummaries"][1]["data"]["sleepAmounts"]
    assert amounts[0] == {"duration": 30600, "type": "SLEEP"}

    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "Kona (id pet-1)" in summary
    assert "Pet.sleepScore: Int" in summary
    assert '[pet] Cannot query field "sleepQuality"' in summary
    assert 'Did you mean "sleepScore"' in summary
    assert "chris@example.com" not in summary

    # One pasted file must carry everything the probe learned: the
    # profile/device/location bodies are inlined, redacted.
    assert "## Other responses" in summary
    assert '"signalStrengthPercent": 72' in summary
    assert '"fullSize": "<redacted>"' in summary
    assert '"areaName": "<redacted>"' in summary
    assert "Austin" not in summary and "30.2672" not in summary
    for f in report.files:
        assert "chris@example.com" not in f.read_text(encoding="utf-8")


def test_speculative_queries_isolate_one_unknown_each():
    """Round 3 proved the fields exist and half-named their shapes; round 4
    asks so each error names exactly one thing. `overnightRestSummary` turned
    out to be its own type -- `start`, `end` and `data` were all rejected and
    `data` drew "did you mean `date`?" -- so it is no longer asked for as if
    it were a RestSummary."""
    from kona_tracker.fi.queries import speculative_queries

    labelled = dict(speculative_queries("pet-1"))
    for label in (
        "overnight",
        "restFeed",
        "activityFeed",
        "stepFeed",
        "place",
        "home",
        "heatmap",
        "activityField",
        "packs",
        "device2",
        "firmwareUpdate",
    ):
        assert label in labelled, label
    for label, query in labelled.items():
        assert query.lstrip().startswith("query KonaSpeculative"), label
    assert "date" in labelled["overnight"] and "sleepAmounts" not in labelled["overnight"]
    assert "... on OngoingRest { place" in labelled["place"]
    # `cursor` was accepted on restFeed and rejected on activityFeed. Ask each
    # with only the argument it took, so the remaining error is the real one.
    assert "restFeed(cursor: null)" in labelled["restFeed"]
    assert "activityFeed(limit: 3)" in labelled["activityFeed"]


def test_gps_tracks_collapse_to_their_shape_in_the_summary():
    """The walk probe inlined ~190 one-per-second positions. The shape is the
    point; the list was noise -- and it is what the redactor already turned
    the coordinates into."""
    from kona_tracker.probe.run import _collapse_positions

    track = {
        "ongoingActivity": {
            "__typename": "OngoingWalk",
            "distance": 285.8,
            "positions": [
                {"date": "2026-09-10T20:51:43Z", "errorRadius": 0.1, "position": "<redacted>"},
                {"date": "2026-09-10T20:53:00Z", "errorRadius": 65, "position": "<redacted>"},
                {"date": "2026-09-10T20:57:38Z", "errorRadius": 6, "position": "<redacted>"},
                "junk",
            ],
        }
    }
    out = _collapse_positions(track)["ongoingActivity"]
    assert out["distance"] == 285.8
    assert out["positions"] == {
        "count": 4,
        "first": "2026-09-10T20:51:43Z",
        "last": "2026-09-10T20:57:38Z",
        "errorRadius": [0.1, 65],
    }
    assert _collapse_positions({"positions": []})["positions"]["count"] == 0
