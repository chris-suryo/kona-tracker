import json
import os
from pathlib import Path

import httpx
import pytest

from kona_tracker.fi.client import FiClient

FIXTURES = Path(__file__).parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config: pytest.Config) -> None:
    """Refuse to run if pytest's temp directory is inside the checkout.

    pytest deletes `--basetemp` wholesale at the start of every session, so
    pointing it into a working tree is destructive, and the tests that create
    a git repository under `tmp_path` then nest one inside this one. It
    happened: a `User`-scoped PYTEST_ADDOPTS held
    `--basetemp=C:\\Users\\harim\\.pytest-tmp`, pytest parses that value with
    `shlex.split()`, which eats the backslashes and leaves
    `C:Usersharim.pytest-tmp` -- which Windows reads as drive-relative and
    resolves against the current directory, i.e. inside the repo.

    The symptom was one failing build test and no hint of the cause, so this
    fails first and says the cause out loud. Fail closed: the alternative is
    a suite that looks green while deleting a directory in the working tree.
    """
    raw = config.getoption("basetemp", default=None)
    if not raw:
        return
    resolved = Path(raw).resolve()
    if resolved != REPO_ROOT and REPO_ROOT not in resolved.parents:
        return
    addopts = os.environ.get("PYTEST_ADDOPTS")
    raise pytest.UsageError(
        f"--basetemp resolves to {resolved}, which is inside the checkout at "
        f"{REPO_ROOT}. pytest wipes that directory at the start of every run.\n"
        f"PYTEST_ADDOPTS={addopts!r}\n"
        "A Windows path written with backslashes is the usual cause: pytest "
        "splits the value with shlex, which eats them, and the remainder is "
        "read as drive-relative. Use forward slashes (see docs/first-run.md), "
        "or unset the variable:\n"
        "  [Environment]::SetEnvironmentVariable('PYTEST_ADDOPTS', $null, 'User')"
    )


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
            ("KonaStatus", "status"),
            ("KonaProfile", "profile"),
            ("KonaDevice", "device"),
            ("KonaLocation", "location"),
            ("KonaWhereabouts", "whereabouts"),
            ("KonaWalks", "walks"),
            ("KonaOvernight", "overnight"),
            ("KonaHourly", "hourly"),
        ):
            if op in query:
                return httpx.Response(200, json=fixture(name))
        return httpx.Response(400, json={"errors": [{"message": "unknown operation"}]})
    return httpx.Response(404)


@pytest.fixture
def fake_client() -> FiClient:
    with FiClient(transport=httpx.MockTransport(fake_fi_handler)) as c:
        yield c
