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
  start
  end
  data {
    __typename
    sleepAmounts { type duration }
  }
}
"""


def pet_rest(pet_id: str, period: str = "DAILY", limit: int = 7) -> str:
    """Rest feed for one pet. `period` is DAILY | WEEKLY | MONTHLY."""
    return (
        f'query KonaRest {{ pet(id: "{pet_id}") {{ '
        f"restSummaryFeed(cursor: null, period: {period}, limit: {limit}) {{ "
        "restSummaries { ...RestSummaryDetails } } } }" + REST_SUMMARY_FRAGMENT
    )


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
