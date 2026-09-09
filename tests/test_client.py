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
