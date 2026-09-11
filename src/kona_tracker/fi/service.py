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
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta

from kona_tracker.fi.client import FiClient, FiError, FiGraphQLError
from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    PetProfile,
    RestWindow,
    activity_from,
    hours_from_duration,
    pets_from,
    profile_from,
    rest_from,
    rest_position_from,
    split_windows,
    status_from,
)
from kona_tracker.fi.queries import (
    CURRENT_USER_PETS,
    pet_activity,
    pet_rest,
    pet_status,
    pet_whereabouts,
)

DEFAULT_REFRESH_SECONDS = 300.0
#: How often a *person* may make us ask Fi again (pull-to-refresh, coming back
#: to the app). Well under the background TTL, well above a thumb twitch: Fi's
#: API is private and undocumented, and a request loop against it is the one
#: thing a refresh gesture must never become.
PULL_REFRESH_FLOOR_SECONDS = 30.0


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
    #: The most recent *completed* day: the hero. Last night lives here.
    window: RestWindow | None = None
    #: The day in progress. Its SLEEP is 0 until tonight; its NAP is live.
    today: RestWindow | None = None
    activity: ActivityStats | None = None
    week: ActivityStats | None = None
    #: Photo, breed, birthday; and the collar right now. Independent of rest
    #: and steps, so a failure in one never blanks the others.
    profile: PetProfile | None = None
    status: CollarStatus | None = None
    problem: str | None = None
    stale: bool = False
    #: First date whose collar measurements belong to this setup. Older
    #: aggregates can belong to a replaced or unworn collar.
    data_start: date | None = None
    historical_totals_hidden: bool = False

    @property
    def sleep_hours(self) -> float | None:
        return hours_from_duration(self.window.sleep) if self.window else None

    @property
    def nap_hours(self) -> float | None:
        """Naps so far today, not last night's."""
        return hours_from_duration(self.today.nap) if self.today else None

    @property
    def has_data(self) -> bool:
        return any(x is not None for x in (self.window, self.today, self.activity, self.status))

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
        raws = [w.sleep for w in (self.window, self.today) if w] + [
            w.nap for w in (self.window, self.today) if w
        ]
        return any(raw is not None and hours_from_duration(raw) is None for raw in raws)


def _now() -> datetime:
    return datetime.now(UTC)


def _explain(error: FiError) -> str:
    """Say what a failure means, not just that one happened.

    A GraphQL error on a query that used to work almost always means Fi
    renamed or removed a field: these documents came from pytryfi, which has
    not shipped since Dec 2023. So say that, and point at the probe, rather
    than surfacing "Fi GraphQL error: GraphQL error".

    Note what this deliberately does *not* do: it replaces Fi's own text
    rather than repeating it. The text would be safe — `FiGraphQLError`
    already restricts it to schema identifiers — but "Cannot query field
    \"sleepAmounts\" on type \"RestSummaryData\"" is not a sentence to put
    in front of someone checking on their dog. `kona probe` is where the
    field names belong.

    (A failure in `login` or the pets query skips this function entirely:
    `FiService._refresh` catches those and uses `str(e)`, so allowlisted
    text *can* reach the page by that path. That is fine — it is schema
    identifiers only — but it is why the allowlist is tested as hard as it
    is, and why it must never be widened casually.)
    """
    if isinstance(error, FiGraphQLError):
        return (
            "Fi rejected the query, which usually means it renamed a field. "
            "Run `kona probe` to see what Fi calls it now."
        )
    return str(error)


def fetch_snapshot(
    client: FiClient,
    email: str,
    password: str,
    now: datetime | None = None,
    data_start: date | None = None,
) -> FiSnapshot:
    """One full round trip: log in, find the pet, read rest and activity.

    Raises `FiError` on login failure — without a session there is nothing to
    show. Once logged in, rest and activity are independent: losing one must
    not blank the other. `now` decides which rest window counts as "last
    night"; tests pin it so fixtures do not age.
    """
    now = now or _now()
    client.login(email, password)
    pets = pets_from(client.graphql(CURRENT_USER_PETS))
    if not pets:
        raise FiError("Logged in, but the account has no pets. Is the collar set up in the Fi app?")
    pet = pets[0]

    window: RestWindow | None = None
    today: RestWindow | None = None
    activity: ActivityStats | None = None
    week: ActivityStats | None = None
    profile: PetProfile | None = None
    status: CollarStatus | None = None
    problems: list[str] = []
    try:
        windows = rest_from(client.graphql(pet_rest(pet.id, limit=2)), "dailyStat")
        window, today = split_windows(windows, now)
        if data_start and window and (window.start is None or window.start.date() < data_start):
            window = None
        if window is None and today is None:
            problems.append("Fi returned no rest windows yet.")
    except FiError as e:
        problems.append(f"Sleep: {_explain(e)}")
    try:
        data = client.graphql(pet_activity(pet.id))
        activity = activity_from(data, "dailyStat")
        week = activity_from(data, "weeklyStat")
        # Fi does not tell us the weekly bucket's start. Seven full days
        # after the cutoff is the first point where none of that aggregate
        # can belong to the previous collar.
        if data_start and now.date() < data_start + timedelta(days=7):
            week = None
    except FiError as e:
        problems.append(f"Steps: {_explain(e)}")
    try:
        data = client.graphql(pet_status(pet.id))
        profile = profile_from(data)
        status = status_from(data)
    except FiError as e:
        problems.append(f"Collar: {_explain(e)}")
    try:
        # Its own round trip on purpose: the field is sourced from pytryfi,
        # not yet seen from her collar, and a rejected field fails the whole
        # document it is in. Here that costs the map point and nothing else.
        rest_position = rest_position_from(client.graphql(pet_whereabouts(pet.id)))
        if status is not None:
            status = replace(status, rest_position=rest_position)
        elif rest_position is not None:
            status = CollarStatus(rest_position=rest_position)
    except FiError as e:
        problems.append(f"Location: {_explain(e)}")

    return FiSnapshot(
        fetched_at=now,
        pet_name=pet.name,
        pet_id=pet.id,
        window=window,
        today=today,
        activity=activity,
        week=week,
        profile=profile,
        status=status,
        problem=" ".join(problems) or None,
        data_start=data_start,
        historical_totals_hidden=bool(data_start and now.date() < data_start + timedelta(days=7)),
    )


class FiService:
    """Cache in front of `fetch_snapshot`, refreshed at most once per TTL."""

    def __init__(
        self,
        email: str,
        password: str,
        refresh_seconds: float = DEFAULT_REFRESH_SECONDS,
        client_factory=FiClient,
        clock: Callable[[], datetime] = _now,
        data_start: date | None = None,
    ):
        self._email = email
        self._password = password
        self._ttl = max(refresh_seconds, 1.0)
        self._client_factory = client_factory
        self._clock = clock
        self._data_start = data_start
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
            return fetch_snapshot(
                client,
                self._email,
                self._password,
                now=self._clock(),
                data_start=self._data_start,
            )
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
            self._attempted_at = self._clock()
            if fresh is not None:
                # A walk's route comes only with the walk. Once she is back
                # to resting, keep the last route seen by this process and let
                # its own timestamps say how old it is; the page prefers the
                # resting position when Fi sends one, and never relabels an
                # old fix as a current location.
                previous_status = self._snapshot.status if self._snapshot else None
                if (
                    fresh.status is not None
                    and not fresh.status.positions
                    and previous_status is not None
                    and previous_status.positions
                ):
                    fresh = replace(
                        fresh,
                        status=replace(fresh.status, positions=previous_status.positions),
                    )
                self._snapshot = fresh
            elif self._snapshot is not None:
                # Keep the data, stamp the failure; `fetched_at` stays at the
                # moment the data was true, which is what "as of" must mean.
                # `stale` is what lets the page say "last good reading" here
                # and only here.
                self._snapshot = replace(self._snapshot, problem=problem, stale=True)
            else:
                self._snapshot = FiSnapshot(
                    fetched_at=self._clock(), problem=problem, data_start=self._data_start
                )
            self._refreshing = False

    def _since_attempt(self) -> float:
        if self._attempted_at is None:
            return float("inf")
        return (self._clock() - self._attempted_at).total_seconds()

    def snapshot(self, force: bool = False) -> FiSnapshot:
        """The best answer available now.

        The first call blocks on Fi because there is nothing else to return.
        Every later call returns immediately and, if the cache has aged out,
        kicks off a refresh that some later request will benefit from.

        `force` is a person asking (pull-to-refresh): refresh *now*, on this
        request, so the page they get back is current -- unless the last
        attempt was under `PULL_REFRESH_FLOOR_SECONDS` ago, in which case the
        cache is the answer and its "Updated" time says so honestly.
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
            since = self._since_attempt()
            wanted = since >= self._ttl or (force and since >= PULL_REFRESH_FLOOR_SECONDS)
            due = wanted and not self._refreshing
            if due:
                self._refreshing = True
        if due and force:
            self._refresh()
            with self._lock:
                return self._snapshot  # type: ignore[return-value]
        if due:
            threading.Thread(target=self._refresh, name="fi-refresh", daemon=True).start()
        return cached
