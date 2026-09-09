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
    """Login rejected. Carries the HTTP status and (secret-free) body."""

    def __init__(self, status: int, body: str):
        self.status = status
        self.body = body
        super().__init__(f"Fi login failed (HTTP {status}): {body}")


class FiGraphQLError(FiError):
    """GraphQL returned `errors`. Kept whole: Fi's validation errors include
    'Did you mean ...?' hints that are exactly what the probe wants."""

    def __init__(self, errors: list[dict[str, Any]], data: Any = None):
        self.errors = errors
        self.data = data
        messages = "; ".join(str(e.get("message", e)) for e in errors)
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
        resp = self._http.post(LOGIN_PATH, data={"email": email, "password": password})
        body: Any
        try:
            body = resp.json()
        except ValueError:
            body = None
        if not resp.is_success or not isinstance(body, dict) or "error" in body:
            # Never echo the password; the request body is not part of `resp`.
            detail = body.get("error", body) if isinstance(body, dict) else resp.text[:500]
            raise FiLoginError(resp.status_code, str(detail))
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
        resp = self._http.post(GRAPHQL_PATH, json=payload)
        try:
            body = resp.json()
        except ValueError as e:
            raise FiError(f"non-JSON GraphQL response (HTTP {resp.status_code})") from e
        if not isinstance(body, dict):
            raise FiError(f"unexpected GraphQL response shape (HTTP {resp.status_code})")
        if body.get("errors"):
            raise FiGraphQLError(body["errors"], body.get("data"))
        if not resp.is_success:
            raise FiError(f"GraphQL HTTP {resp.status_code}: {resp.text[:500]}")
        return body.get("data")
