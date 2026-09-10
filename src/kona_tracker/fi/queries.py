"""GraphQL documents for the Fi API.

Known-good shapes come from pytryfi's `const.py`; the speculative probe query
exists only to harvest the server's validation errors ("Did you mean ...?")
when introspection is disabled. Nothing here is documented by Fi.
"""

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


def pet_rest(pet_id: str, limit: int = 1) -> str:
    """Sleep and nap totals at all three periods.

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
    return (
        f'query KonaActivity {{ pet(id: "{pet_id}") {{ '
        "dailyStat: currentActivitySummary(period: DAILY) { totalSteps stepGoal totalDistance } "
        "weeklyStat: currentActivitySummary(period: WEEKLY) { totalSteps stepGoal totalDistance } "
        "} }"
    )


# Field names we HOPE exist. Any that don't will come back as validation
# errors, usually with a "Did you mean" hint naming the real field.
SPECULATIVE_PET_FIELDS = [
    "sleepQuality",
    "restQuality",
    "restScore",
    "sleepScore",
    "behaviorSummary",
    "behaviorFeed",
    "currentBehaviorSummary",
    "interruptions",
]


def pet_speculative(pet_id: str) -> str:
    fields = " ".join(SPECULATIVE_PET_FIELDS)
    return f'query KonaSpeculative {{ pet(id: "{pet_id}") {{ {fields} }} }}'


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
