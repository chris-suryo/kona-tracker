import httpx
import pytest

from kona_tracker.fi.client import FiClient, FiGraphQLError, FiLoginError


def test_login_stores_session_and_cookie(fake_client):
    session = fake_client.login("chris@example.com", "correct")
    assert session.user_id == "user-123"
    assert session.session_id == "sess-abc"
    # The cookie jar is what authenticates later calls; the handler asserts it.
    data = fake_client.graphql("query KonaPets { currentUser { id } }")
    assert data["currentUser"]["id"] == "user-123"


def test_login_failure_raises_without_password(fake_client):
    with pytest.raises(FiLoginError) as exc:
        fake_client.login("chris@example.com", "wrong")
    assert exc.value.status == 401
    assert "wrong" not in str(exc.value)
    assert "body omitted" in str(exc.value)


def test_graphql_errors_keep_hints(fake_client):
    fake_client.login("chris@example.com", "correct")
    with pytest.raises(FiGraphQLError) as exc:
        fake_client.graphql("query KonaSpeculative { pet { sleepQuality } }")
    assert any("Did you mean" in e["message"] for e in exc.value.errors)


def test_non_json_response_is_a_fi_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>bad gateway</html>")

    with FiClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(FiLoginError) as exc:
            c.login("a@b.c", "x")
        assert exc.value.status == 502


def test_graphql_multi_suggestion_hints_survive_the_allowlist():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "errors": [
                    {
                        "message": 'Cannot query field "sleepQuality" on type "Pet". '
                        'Did you mean "sleepScore", "sleepStats", or "sleep"?'
                    },
                    {
                        "message": 'Cannot query field "restQuality" on type "Pet". '
                        'Did you mean "rest" or "restStats"?'
                    },
                    {"message": "denied for chris@example.com session=abc"},
                ]
            },
        )

    with FiClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(FiGraphQLError) as exc:
            c.graphql("query KonaSpeculative { pet { sleepQuality } }")
    msgs = [e["message"] for e in exc.value.errors]
    assert '"sleepScore", "sleepStats", or "sleep"' in msgs[0]
    assert '"rest" or "restStats"' in msgs[1]
    assert "chris@example.com" not in msgs[2] and "omitted" in msgs[2]


# --------------------------------------------------------------------------
# The sleep query, and the reason it shipped broken.
# --------------------------------------------------------------------------


def test_the_shipped_rest_query_reaches_sleep_through_the_abstract_type():
    """`RestSummary.data` is abstract; `sleepAmounts` is on the concrete type.

    Selecting it directly is a validation error and Fi refuses the whole
    query, which is what happened on first contact with Kona's collar: steps
    arrived, sleep did not. The inline fragment is the fix and this pins it.
    """
    from kona_tracker.fi.queries import pet_rest

    query = pet_rest("pet-1")
    assert "... on ConcreteRestSummaryData" in query
    assert "sleepAmounts" in query.split("... on ConcreteRestSummaryData", 1)[1]
    for alias in ("dailyStat", "weeklyStat", "monthlyStat"):
        assert f"{alias}: restSummaryFeed" in query


def test_the_mock_now_refuses_what_fi_refuses(fake_client):
    """The test-design bug behind the query bug.

    The mock used to answer any query carrying the right operation name, so
    102 tests validated the parser and none validated the query. Feed it the
    old broken shape: it must now fail the way the real server did.
    """
    from kona_tracker.fi.client import FiGraphQLError
    from kona_tracker.fi.queries import pet_rest

    fake_client.login("chris@example.com", "correct")
    assert fake_client.graphql(pet_rest("pet-1"))["pet"]["dailyStat"]["restSummaries"]

    broken = pet_rest("pet-1").replace(
        "... on ConcreteRestSummaryData {\n      sleepAmounts", "sleepAmounts"
    )
    assert "... on ConcreteRestSummaryData" not in broken
    with pytest.raises(FiGraphQLError) as caught:
        fake_client.graphql(broken)
    # And the message survives redaction, which is the whole point of the
    # widened allowlist: this is the sentence that names the fix.
    assert "inline fragment" in str(caught.value)
    assert "ConcreteRestSummaryData" in str(caught.value)


@pytest.mark.parametrize(
    "message",
    [
        'Cannot query field "sleepQuality" on type "Pet".',
        'Cannot query field "currentBehaviorSummary" on type "Pet".'
        ' Did you mean "currentActivitySummary"?',
        'Cannot query field "sleepAmounts" on type "RestSummaryData".'
        ' Did you mean to use an inline fragment on "ConcreteRestSummaryData"?',
        'Unknown argument "cursor" on field "Pet.restSummaryFeed".',
        'Unknown type "RestPeriod". Did you mean "RestPeriodType"?',
        'Unknown fragment "RestSummaryDetails".',
        'Field "Query.pet" argument "id" of type "ID!" is required, but it was not provided.',
        'Field "name" must not have a selection since type "String!" has no subfields.',
        'Field "photos" of type "PetPhotos" must have a selection of subfields.'
        ' Did you mean "photos { ... }"?',
        'Value "HOURLY" does not exist in "RestPeriod" enum. Did you mean the enum value "DAILY"?',
        'Fragment "F" cannot be spread here as objects of type "A" can never be of type "B".',
    ],
)
def test_schema_validation_messages_survive_verbatim(message):
    """These are authored by graphql-js and name only schema identifiers.

    They are how we learn what Fi renamed. Redacting them cost this project
    an afternoon, so each shape is pinned.
    """
    from kona_tracker.fi.client import FiGraphQLError

    assert FiGraphQLError([{"message": message}]).errors[0]["message"] == message


@pytest.mark.parametrize(
    "message",
    [
        # Echoes the value that was sent -- the one validation message that can
        # carry account data. Stays redacted on purpose.
        'Expected type "String", found chris@example.com.',
        "User 5K5j1NIYBjwOD3PotTdvhh is not authorized for pet at 12 Elm Street",
        'Cannot query field "a" on type "B". Contact chris@example.com',
        "Internal server error: token=abc123",
        "",
    ],
)
def test_everything_else_is_still_redacted(message):
    from kona_tracker.fi.client import REDACTED, FiGraphQLError

    assert FiGraphQLError([{"message": message}]).errors[0]["message"] == REDACTED
