"""Thin client for Fi's undocumented API (api.tryfi.com).

Why not pytryfi: it last shipped in Dec 2023, sends GraphQL via GET query
strings, and pulls in `requests`. The whole surface we need is one login POST
and one GraphQL POST, so a ~100-line client we control is safer than a stale
dependency that may break without notice.

Auth model (from pytryfi's source): POST /auth/login with form fields
`email` and `password`; the server sets a session cookie and returns JSON with
`userId` and `sessionId`. Every later call rides on the cookie jar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

BASE_URL = "https://api.tryfi.com"
LOGIN_PATH = "/auth/login"
GRAPHQL_PATH = "/graphql"

# A browser-like UA: pytryfi sets custom headers we could not read from the
# fetched source, so we mimic a normal client rather than httpx's default.
USER_AGENT = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) kona-tracker/0.1"


class FiError(Exception):
    """Base class for anything the Fi API refuses."""


class FiLoginError(FiError):
    """Login rejected. Carries HTTP status and a locally authored explanation."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Fi login failed (HTTP {status}): {body}")


# --------------------------------------------------------------------------
# What a GraphQL error is allowed to say out loud.
#
# Fi's server prose and error `extensions` can carry account data, so the
# default is to redact. The exception is graphql-js's **validation** errors:
# they are authored by the GraphQL library, not by Fi, and they name only
# schema identifiers — types, fields, arguments, enum values. Those are
# exactly the messages that tell us how the API changed, and throwing them
# away has already cost this project real time: the sleep query broke with
# "Did you mean to use an inline fragment on ConcreteRestSummaryData?" and
# all we kept was "GraphQL error".
#
# `Expected type "X", found <literal>` is deliberately NOT here. It echoes
# the value that was sent, which is the one validation message that can
# carry data.
# --------------------------------------------------------------------------
_NAME = r'"[A-Za-z_][A-Za-z_0-9]*"'
#: A type reference, which may be wrapped: "ID!", "[String!]!".
_TYPE = r'"[A-Za-z_][A-Za-z_0-9]*[!\]\[]*"|"\[[A-Za-z_][A-Za-z_0-9!\]\[]*"'
#: graphql-js names an argument's owner as "Type.field".
_COORD = r'"[A-Za-z_][A-Za-z_0-9]*\.[A-Za-z_][A-Za-z_0-9]*"'
#: `"a"`, `"a", "b"`, `"a", "b", or "c"` — keep the whole list; the
#: suggestions are the entire point of the speculative probe query.
_LIST = rf"{_NAME}(?:, {_NAME})*(?:,? or {_NAME})?"
_SUGGEST = rf"(?: Did you mean {_LIST}\?)?"

ALLOWED_GRAPHQL_ERRORS: tuple[str, ...] = (
    # Unknown field, with either flavour of hint.
    rf"Cannot query field {_NAME} on type {_NAME}\."
    rf"(?:{_SUGGEST}| Did you mean to use an inline fragment on {_LIST}\?)",
    rf"Unknown argument {_NAME} on field {_COORD}\.{_SUGGEST}",
    rf"Unknown type {_NAME}\.{_SUGGEST}",
    rf"Unknown fragment {_NAME}\.",
    rf"Field {_COORD} argument {_NAME} of type (?:{_TYPE}) is required, "
    r"but it was not provided\.",
    rf"Field {_NAME} must not have a selection since type (?:{_TYPE}) has no subfields\.",
    # The hint here quotes the whole suggestion, braces included:
    # Did you mean "photos { ... }"?  — not "photos" { ... }.
    rf"Field {_NAME} of type (?:{_TYPE}) must have a selection of subfields\."
    r'(?: Did you mean "[A-Za-z_][A-Za-z_0-9]* \{ \.\.\. \}"\?)?',
    rf"Value {_NAME} does not exist in {_NAME} enum\."
    rf"(?: Did you mean the enum value {_LIST}\?)?",
    rf"Fragment {_NAME} cannot be spread here as objects of type {_NAME} "
    rf"can never be of type {_NAME}\.",
)

REDACTED = "GraphQL error (server details omitted for privacy)."


def allowlisted(message: str) -> bool:
    """True if this is a schema-validation message safe to repeat verbatim."""
    return any(re.fullmatch(p, message) for p in ALLOWED_GRAPHQL_ERRORS)


class FiGraphQLError(FiError):
    """GraphQL errors with only allowlisted schema-validation text retained."""

    def __init__(self, errors: list[dict[str, Any]], data: Any = None):
        self.errors = [
            {"message": message if allowlisted(message) else REDACTED}
            for error in errors
            for message in [str(error.get("message", ""))]
        ]
        self.data = data
        messages = "; ".join(e["message"] for e in self.errors)
        super().__init__(f"Fi GraphQL error: {messages}")


@dataclass(frozen=True)
class FiSession:
    user_id: str
    session_id: str


class FiClient:
    """Sync HTTP client. Pass `transport=httpx.MockTransport(...)` in tests."""

    def __init__(
        self,
        base_url: str = BASE_URL,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
    ):
        self._http = httpx.Client(
            base_url=base_url,
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self.session: FiSession | None = None

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> FiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def login(self, email: str, password: str) -> FiSession:
        try:
            resp = self._http.post(LOGIN_PATH, data={"email": email, "password": password})
        except httpx.RequestError:
            raise FiError("Fi login connection failed; check connectivity and try again.") from None
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not resp.is_success or not isinstance(body, dict) or "error" in body:
            raise FiLoginError(
                resp.status_code, "Login rejected or invalid response; body omitted."
            )
        try:
            self.session = FiSession(user_id=str(body["userId"]), session_id=str(body["sessionId"]))
        except KeyError as e:
            raise FiLoginError(resp.status_code, f"login response missing {e}") from e
        return self.session

    def graphql(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        """POST a query; return `data`. Raises FiGraphQLError if `errors` is present."""
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables
        try:
            resp = self._http.post(GRAPHQL_PATH, json=payload)
        except httpx.RequestError:
            raise FiError("Fi query connection failed; response unavailable.") from None
        try:
            body = resp.json()
        except ValueError as e:
            raise FiError(f"non-JSON GraphQL response (HTTP {resp.status_code})") from e
        if not isinstance(body, dict):
            raise FiError(f"unexpected GraphQL response shape (HTTP {resp.status_code})")
        if body.get("errors"):
            raise FiGraphQLError(body["errors"], body.get("data"))
        if not resp.is_success:
            raise FiError(f"GraphQL HTTP {resp.status_code}; response body omitted.")
        return body.get("data")
