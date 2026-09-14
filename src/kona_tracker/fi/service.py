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

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

from kona_tracker.fi.client import FiClient, FiError, FiGraphQLError
from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    HourlyDay,
    Overnight,
    PetProfile,
    RestDay,
    RestWindow,
    Walk,
    activity_from,
    hourly_from,
    hours_from_duration,
    overnight_from,
    pets_from,
    profile_from,
    rest_from,
    rest_history,
    rest_position_from,
    split_windows,
    status_from,
    walks_from,
)
from kona_tracker.fi.queries import (
    CURRENT_USER_PETS,
    pet_activity,
    pet_hourly,
    pet_overnight,
    pet_rest,
    pet_status,
    pet_walks,
    pet_whereabouts,
)

log = logging.getLogger("kona_tracker.fi")

DEFAULT_REFRESH_SECONDS = 300.0
#: While she is out, this is how often the server may ask Fi. Fi's own GPS
#: rate setting decides how fresh the answer can possibly be -- on the
#: 2026-09-13 walk the collar's last report was about a minute old -- so
#: asking much faster than this buys nothing but requests against somebody
#: else's private API.
DEFAULT_LIVE_SECONDS = 20.0
#: The fast cadence never goes below this, whatever the setting says.
LIVE_FLOOR_SECONDS = 10.0
#: A walk button nobody remembers to switch off must not poll Fi all night,
#: so live mode expires by itself. Two hours is longer than any walk and
#: short enough that a forgotten press costs one afternoon, not a week.
DEFAULT_LIVE_MAX_SECONDS = 7200.0

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
    #: Daily rest, oldest first, one entry per day the collar has existed.
    #: Empty when the history query failed -- never a silent short list, which
    #: a chart would draw as "she slept less" rather than "we do not know".
    rest_days: list[RestDay] = field(default_factory=list)
    #: Finished activities, newest first as Fi sends them: walks and car
    #: rides, each with its own steps, distance and -- for walks -- route.
    walks: tuple[Walk, ...] = ()
    #: Last night as an interval, for the same night `window` totals.
    overnight: Overnight | None = None
    #: Today by the hour: rest and steps in 24 buckets from midnight her time.
    hourly: HourlyDay | None = None

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


#: How many daily rest windows to ask `restSummaryFeed` for. A ceiling:
#: Fi returns what it has, which was five on 2026-09-11 (the collar's whole
#: life). Two weeks is enough for a week chart plus the incomplete days at
#: either end, and small enough that a slow response is not mistaken for a
#: failure.
REST_HISTORY_DAYS = 14


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
    # Initialised here, not in the try: a failed rest query must leave an
    # empty history rather than an undefined name, and empty is the honest
    # answer -- a chart draws nothing rather than a short series that reads
    # as "she slept less those days".
    rest_days: list[RestDay] = []
    try:
        # One request, both jobs. REST_HISTORY_DAYS is a ceiling, not an
        # expectation: Fi returns the days it has, which on 2026-09-11 was
        # five -- the collar's whole life. Asking for more costs nothing.
        raw = client.graphql(pet_rest(pet.id, limit=REST_HISTORY_DAYS))
        windows = rest_from(raw, "dailyStat")
        window, today = split_windows(windows, now)
        rest_days = rest_history(windows, now, data_start)
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
    walks: tuple[Walk, ...] = ()
    try:
        walks = tuple(walks_from(client.graphql(pet_walks(pet.id))))
    except FiError as e:
        problems.append(f"Walks: {_explain(e)}")
    hourly: HourlyDay | None = None
    try:
        hourly = hourly_from(client.graphql(pet_hourly(pet.id)))
    except FiError as e:
        problems.append(f"Hourly: {_explain(e)}")
    overnight: Overnight | None = None
    if window is not None and window.start is not None:
        # The night that `window` totals: Fi keys the overnight summary by
        # the day the night starts in, which is the daily window's start
        # date. Without a completed window there is no night to ask about.
        try:
            overnight = overnight_from(client.graphql(pet_overnight(pet.id, window.start.date())))
        except FiError as e:
            problems.append(f"Sleep detail: {_explain(e)}")

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
        rest_days=rest_days,
        walks=walks,
        overnight=overnight,
        hourly=hourly,
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
        live_seconds: float = DEFAULT_LIVE_SECONDS,
        live_max_seconds: float = DEFAULT_LIVE_MAX_SECONDS,
        recorder: Any | None = None,
    ):
        self._email = email
        self._password = password
        self._ttl = max(refresh_seconds, 1.0)
        self._live_ttl = max(live_seconds, LIVE_FLOOR_SECONDS)
        self._live_max = max(live_max_seconds, 60.0)
        #: When the fast cadence stops. None means it is not running.
        self._live_until: datetime | None = None
        self._client_factory = client_factory
        self._clock = clock
        self._data_start = data_start
        self._lock = threading.Condition()
        self._snapshot: FiSnapshot | None = None
        self._refreshing = False
        # When we last *tried*, as opposed to when we last succeeded. A run
        # of failures must not turn into a request-rate retry loop against
        # somebody else's private API, so the TTL is measured from here.
        self._attempted_at: datetime | None = None
        #: Optional `store.Recorder`. Fi's hourly detail is today-only, so
        #: what is not written down before midnight is gone. Duck-typed on
        #: purpose: this module must not depend on storage existing.
        self._recorder = recorder

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
            fresh, problem = (
                None,
                f"Unexpected error talking to Fi: {type(e).__name__} (details omitted)",
            )
        # The snapshot to record, decided under the lock and used after it.
        # `fresh` is not that value: a walk's carried-over route replaces it.
        recordable: FiSnapshot | None = None
        if fresh is None:
            log.warning("Fi refresh failed: %s", problem)
        elif fresh.problem:
            log.warning("Fi refresh partial: %s", fresh.problem)
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
                        status=replace(
                            fresh.status,
                            positions=previous_status.positions,
                            positions_carried=True,
                        ),
                    )
                self._snapshot = fresh
                recordable = fresh
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
            self._lock.notify_all()
        # Outside the lock, and only for a reading that actually arrived. A
        # stale snapshot is the *same* data annotated with a failure, and
        # recording it again would invent an observation that never happened.
        # Writing here rather than inside the lock keeps a disk hiccup from
        # blocking every page waiting on this refresh; `record()` swallows its
        # own failures, so nothing below can reach the caller.
        if recordable is not None and self._recorder is not None:
            # `Recorder.record` promises not to raise, and this does not rely
            # on that promise. Anything duck-typed into this slot reaches the
            # page load through here, and a history feature must never be able
            # to take down the thing people actually open the app for.
            try:
                self._recorder.record(recordable)
            except Exception as e:
                log.warning("Recording failed: %s", type(e).__name__)

    # -- live mode ---------------------------------------------------------
    #
    # Fi decides a walk has started two to three minutes after it has, which
    # is most of a short walk spent at the resting cadence. So the person
    # holding the lead gets to say so: "Start walk" turns the fast cadence on
    # at once, and Fi's own detection stays underneath for the walks nobody
    # pressed a button for.

    def start_live(self) -> dict[str, Any]:
        """Ask Fi more often, from now until it expires or is stopped."""
        with self._lock:
            self._live_until = self._clock() + timedelta(seconds=self._live_max)
            return self._live_state()

    def stop_live(self) -> dict[str, Any]:
        with self._lock:
            self._live_until = None
            return self._live_state()

    def live_state(self) -> dict[str, Any]:
        with self._lock:
            return self._live_state()

    def _live_state(self) -> dict[str, Any]:
        """Caller holds the lock."""
        remaining = 0.0
        if self._live_until is not None:
            remaining = max(0.0, (self._live_until - self._clock()).total_seconds())
            if remaining <= 0.0:
                self._live_until = None
        return {
            "live": self._live_until is not None,
            "seconds_left": int(remaining),
            "every_seconds": int(self._live_ttl),
        }

    def _effective_ttl(self) -> float:
        """The refresh interval that applies right now. Caller holds the lock.

        Two ways to earn the fast one: somebody pressed the button, or the
        snapshot we already hold says she is on a walk. The second means a
        walk started by anyone -- Chris's sister, say -- speeds the page up
        on its own once Fi notices it.
        """
        if self._live_until is not None:
            if (self._live_until - self._clock()).total_seconds() > 0:
                return self._live_ttl
            self._live_until = None
        status = self._snapshot.status if self._snapshot else None
        if status is not None and status.activity == "walk" and not status.positions_carried:
            return self._live_ttl
        return self._ttl

    def peek(self) -> FiSnapshot | None:
        """What the cache holds, without asking Fi for anything.

        For the unauthenticated health check: a stranger pinging the URL
        must not be able to make this process talk to Fi.
        """
        with self._lock:
            return self._snapshot

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
            # Two first visitors must share one fetch, just like warm-cache
            # visitors. Previously both saw None and logged in independently.
            while self._snapshot is None and self._refreshing:
                self._lock.wait()
            cached = self._snapshot
            if cached is None:
                self._refreshing = True
        if cached is None:
            self._refresh()
            with self._lock:
                return self._snapshot  # type: ignore[return-value]

        with self._lock:
            since = self._since_attempt()
            ttl = self._effective_ttl()
            wanted = since >= ttl or (force and since >= PULL_REFRESH_FLOOR_SECONDS)
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
