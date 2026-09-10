"""Keeping one recent answer from Fi, so the page never waits on the network.

Fi's API is undocumented, unversioned and not ours. Two rules follow. We log
in once per refresh rather than once per request, because polling somebody
else's private API from every page load is how an account gets throttled or
banned. And a refresh that fails never destroys the answer we already have:
the page keeps showing last night's sleep with an "as of" stamp and says what
went wrong, which is strictly more useful than a blank dial.

The refresh runs on a background thread, so only the very first load of the
day pays the round trip.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from kona_tracker.fi.client import FiClient, FiError, FiGraphQLError
from kona_tracker.fi.parse import (
    ActivityStats,
    RestWindow,
    activity_from,
    hours_from_duration,
    pets_from,
    rest_from,
)
from kona_tracker.fi.queries import CURRENT_USER_PETS, pet_activity, pet_rest

DEFAULT_REFRESH_SECONDS = 300.0


@dataclass(frozen=True)
class FiSnapshot:
    """Everything the Activity page is allowed to say, and when we learned it.

    `problem` can coexist with real data, and there are two different ways
    that happens. They must not be described the same way:

    - **partial** (`stale=False`): this reading is current, but one of the
      queries failed. Steps arrived, sleep did not. Nothing here is old.
    - **stale** (`stale=True`): a whole refresh failed, so the numbers are
      from the last time Fi answered and `fetched_at` says when that was.

    Calling the first one "the last good reading" is a lie, which is why the
    flag exists rather than the template guessing from `problem` alone.
    """

    fetched_at: datetime
    pet_name: str = ""
    pet_id: str = ""
    window: RestWindow | None = None
    activity: ActivityStats | None = None
    problem: str | None = None
    stale: bool = False

    @property
    def sleep_hours(self) -> float | None:
        return hours_from_duration(self.window.sleep) if self.window else None

    @property
    def nap_hours(self) -> float | None:
        return hours_from_duration(self.window.nap) if self.window else None

    @property
    def has_data(self) -> bool:
        return self.window is not None or self.activity is not None

    @property
    def partial(self) -> bool:
        """Fresh, but something in it is missing because a query failed."""
        return bool(self.problem) and self.has_data and not self.stale

    @property
    def unit_suspect(self) -> bool:
        """A duration came back that seconds cannot explain.

        Loud on purpose: it means Fi changed units under us, and the page
        shows the raw number rather than a confident wrong one.
        """
        if not self.window:
            return False
        return any(
            raw is not None and hours_from_duration(raw) is None
            for raw in (self.window.sleep, self.window.nap)
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _explain(error: FiError) -> str:
    """Say what a failure means, not just that one happened.

    A GraphQL error on a query that used to work almost always means Fi
    renamed or removed a field: these documents came from pytryfi, which has
    not shipped since Dec 2023. The client strips the server's message before
    it reaches here (it can carry account data), so the page cannot show the
    field name — but `kona probe` keeps the allowlisted schema-validation
    text, which names it. Point at the probe rather than at a dead end.
    """
    if isinstance(error, FiGraphQLError):
        return (
            "Fi rejected the query, which usually means it renamed a field. "
            "Run `kona probe` to see what Fi calls it now."
        )
    return str(error)


def fetch_snapshot(client: FiClient, email: str, password: str) -> FiSnapshot:
    """One full round trip: log in, find the pet, read rest and activity.

    Raises `FiError` on login failure — without a session there is nothing to
    show. Once logged in, rest and activity are independent: losing one must
    not blank the other.
    """
    client.login(email, password)
    pets = pets_from(client.graphql(CURRENT_USER_PETS))
    if not pets:
        raise FiError("Logged in, but the account has no pets. Is the collar set up in the Fi app?")
    pet = pets[0]

    window: RestWindow | None = None
    activity: ActivityStats | None = None
    problems: list[str] = []
    try:
        windows = rest_from(client.graphql(pet_rest(pet.id, limit=1)), "dailyStat")
        window = windows[0] if windows else None
        if window is None:
            problems.append("Fi returned no rest windows yet.")
    except FiError as e:
        problems.append(f"Sleep: {_explain(e)}")
    try:
        activity = activity_from(client.graphql(pet_activity(pet.id)))
    except FiError as e:
        problems.append(f"Steps: {_explain(e)}")

    return FiSnapshot(
        fetched_at=_now(),
        pet_name=pet.name,
        pet_id=pet.id,
        window=window,
        activity=activity,
        problem=" ".join(problems) or None,
    )


class FiService:
    """Cache in front of `fetch_snapshot`, refreshed at most once per TTL."""

    def __init__(
        self,
        email: str,
        password: str,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        client_factory=FiClient,
    ):
        self._email = email
        self._password = password
        self._ttl = max(refresh_seconds, 1.0)
        self._client_factory = client_factory
        self._lock = threading.Lock()
        self._snapshot: FiSnapshot | None = None
        self._refreshing = False
        # When we last *tried*, as opposed to when we last succeeded. A run
        # of failures must not turn into a request-rate retry loop against
        # somebody else's private API, so the TTL is measured from here.
        self._attempted_at: datetime | None = None

    def _fetch(self) -> FiSnapshot:
        client = self._client_factory()
        try:
            return fetch_snapshot(client, self._email, self._password)
        finally:
            client.close()

    def _refresh(self) -> None:
        """Replace the cache, or annotate it. Never leaves it worse."""
        try:
            fresh = self._fetch()
            problem = None
        except FiError as e:
            fresh, problem = None, str(e)
        except Exception as e:  # a bug here must not kill the page
            fresh, problem = None, f"Unexpected error talking to Fi: {type(e).__name__}: {e}"
        with self._lock:
            self._attempted_at = _now()
            if fresh is not None:
                self._snapshot = fresh
            elif self._snapshot is not None:
                # Keep the data, stamp the failure; `fetched_at` stays at the
                # moment the data was true, which is what "as of" must mean.
                # `stale` is what lets the page say "last good reading" here
                # and only here.
                self._snapshot = replace(self._snapshot, problem=problem, stale=True)
            else:
                self._snapshot = FiSnapshot(fetched_at=_now(), problem=problem)
            self._refreshing = False

    def _stale(self) -> bool:
        if self._attempted_at is None:
            return True
        return (_now() - self._attempted_at).total_seconds() >= self._ttl

    def snapshot(self) -> FiSnapshot:
        """The best answer available now.

        The first call blocks on Fi because there is nothing else to return.
        Every later call returns immediately and, if the cache has aged out,
        kicks off a refresh that some later request will benefit from.
        """
        with self._lock:
            cached = self._snapshot
            if cached is None:
                self._refreshing = True
        if cached is None:
            self._refresh()
            with self._lock:
                return self._snapshot  # type: ignore[return-value]

        with self._lock:
            due = self._stale() and not self._refreshing
            if due:
                self._refreshing = True
        if due:
            threading.Thread(target=self._refresh, name="fi-refresh", daemon=True).start()
        return cached
