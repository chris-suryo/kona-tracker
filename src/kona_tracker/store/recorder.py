"""Write what a refresh saw into the store, and never break the refresh.

The contract, in order of importance:

1. **This can never take the app down.** `record()` catches everything,
   including its own bugs, logs, and returns. A dog-watching page that fails
   to load because a history table would not write is a strictly worse app
   than one that quietly stops recording. Every caller is inside the Fi
   refresh path, which is inside the page load.
2. **Never overwrite something known with nothing.** Fi answers partially all
   the time -- steps arrive, rest does not -- and the same hour gets written
   repeatedly as the day fills in. A later refresh that knows less must not
   erase what an earlier one knew, so every update is `COALESCE(new, old)`.
   This is the rule that makes re-recording safe, and it is enforced in SQL
   rather than in Python so it holds for every path into the table.
3. **NULL means "not told", never zero.** Preserved end to end: the parser
   already distinguishes them, and the schema keeps the distinction.

A connection is opened per call rather than held. Refreshes happen at most
every twenty seconds and usually every five minutes, so the cost is nothing
next to the alternative -- `sqlite3` objects are not safe to share between
threads, and `_refresh` runs on whichever thread asked for the page.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime
from typing import Any

from kona_tracker.store.schema import connect, migrate

log = logging.getLogger("kona_tracker.store")

#: Which collar these rows came from. One value today; the column exists
#: because the stated plan is to replace Fi, and rows written before that
#: happens must still be attributable afterwards.
FI = "fi"


def _iso(value: datetime | date | None) -> str | None:
    return None if value is None else value.isoformat()


def _day_of(value: datetime | date | None) -> str | None:
    """The calendar day a timestamp belongs to, as Fi reckons it.

    Deliberately `.date()` on whatever timezone the value carries rather than
    a conversion to UTC: the parser has already put these in her timezone, and
    converting would slide an evening walk into the following day.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _flag(value: bool | None) -> int | None:
    return None if value is None else int(value)


class Recorder:
    """Appends a `FiSnapshot` to a SQLite file. Idempotent per snapshot."""

    def __init__(self, path: str, source: str = FI):
        self._path = path
        self._source = source
        self._broken = False

    def record(self, snapshot: Any) -> bool:
        """Write everything in `snapshot`. True if it landed.

        Returns rather than raises, always. The one piece of state kept is
        `_broken`: after a failure that is clearly about the file itself
        rather than this snapshot, stop trying, so a misconfigured path does
        not write a warning line on every page load for the rest of the day.
        """
        if self._broken:
            return False
        try:
            conn = connect(self._path)
        except Exception as e:
            self._broken = True
            log.warning(
                "Recording is off: could not open %s (%s). Fix KONA_DB_PATH and restart.",
                self._path,
                type(e).__name__,
            )
            return False
        try:
            migrate(conn)
            with conn:
                self._write(conn, snapshot)
            return True
        except sqlite3.DatabaseError as e:
            # A malformed file or a newer schema will not fix itself.
            self._broken = True
            log.warning("Recording is off: %s (%s)", e, type(e).__name__)
            return False
        except Exception as e:
            # A bug in one of the writers below, or a snapshot shape nobody
            # anticipated. Worth one line, and worth trying again next time:
            # the next snapshot may be perfectly ordinary.
            log.warning("Did not record this refresh: %s", type(e).__name__)
            return False
        finally:
            conn.close()

    # -- the writers -------------------------------------------------------
    #
    # Each takes the open connection and writes one part. They are separate
    # so that a change to Fi's walk shape cannot disturb the hourly table,
    # which is the one that cannot be re-fetched.

    def _write(self, conn: sqlite3.Connection, snap: Any) -> None:
        pet = snap.pet_id or ""
        seen = _iso(snap.fetched_at)
        self._hours(conn, snap, pet, seen)
        self._days(conn, snap, pet, seen)
        self._walks(conn, snap, pet, seen)
        self._positions(conn, snap, pet)
        self._device(conn, snap, pet, seen)
        self._overnight(conn, snap, pet, seen)

    def _hours(self, conn: sqlite3.Connection, snap: Any, pet: str, seen: str | None) -> None:
        hourly = snap.hourly
        if hourly is None or hourly.start is None:
            return
        day = _day_of(hourly.start)
        rows = []
        for index, bucket in enumerate(hourly.hours):
            # An hour we know nothing about is not a row. Writing 24 rows of
            # NULL every refresh would fill the table with the absence of
            # information and make "did we ever see this hour" unanswerable.
            if bucket.steps is None and bucket.sleep_s is None and bucket.nap_s is None:
                continue
            rows.append(
                (self._source, pet, day, index, bucket.steps, bucket.sleep_s, bucket.nap_s, seen)
            )
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO hour (source, pet_id, day, hour, steps, sleep_s, nap_s, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, pet_id, day, hour) DO UPDATE SET
                steps       = COALESCE(excluded.steps,   hour.steps),
                sleep_s     = COALESCE(excluded.sleep_s, hour.sleep_s),
                nap_s       = COALESCE(excluded.nap_s,   hour.nap_s),
                observed_at = excluded.observed_at
            """,
            rows,
        )

    def _days(self, conn: sqlite3.Connection, snap: Any, pet: str, seen: str | None) -> None:
        rows = []
        for rest in snap.rest_days:
            day = _day_of(rest.window.start)
            if day is None:
                continue
            rows.append(
                (
                    self._source,
                    pet,
                    day,
                    None,  # steps: the history feed carries rest only
                    None,
                    None,
                    rest.window.sleep,
                    rest.window.nap,
                    _flag(rest.complete),
                    _flag(rest.in_progress),
                    _flag(rest.partial_first_day),
                    seen,
                )
            )
        # Today's steps come from a different query than today's rest, so they
        # are a second write into the same row rather than part of the loop.
        # COALESCE means whichever lands first is not clobbered by the other.
        if snap.activity is not None and snap.hourly is not None and snap.hourly.start is not None:
            rows.append(
                (
                    self._source,
                    pet,
                    _day_of(snap.hourly.start),
                    snap.activity.steps,
                    snap.activity.step_goal,
                    snap.activity.distance,
                    None,
                    None,
                    None,
                    None,
                    None,
                    seen,
                )
            )
        if not rows:
            return
        conn.executemany(
            """
            INSERT INTO day (source, pet_id, day, steps, step_goal, distance,
                             sleep_s, nap_s, complete, in_progress,
                             partial_first_day, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, pet_id, day) DO UPDATE SET
                steps             = COALESCE(excluded.steps,     day.steps),
                step_goal         = COALESCE(excluded.step_goal, day.step_goal),
                distance          = COALESCE(excluded.distance,  day.distance),
                sleep_s           = COALESCE(excluded.sleep_s,   day.sleep_s),
                nap_s             = COALESCE(excluded.nap_s,     day.nap_s),
                complete          = COALESCE(excluded.complete,          day.complete),
                in_progress       = COALESCE(excluded.in_progress,       day.in_progress),
                partial_first_day = COALESCE(excluded.partial_first_day, day.partial_first_day),
                observed_at       = excluded.observed_at
            """,
            rows,
        )

    def _walks(self, conn: sqlite3.Connection, snap: Any, pet: str, seen: str | None) -> None:
        for walk in snap.walks:
            if not walk.id:
                continue
            conn.execute(
                """
                INSERT INTO walk (source, walk_id, pet_id, kind, started_at, ended_at,
                                  steps, distance_m, area_name, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, walk_id) DO UPDATE SET
                    ended_at    = COALESCE(excluded.ended_at,   walk.ended_at),
                    steps       = COALESCE(excluded.steps,      walk.steps),
                    distance_m  = COALESCE(excluded.distance_m, walk.distance_m),
                    area_name   = COALESCE(excluded.area_name,  walk.area_name),
                    observed_at = excluded.observed_at
                """,
                (
                    self._source,
                    walk.id,
                    pet,
                    walk.kind,
                    _iso(walk.start),
                    _iso(walk.end),
                    walk.steps,
                    walk.distance_m,
                    walk.area_name,
                    seen,
                ),
            )
            if not walk.path:
                continue
            # OR IGNORE, not upsert: a finished walk's route does not change,
            # and re-writing it on every refresh for as long as it stays in
            # the feed would be pure churn.
            conn.executemany(
                """
                INSERT OR IGNORE INTO walk_point
                    (source, walk_id, seq, latitude, longitude, recorded_at, accuracy_m)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        self._source,
                        walk.id,
                        seq,
                        point.latitude,
                        point.longitude,
                        _iso(point.recorded_at),
                        point.accuracy_m,
                    )
                    for seq, point in enumerate(walk.path)
                ],
            )

    def _positions(self, conn: sqlite3.Connection, snap: Any, pet: str) -> None:
        status = snap.status
        if status is None:
            return
        points = list(status.positions)
        if status.rest_position is not None:
            points.append(status.rest_position)
        rows = [
            (
                self._source,
                pet,
                _iso(point.recorded_at),
                point.latitude,
                point.longitude,
                point.accuracy_m,
                status.area_name,
            )
            # A fix with no timestamp cannot be placed in a history, and
            # inventing one would put her somewhere at a time she was not
            # there. Dropped, which is the honest loss.
            for point in points
            if point.recorded_at is not None
        ]
        if not rows:
            return
        conn.executemany(
            """
            INSERT OR IGNORE INTO position
                (source, pet_id, recorded_at, latitude, longitude, accuracy_m, area_name)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def _device(self, conn: sqlite3.Connection, snap: Any, pet: str, seen: str | None) -> None:
        status = snap.status
        # Keyed on the collar's own connection time: without one there is no
        # way to tell a new reading from the same reading seen again, and a
        # row per page load would swamp the table.
        if status is None or status.connection_at is None:
            return
        conn.execute(
            """
            INSERT OR IGNORE INTO device_state
                (source, pet_id, connection_at, battery_percent, time_to_empty_s,
                 signal_percent, on_base, activity, mode, escaped, lost,
                 area_name, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self._source,
                pet,
                _iso(status.connection_at),
                status.battery_percent,
                status.time_to_empty_s,
                status.signal_percent,
                _flag(status.on_base),
                status.activity,
                status.mode,
                _flag(status.escaped),
                _flag(status.lost),
                status.area_name,
                seen,
            ),
        )

    def _overnight(self, conn: sqlite3.Connection, snap: Any, pet: str, seen: str | None) -> None:
        night = snap.overnight
        if night is None:
            return
        day = _day_of(night.date)
        if day is None:
            return
        conn.execute(
            """
            INSERT INTO overnight
                (source, pet_id, day, sleep_s, sleep_start, sleep_end, observed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, pet_id, day) DO UPDATE SET
                sleep_s     = COALESCE(excluded.sleep_s,     overnight.sleep_s),
                sleep_start = COALESCE(excluded.sleep_start, overnight.sleep_start),
                sleep_end   = COALESCE(excluded.sleep_end,   overnight.sleep_end),
                observed_at = excluded.observed_at
            """,
            (
                self._source,
                pet,
                day,
                night.sleep_seconds,
                _iso(night.sleep_start),
                _iso(night.sleep_end),
                seen,
            ),
        )
        if not night.interruptions:
            return
        conn.executemany(
            """
            INSERT OR IGNORE INTO overnight_interruption
                (source, pet_id, day, seq, start_at, end_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (self._source, pet, day, seq, _iso(start), _iso(end))
                for seq, (start, end) in enumerate(night.interruptions)
            ],
        )
