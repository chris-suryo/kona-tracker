"""GraphQL documents for the Fi API.

Known-good shapes come from pytryfi's `const.py`; the speculative probe query
exists only to harvest the server's validation errors ("Did you mean ...?")
when introspection is disabled. Nothing here is documented by Fi.
"""

from datetime import UTC, date, datetime, timedelta

# Full schema dump. `ofType` is nested a few levels so NON_NULL/LIST wrappers
# still resolve to a named type.
INTROSPECTION = """
query KonaIntrospect {
  __schema {
    queryType { name }
    types {
      name
      kind
      description
      fields {
        name
        description
        args { name type { name kind ofType { name kind } } }
        type { name kind ofType { name kind ofType { name kind ofType { name kind } } } }
      }
      enumValues { name }
    }
  }
}
"""

# Shape per pytryfi FRAGMENT_USER_FULL_DETAILS: currentUser -> userHouseholds ->
# household -> pets. Kept minimal so a schema drift in unrelated fields does
# not sink the whole request.
CURRENT_USER_PETS = """
query KonaPets {
  currentUser {
    id
    userHouseholds {
      household {
        pets { id name }
      }
    }
  }
}
"""

REST_SUMMARY_FRAGMENT = """
fragment RestSummaryDetails on RestSummary {
  __typename
  start
  end
  data {
    __typename
    ... on ConcreteRestSummaryData {
      sleepAmounts { __typename type duration }
    }
  }
}
"""

#: Aliases for the three periods, matching pytryfi and `pet_activity` below.
REST_PERIODS: tuple[tuple[str, str], ...] = (
    ("dailyStat", "DAILY"),
    ("weeklyStat", "WEEKLY"),
    ("monthlyStat", "MONTHLY"),
)


def pet_rest(pet_id: str, limit: int = 2) -> str:
    """Sleep and nap totals at all three periods.

    `limit=2` on purpose: the newest daily window is today, in progress, and
    last night lives in the one before it. See `parse.split_windows`.

    The inline fragment on `ConcreteRestSummaryData` is load-bearing, not
    decoration. `RestSummary.data` is an abstract type and `sleepAmounts`
    exists only on the concrete implementation, so selecting it directly is
    a validation error and Fi refuses the entire query. That is exactly what
    broke on first contact with the real API: steps came back, sleep did
    not. Do not "simplify" this back.
    """
    feeds = " ".join(
        f"{alias}: restSummaryFeed(cursor: null, period: {period}, limit: {limit}) "
        "{ restSummaries { ...RestSummaryDetails } }"
        for alias, period in REST_PERIODS
    )
    return f'query KonaRest {{ pet(id: "{pet_id}") {{ {feeds} }} }}' + REST_SUMMARY_FRAGMENT


def pet_activity(pet_id: str) -> str:
    """Steps, goal and distance at all three periods, like pytryfi."""
    stats = " ".join(
        f"{alias}: currentActivitySummary(period: {period}) {{ totalSteps stepGoal totalDistance }}"
        for alias, period in REST_PERIODS
    )
    return f'query KonaActivity {{ pet(id: "{pet_id}") {{ {stats} }} }}'


# --------------------------------------------------------------------------
# Speculative queries: field names we HOPE exist.
#
# Introspection is disabled, so this is how the vocabulary gets learned. Any
# name that does not exist comes back as a validation error, and when Fi has
# something close it says so: `currentBehaviorSummary` -> "Did you mean
# currentActivitySummary?". A rejection with NO suggestion is evidence of
# absence. Each run's hints feed the next run's guesses until they saturate.
#
# The first eight are kept as they were: their rejections are the recorded
# proof that no sleep score or behaviour count exists on `Pet`.
# --------------------------------------------------------------------------
SPECULATIVE_PET_FIELDS = [
    "sleepQuality",
    "restQuality",
    "restScore",
    "sleepScore",
    "behaviorSummary",
    "behaviorFeed",
    "currentBehaviorSummary",
    "interruptions",
    # Round 2: things we would want, phrased several ways each.
    "battery",
    "batteryLevel",
    "batteryPercent",
    "health",
    "healthSummary",
    "healthScore",
    "heartRate",
    "walks",
    "walkFeed",
    "activityFeed",
    "restFeed",
    "restSummary",
    "currentRestSummary",
    "sleepSummary",
    "locationHistory",
    "currentLocation",
    "lastLocation",
    "lastSeen",
    "safeZones",
    "geofences",
    "places",
    "baseStation",
    "bases",
    "goals",
    "activityGoal",
    "insights",
    "age",
]


def pet_speculative(pet_id: str) -> str:
    fields = " ".join(SPECULATIVE_PET_FIELDS)
    return f'query KonaSpeculative {{ pet(id: "{pet_id}") {{ {fields} }} }}'


def speculative_queries(pet_id: str, on: date | None = None) -> list[tuple[str, str]]:
    """Every speculative query, labelled. One per type we know exists.

    The operation names all start with `KonaSpeculative` so a mock can route
    them together. Each errors independently, and every error names the type
    it was checked against, which is itself a fact worth recording.

    `on` anchors the round-7 queries that need a date; it defaults to today
    in UTC and is injectable so a test does not depend on the calendar.
    """
    today = on or datetime.now(UTC).date()
    yesterday = (today - timedelta(days=1)).isoformat()
    week_ago = (today - timedelta(days=7)).isoformat()
    return [
        ("pet", pet_speculative(pet_id)),
        (
            "device",
            f'query KonaSpeculativeDevice {{ pet(id: "{pet_id}") {{ device {{ '
            "battery batteryPercent batteryLevel charging isCharging firmware "
            "firmwareVersion signalStrength lastSeen temperature serialNumber "
            "} } }",
        ),
        (
            "activity",
            f'query KonaSpeculativeActivity {{ pet(id: "{pet_id}") {{ '
            "currentActivitySummary(period: DAILY) { "
            "activeMinutes activeTime calories restMinutes walks walkCount "
            "distanceMeters distanceMiles activityGoal "
            "} } }",
        ),
        (
            "rest",
            f'query KonaSpeculativeRest {{ pet(id: "{pet_id}") {{ '
            "restSummaryFeed(cursor: null, period: DAILY, limit: 1) { restSummaries { "
            "quality score restfulness interruptions wakeUps "
            "} } } }",
        ),
        (
            "ongoing",
            f'query KonaSpeculativeOngoing {{ pet(id: "{pet_id}") {{ ongoingActivity {{ '
            "type kind name place uncertainty totalSteps duration "
            "} } }",
        ),
        # Round 3: every one of these was named by a "did you mean" on
        # 2026-09-10. The shapes are guesses; the corrections name the truth.
        # Round 4. Round 3 proved these exist and named their shape only
        # partly, because the required-argument message was being redacted.
        # One unknown per query now, so each error names exactly one thing.
        (
            "overnight",
            f'query KonaSpeculativeOvernight {{ pet(id: "{pet_id}") {{ '
            # A distinct type: `start`, `end` and `data` were all rejected and
            # `data` drew "did you mean `date`?".
            "overnightRestSummary { __typename date } } }",
        ),
        (
            "restFeed",
            # `cursor` was accepted, `limit` was not, and something required
            # is still missing. Ask with cursor alone and let it name it.
            f'query KonaSpeculativeRestFeed {{ pet(id: "{pet_id}") {{ '
            "restFeed(cursor: null) { __typename } } }",
        ),
        (
            "activityFeed",
            # The mirror image: `limit` accepted, `cursor` rejected.
            f'query KonaSpeculativeActivityFeed {{ pet(id: "{pet_id}") {{ '
            "activityFeed(limit: 3) { __typename } } }",
        ),
        (
            "stepFeed",
            f'query KonaSpeculativeStepFeed {{ pet(id: "{pet_id}") {{ '
            "stepFeed(cursor: null) { __typename } } }",
        ),
        (
            "place",
            f'query KonaSpeculativePlace {{ pet(id: "{pet_id}") {{ ongoingActivity {{ '
            "__typename ... on OngoingRest { place { __typename id name } } } } }",
        ),
        (
            "home",
            f'query KonaSpeculativeHome {{ pet(id: "{pet_id}") {{ '
            "homeLocation { __typename } places { __typename id name } timezone } }",
        ),
        # All three needed arguments; split so one error names one field.
        (
            "heatmap",
            f'query KonaSpeculativeHeatmap {{ pet(id: "{pet_id}") {{ '
            "heatmap { __typename } } }",
        ),
        (
            "activityField",
            f'query KonaSpeculativeActivityField {{ pet(id: "{pet_id}") {{ '
            "activity { __typename } } }",
        ),
        (
            "packs",
            f'query KonaSpeculativePacks {{ pet(id: "{pet_id}") {{ packs {{ __typename }} }} }}',
        ),
        (
            "device2",
            f'query KonaSpeculativeDevice2 {{ pet(id: "{pet_id}") {{ device {{ '
            "__typename carrier hardwareRevision } } }",
        ),
        (
            "firmwareUpdate",
            f'query KonaSpeculativeFirmware {{ pet(id: "{pet_id}") {{ device {{ '
            "__typename firmwareUpdate { __typename } } } }",
        ),
        # Round 5, 2026-09-11: the resting position. pytryfi selects
        # `position { latitude longitude }` on OngoingRest and `path` on
        # OngoingWalk; the page now asks for the former (`pet_whereabouts`).
        # These ask around it, one unknown each: is the rest position a bare
        # Position or a Location with a date; what `uncertaintyInfo` (named
        # by a did-you-mean on 2026-09-10) looks like; and whether `device`
        # keeps a last/current location next to `nextLocationUpdateExpectedBy`.
        (
            "restPositionDate",
            f'query KonaSpeculativeRestPositionDate {{ pet(id: "{pet_id}") {{ ongoingActivity {{ '
            "__typename ... on OngoingRest { position { __typename date } } } } }",
        ),
        (
            "uncertainty",
            f'query KonaSpeculativeUncertainty {{ pet(id: "{pet_id}") {{ ongoingActivity {{ '
            "__typename ... on OngoingRest { uncertaintyInfo { __typename } } } } }",
        ),
        (
            "walkPath",
            f'query KonaSpeculativeWalkPath {{ pet(id: "{pet_id}") {{ ongoingActivity {{ '
            "__typename ... on OngoingWalk { path { __typename } } } } }",
        ),
        (
            "deviceLastLocation",
            f'query KonaSpeculativeDeviceLastLocation {{ pet(id: "{pet_id}") {{ device {{ '
            "__typename lastLocation { __typename } } } }",
        ),
        (
            "deviceCurrentLocation",
            f'query KonaSpeculativeDeviceCurrentLocation {{ pet(id: "{pet_id}") {{ device {{ '
            "__typename currentLocation { __typename } } } }",
        ),
        # Round 7, 2026-09-11 evening. Round 6 established that four fields
        # exist and named the one argument each requires:
        #   stepFeed / restFeed      period: ActivityRestStrainPeriod!
        #   overnightRestSummary     date: DateTime!
        #   heatmap                  startDate, endDate: DateTime!
        # Each is asked with that argument supplied and nothing else selected
        # but `__typename`, so the next error names exactly the next thing:
        # an enum value Fi does not accept, a scalar format it rejects, or --
        # if accepted -- the type whose subfields the round after this asks
        # for. `DAILY` is the value `restSummaryFeed` already accepts; whether
        # it is the same enum is precisely the unknown.
        (
            "stepFeedPeriod",
            f'query KonaSpeculativeStepFeedPeriod {{ pet(id: "{pet_id}") {{ '
            "stepFeed(period: DAILY) { __typename } } }",
        ),
        (
            "restFeedPeriod",
            f'query KonaSpeculativeRestFeedPeriod {{ pet(id: "{pet_id}") {{ '
            "restFeed(period: DAILY) { __typename } } }",
        ),
        (
            "overnightDate",
            f'query KonaSpeculativeOvernightDate {{ pet(id: "{pet_id}") {{ '
            f'overnightRestSummary(date: "{yesterday}T00:00:00Z") {{ __typename date }} }} }}',
        ),
        (
            "heatmapRange",
            f'query KonaSpeculativeHeatmapRange {{ pet(id: "{pet_id}") {{ '
            f'heatmap(startDate: "{week_ago}T00:00:00Z", endDate: "{today.isoformat()}T00:00:00Z") '
            "{ __typename } } }",
        ),
    ]


def pet_status(pet_id: str) -> str:
    """Everything the page shows beyond rest and steps, in one round trip.

    Only fields measured on Kona's collar on 2026-09-10, plus `timezone`,
    accepted by Fi in round 3 (its value is redacted by the probe, so the
    format is assumed IANA and the page falls back if it is not). `info` is
    a JSON scalar; battery is inside it. The two inline fragments are the concrete
    connection states -- selecting `signalStrengthPercent` directly would be
    the same class of error that broke sleep.
    """
    return (
        f'query KonaStatus {{ pet(id: "{pet_id}") {{ __typename name timezone '
        "breed { __typename name } yearOfBirth monthOfBirth dayOfBirth "
        "homeLocation { __typename position { __typename latitude longitude } } "
        "photos { __typename first { __typename id date image { __typename fullSize } } } "
        "device { __typename info nextLocationUpdateExpectedBy "
        "lastConnectionState { __typename date "
        "... on ConnectedToBase { chargingBase { __typename id } } "
        "... on ConnectedToCellular { signalStrengthPercent } } "
        "ledColor { __typename name hexCode } "
        "operationParams { __typename mode ledEnabled } } "
        "ongoingActivity { __typename start lastReportTimestamp areaName "
        "... on OngoingRest { place { __typename id name } } "
        "... on OngoingWalk { distance positions { __typename date errorRadius "
        "position { __typename latitude longitude } } } } "
        "} }"
    )


def pet_whereabouts(pet_id: str) -> str:
    """Where she is while resting: one field, in a document of its own.

    The Fi app shows her position whether she is walking or asleep, and our
    `pet_status` only ever asked `OngoingRest` for a place *name*. pytryfi's
    fragment (the Home Assistant tracker's source) selects
    `... on OngoingRest { position { latitude longitude } }`, so that is what
    this asks for. It has not yet been seen from Kona's collar, which is why
    it is not one more line in `pet_status`: a wrong field name fails the
    whole document, and that would take battery, signal and the escape flag
    down with it. Alone, a rejection costs exactly the map point, the page
    says "Location: ...", and `kona probe` runs this same document.
    """
    return (
        f'query KonaWhereabouts {{ pet(id: "{pet_id}") {{ __typename ongoingActivity {{ '
        "__typename lastReportTimestamp "
        "... on OngoingRest { position { __typename latitude longitude } } "
        "} } }"
    )


# --------------------------------------------------------------------------
# Probe-only queries.
#
# Field names taken from pytryfi's const.py, which is what the Home Assistant
# integration Chris found is built on. They are *sourced*, not guessed — but
# not yet verified against Kona's collar, which is the probe's whole job.
# Nothing here is wired into the page until a real response comes back.
# --------------------------------------------------------------------------


def pet_profile(pet_id: str) -> str:
    """Who Kona is, including the photo already set in the Fi app."""
    return (
        f'query KonaProfile {{ pet(id: "{pet_id}") {{ '
        "__typename id name homeCityState yearOfBirth monthOfBirth dayOfBirth "
        "gender weight isPurebred "
        "breed { __typename id name } "
        "photos { __typename "
        "first { __typename id date image { __typename fullSize } } "
        "items { __typename id date image { __typename fullSize } } } "
        "} }"
    )


def pet_device(pet_id: str) -> str:
    """The collar itself: charge, signal, LED, lost-dog mode."""
    return (
        f'query KonaDevice {{ pet(id: "{pet_id}") {{ __typename device {{ '
        "__typename id moduleId info nextLocationUpdateExpectedBy "
        "operationParams { __typename mode ledEnabled ledOffAt } "
        "lastConnectionState { __typename date "
        "... on ConnectedToBase { chargingBase { __typename id } } "
        "... on ConnectedToCellular { signalStrengthPercent } } "
        "ledColor { __typename ledColorCode hexCode name } "
        "} } }"
    )


def pet_location(pet_id: str) -> str:
    """Where she is and whether she is out on a walk right now."""
    return (
        f'query KonaLocation {{ pet(id: "{pet_id}") {{ __typename ongoingActivity {{ '
        "__typename start lastReportTimestamp areaName "
        "... on OngoingWalk { distance positions { __typename date errorRadius "
        "position { __typename latitude longitude } } } "
        "} } }"
    )
