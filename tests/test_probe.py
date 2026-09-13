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
        "pet-kona-rest-history.json",
        "pet-kona-rest.json",
        "pet-kona-whereabouts.json",
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


def test_round_five_asks_around_the_resting_position_one_unknown_each():
    """The page now sends `... on OngoingRest { position }` (pytryfi's
    fragment, unverified on Kona's collar) in `pet_whereabouts`; the probe
    sends that same document, and these five ask what sits next to it."""
    from kona_tracker.fi.queries import pet_whereabouts, speculative_queries

    labelled = dict(speculative_queries("pet-1"))
    for label in (
        "restPositionDate",
        "uncertainty",
        "walkPath",
        "deviceLastLocation",
        "deviceCurrentLocation",
    ):
        assert label in labelled, label
        assert "KonaRest" not in labelled[label], "that substring routes to the sleep refusal"
    assert "... on OngoingRest { position { __typename date } }" in labelled["restPositionDate"]
    assert "uncertaintyInfo { __typename }" in labelled["uncertainty"]
    assert "lastLocation { __typename }" in labelled["deviceLastLocation"]
    doc = pet_whereabouts("pet-1")
    assert doc.startswith("query KonaWhereabouts")
    assert "... on OngoingRest { position { __typename latitude longitude } }" in doc
    assert "OngoingWalk" not in doc and "place" not in doc, "one field, one document"


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


def test_rest_history_probe_asks_for_more_windows_than_the_page_uses(fake_client, tmp_path):
    """The page sends `limit=2` deliberately; nobody has asked Fi for more.

    `restSummaryFeed` is an accepted production query, so if a raised limit
    returns more windows then daily rest history needs no new document --
    only a different argument. This pins that the probe actually asks, and
    that its answer is told apart from the two-window production probe in the
    one file Chris pastes back.
    """
    from kona_tracker.fi import queries
    from kona_tracker.probe.run import HISTORY_LIMIT

    assert HISTORY_LIMIT > 2
    asked = queries.pet_rest("pet-1", limit=HISTORY_LIMIT)
    assert f"limit: {HISTORY_LIMIT}" in asked
    assert "limit: 2" not in asked

    fake_client.login("chris@example.com", "correct")
    run_probe(fake_client, tmp_path)

    assert (tmp_path / "pet-kona-rest-history.json").exists()
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    # Both probes report, and the history one is labelled, or the two sets of
    # windows would be indistinguishable in the pasted summary.
    # `_metric_lines` is passed the file slug, not the display name.
    assert "kona [history]" in summary
    assert f"asked restSummaryFeed for limit={HISTORY_LIMIT}" in summary
    assert "windows back" in summary


def test_round_seven_supplies_the_one_argument_each_round_six_error_named():
    """Round 6 proved four fields exist and named the single argument each
    requires. Round 7 asks each with that argument and nothing but
    `__typename`, so the next error names exactly the next unknown."""
    from datetime import date

    from kona_tracker.fi.queries import speculative_queries

    labelled = dict(speculative_queries("pet-1", on=date(2026, 9, 11)))
    for label in ("stepFeedPeriod", "restFeedPeriod", "overnightDate", "heatmapRange"):
        assert label in labelled, label
        assert "KonaRest" not in labelled[label], "that substring routes to the sleep refusal"
        assert labelled[label].lstrip().startswith("query KonaSpeculative"), label

    # The enum value restSummaryFeed already accepts; whether it is the same
    # enum is the unknown being asked.
    assert "stepFeed(period: DAILY) { __typename }" in labelled["stepFeedPeriod"]
    assert "restFeed(period: DAILY) { __typename }" in labelled["restFeedPeriod"]
    # Dates are anchored to the injected day, in UTC, so a run in any
    # timezone sends the same literal and the summary is reproducible.
    assert 'overnightRestSummary(date: "2026-09-10T00:00:00Z")' in labelled["overnightDate"]
    assert 'startDate: "2026-09-04T00:00:00Z"' in labelled["heatmapRange"]
    assert 'endDate: "2026-09-11T00:00:00Z"' in labelled["heatmapRange"]

    # Round 4's zero-argument asks are kept as the record of how each
    # argument was learned; the new ones must not replace them.
    assert "stepFeed(cursor: null)" in labelled["stepFeed"]
    assert "overnightRestSummary { __typename date }" in labelled["overnight"]


def test_round_eight_sends_the_enum_value_fi_suggested_and_guesses_subfields():
    """Round 7's DAILY was refused with "Did you mean DAY?"; round 8 sends
    DAY, checks WEEK to size the enum, and guesses subfields bare so the
    validation errors name each miss. DAILY must not be sent to these two
    fields again -- that answer is already recorded."""
    from datetime import date

    from kona_tracker.fi.queries import speculative_queries

    labelled = dict(speculative_queries("pet-1", on=date(2026, 9, 12)))
    for label in (
        "stepFeedDay",
        "restFeedDay",
        "restFeedWeek",
        "restFeedFields",
        "stepFeedFields",
        "overnightFields",
        "heatmapFields",
        "activityFeedItems",
    ):
        assert label in labelled, label
        assert "KonaRest" not in labelled[label], "that substring routes to the sleep refusal"
        assert labelled[label].lstrip().startswith("query KonaSpeculative"), label

    assert "stepFeed(period: DAY) { __typename }" in labelled["stepFeedDay"]
    assert "restFeed(period: DAY) { __typename }" in labelled["restFeedDay"]
    assert "restFeed(period: WEEK) { __typename }" in labelled["restFeedWeek"]
    for label in ("restFeedFields", "stepFeedFields"):
        assert "period: DAY" in labelled[label] and "DAILY" not in labelled[label]
        assert "{ items first" in labelled[label], "bare guesses, so each miss is named"
    assert 'overnightRestSummary(date: "2026-09-11T00:00:00Z")' in labelled["overnightFields"]
    assert 'startDate: "2026-09-05T00:00:00Z"' in labelled["heatmapFields"]
    assert "activityFeed(limit: 3) { items" in labelled["activityFeedItems"]
    # Round 7 stays as the record of how DAY was learned.
    assert "stepFeed(period: DAILY)" in labelled["stepFeedPeriod"]


def test_round_nine_follows_the_three_things_round_eight_did_not_say():
    """Round 8's silences are its findings: `cursor` drew no error where
    every sibling guess did, the overnight type's fields were checked
    against a different type name than the one it returned, and two list
    fields were named after their element type. Round 9 acts on each."""
    from datetime import date

    from kona_tracker.fi.queries import speculative_queries

    labelled = dict(speculative_queries("pet-1", on=date(2026, 9, 12)))
    for label in (
        "restFeedCursor",
        "stepFeedCursor",
        "restFeedNames",
        "stepFeedNames",
        "overnightConcrete",
        "overnightConcreteFields",
        "heatmapPoints",
        "heatmapPointFields",
        "activityFeedShape",
        "activityItemFields",
    ):
        assert label in labelled, label
        assert "KonaRest" not in labelled[label], "that substring routes to the sleep refusal"
        assert labelled[label].lstrip().startswith("query KonaSpeculative"), label

    # The one field round 8 proved exists, asked for on its own so its value
    # comes back instead of being lost to a sibling's validation error.
    assert "restFeed(period: DAY) { __typename cursor }" in labelled["restFeedCursor"]
    assert "stepFeed(period: DAY) { __typename cursor }" in labelled["stepFeedCursor"]

    # Fields on an interface need an inline fragment on the concrete type Fi
    # actually returned; asking the interface is what failed last round.
    assert "... on ConcreteOvernightRestSummary" in labelled["overnightConcrete"]
    assert "... on ConcreteOvernightRestSummary" in labelled["overnightConcreteFields"]

    # Descend into the two list fields Fi named itself, rather than guessing
    # container names again.
    assert "points { __typename }" in labelled["heatmapPoints"]
    assert "activities { __typename }" in labelled["activityFeedShape"]

    # Names already refused must not be re-sent; that answer is recorded.
    for label in ("restFeedNames", "stepFeedNames"):
        for refused in ("items", "first", "entries", "buckets", "pageInfo"):
            assert f" {refused} " not in labelled[label], f"{refused} was already refused"


def test_round_ten_reads_what_round_nine_named():
    """Round 9's did-you-means named `restSummary`, `stepSummary`,
    `sleepSeconds`/`sleepStart`/`sleepEnd`, `position` and the Walk type;
    round 10 asks for each by name and pages the feed back one day with a
    cursor built the way Fi builds its own."""
    import base64
    from datetime import date

    from kona_tracker.fi.queries import speculative_queries

    labelled = dict(speculative_queries("pet-1", on=date(2026, 9, 13)))
    for label in (
        "restFeedSummary",
        "stepFeedSummary",
        "restFeedBack",
        "restSummaryGrain",
        "stepSummaryGrain",
        "overnightSleep",
        "overnightMore",
        "heatmapPosition",
        "heatmapPointMore",
        "walkFields",
        "walkMore",
    ):
        assert label in labelled, label
        assert "KonaRest" not in labelled[label], "that substring routes to the sleep refusal"
        assert labelled[label].lstrip().startswith("query KonaSpeculative"), label

    assert (
        "restFeed(period: DAY) { period restSummary { __typename } }" in labelled["restFeedSummary"]
    )
    assert (
        "stepFeed(period: DAY) { period stepSummary { __typename } }" in labelled["stepFeedSummary"]
    )

    # The cursor Fi returned was base64 of the Fi-day start; yesterday's is
    # the same shape one day back, so the feed can be asked to page.
    expected = base64.b64encode(b"2026-09-12T04:00:00.000Z").decode()
    assert f'cursor: "{expected}"' in labelled["restFeedBack"]

    assert "sleepSeconds sleepStart sleepEnd" in labelled["overnightSleep"]
    assert "position { __typename latitude longitude }" in labelled["heatmapPosition"]
    assert "... on Walk { distance }" in labelled["walkFields"]
    assert "pageInfo { __typename hasNextPage endCursor }" in labelled["walkFields"]
