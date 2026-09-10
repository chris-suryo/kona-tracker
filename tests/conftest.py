import json
from pathlib import Path

import httpx
import pytest

from kona_tracker.fi.client import FiClient

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def fake_fi_handler(request: httpx.Request) -> httpx.Response:
    """Routes like the real API: /auth/login form POST, then GraphQL by operation name."""
    if request.url.path == "/auth/login":
        form = dict(httpx.QueryParams(request.content.decode()))
        if form.get("password") == "correct":
            return httpx.Response(
                200, json=fixture("login_ok"), headers={"set-cookie": "fi_session=cookie-1; Path=/"}
            )
        return httpx.Response(401, json=fixture("login_error"))
    if request.url.path == "/graphql":
        assert request.headers.get("cookie") == "fi_session=cookie-1", "not logged in"
        query = json.loads(request.content)["query"]
        # Answer like the real server, not like a yes-man. A mock that returns
        # a valid response to an invalid query tests the parser and nothing
        # else -- which is exactly how a malformed sleep query shipped and
        # only failed against Kona's actual collar. `sleepAmounts` sits on a
        # concrete type behind an abstract one, so without the inline fragment
        # Fi rejects the whole query, and now so does this.
        if "KonaRest" in query and "... on ConcreteRestSummaryData" not in query:
            return httpx.Response(200, json=fixture("rest_error"))
        for op, name in (
            ("KonaPets", "pets"),
            ("KonaIntrospect", "introspection"),
            ("KonaRest", "rest"),
            ("KonaActivity", "activity"),
            ("KonaSpeculative", "speculative_error"),
            ("KonaProfile", "profile"),
            ("KonaDevice", "device"),
            ("KonaLocation", "location"),
        ):
            if op in query:
                return httpx.Response(200, json=fixture(name))
        return httpx.Response(400, json={"errors": [{"message": "unknown operation"}]})
    return httpx.Response(404)


@pytest.fixture
def fake_client() -> FiClient:
    with FiClient(transport=httpx.MockTransport(fake_fi_handler)) as c:
        yield c
