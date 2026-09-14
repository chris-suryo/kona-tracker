"""The recorder writes what a refresh saw, and never breaks the refresh.

Two properties carry most of the weight here and are worth naming, because
both are the kind of thing that fails silently and is discovered a month later
as a hole in a chart:

- **A later, poorer reading must not erase an earlier, richer one.** Fi answers
  partially all the time, and the same hour is written over and over as the day
  fills in. If a partial answer overwrote a full one with NULL, the store would
  slowly converge on whatever the *last* refresh of the day happened to know.
- **Nothing in here may ever raise into the caller.** Every call site is inside
  the Fi refresh, which is inside a page load.
"""

from __future__ import annotations

import datetime as dt

import pytest

from kona_tracker.fi.parse import (
    ActivityStats,
    CollarStatus,
    HourBucket,
    HourlyDay,
    LocationPoint,
    Overnight,
    RestDay,
    RestWindow,
    Walk,
)
from kona_tracker.fi.service import FiService, FiSnapshot
from kona_tracker.store import SCHEMA_VERSION, Recorder, connect, migrate

U = dt.UTC
NOW = dt.datetime(2026, 9, 14, 16, 0, tzinfo=U)
DAY_START = dt.datetime(2026, 9, 14, 0, 0, tzinfo=U)


def snapshot(**kwargs) -> FiSnapshot:
    base = {"fetched_at": NOW, "pet_name": "Kona", "pet_id": "kona1"}
    base.update(kwargs)
    return FiSnapshot(**base)


def hourly(*buckets: HourBucket, start: dt.datetime | None = DAY_START) -> HourlyDay:
    return HourlyDay(start=start, hours=tuple(buckets), rest_present=True, steps_present=True)


def rows(path, sql: str) -> list[tuple]:
    conn = connect(str(path))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# -- the hourly table, which is the reason the module exists ---------------


def test_hours_are_written_with_their_day_and_index(tmp_path):
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(snapshot(hourly=hourly(HourBucket(steps=100, sleep_s=3600, nap_s=0))))
    assert rows(db, "SELECT day, hour, steps, sleep_s, nap_s FROM hour") == [
        ("2026-09-14", 0, 100.0, 3600.0, 0.0)
    ]


def test_an_hour_we_know_nothing_about_is_not_a_row(tmp_path):
    """24 rows of NULL every refresh would record the absence of information
    and make "have we ever seen this hour" unanswerable."""
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(
        snapshot(hourly=hourly(HourBucket(steps=5), HourBucket(), HourBucket(sleep_s=60)))
    )
    assert [r[0] for r in rows(db, "SELECT hour FROM hour ORDER BY hour")] == [0, 2]


def test_a_later_partial_reading_does_not_erase_an_earlier_full_one(tmp_path):
    """The property the whole design turns on.

    First refresh knows steps and sleep. Second knows only steps -- which is
    exactly what a half-failed Fi call looks like. The sleep figure must
    survive, because nothing will ever tell us again.
    """
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=100, sleep_s=3600))))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=140, sleep_s=None))))
    assert rows(db, "SELECT steps, sleep_s FROM hour") == [(140.0, 3600.0)]


def test_a_later_reading_does_update_what_it_knows(tmp_path):
    """The other half: COALESCE must not freeze the first value either."""
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=100))))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=900))))
    assert rows(db, "SELECT steps FROM hour") == [(900.0,)]


def test_zero_is_recorded_as_zero_and_not_treated_as_unknown(tmp_path):
    """A dog who did not move is not the same as an hour nobody asked about.
    `COALESCE` is on NULL, not on falsiness -- this pins that it stays so."""
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=500))))
    rec.record(snapshot(hourly=hourly(HourBucket(steps=0))))
    assert rows(db, "SELECT steps FROM hour") == [(0.0,)]


def test_hours_without_a_day_start_are_skipped(tmp_path):
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(snapshot(hourly=hourly(HourBucket(steps=5), start=None)))
    assert rows(db, "SELECT * FROM hour") == []


# -- daily totals ---------------------------------------------------------


def test_rest_history_and_todays_steps_merge_into_one_day_row(tmp_path):
    """They come from different queries and are written separately; the row
    is keyed on the day, so the two halves must meet rather than collide."""
    db = tmp_path / "kona.db"
    window = RestWindow(start=DAY_START, end=None, sleep=30000, nap=1200)
    Recorder(str(db)).record(
        snapshot(
            rest_days=[RestDay(window=window, complete=False, in_progress=True)],
            activity=ActivityStats(steps=21050, step_goal=28000, distance=6139),
            hourly=hourly(HourBucket(steps=1)),
        )
    )
    assert rows(db, "SELECT day, steps, step_goal, sleep_s, nap_s, in_progress FROM day") == [
        ("2026-09-14", 21050.0, 28000.0, 30000.0, 1200.0, 1)
    ]


def test_a_day_with_no_start_is_skipped_rather_than_guessed(tmp_path):
    db = tmp_path / "kona.db"
    window = RestWindow(start=None, end=None, sleep=100, nap=0)
    Recorder(str(db)).record(snapshot(rest_days=[RestDay(window=window, complete=True)]))
    assert rows(db, "SELECT * FROM day") == []


# -- walks ----------------------------------------------------------------


def walk(**kwargs) -> Walk:
    base = {
        "id": "w1",
        "kind": "walk",
        "start": dt.datetime(2026, 9, 14, 13, 25, tzinfo=U),
        "end": dt.datetime(2026, 9, 14, 13, 46, tzinfo=U),
        "steps": 3853,
        "distance_m": 1749,
    }
    base.update(kwargs)
    return Walk(**base)


def test_the_same_walk_seen_repeatedly_is_one_row(tmp_path):
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    for _ in range(3):
        rec.record(snapshot(walks=(walk(),)))
    assert rows(db, "SELECT COUNT(*) FROM walk") == [(1,)]


def test_a_walks_route_is_stored_in_order(tmp_path):
    db = tmp_path / "kona.db"
    path = (LocationPoint(1.0, 2.0), LocationPoint(3.0, 4.0), LocationPoint(5.0, 6.0))
    rec = Recorder(str(db))
    rec.record(snapshot(walks=(walk(path=path),)))
    rec.record(snapshot(walks=(walk(path=path),)))  # re-seen, not re-written
    assert rows(db, "SELECT seq, latitude, longitude FROM walk_point ORDER BY seq") == [
        (0, 1.0, 2.0),
        (1, 3.0, 4.0),
        (2, 5.0, 6.0),
    ]


def test_a_walk_that_gains_an_end_time_keeps_its_row(tmp_path):
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    rec.record(snapshot(walks=(walk(end=None, distance_m=None),)))
    rec.record(snapshot(walks=(walk(),)))
    assert rows(db, "SELECT ended_at, distance_m FROM walk") == [
        ("2026-09-14T13:46:00+00:00", 1749.0)
    ]


# -- positions ------------------------------------------------------------


def status(**kwargs) -> CollarStatus:
    base = {"connection_at": dt.datetime(2026, 9, 14, 15, 59, tzinfo=U), "battery_percent": 68}
    base.update(kwargs)
    return CollarStatus(**base)


def test_positions_are_keyed_on_the_collars_own_timestamp(tmp_path):
    db = tmp_path / "kona.db"
    at = dt.datetime(2026, 9, 14, 15, 30, tzinfo=U)
    rec = Recorder(str(db))
    for _ in range(4):
        rec.record(snapshot(status=status(positions=(LocationPoint(1.0, 2.0, at),))))
    assert rows(db, "SELECT COUNT(*) FROM position") == [(1,)]


def test_a_fix_with_no_timestamp_is_dropped_not_stamped_with_now(tmp_path):
    """Inventing a time would place her somewhere at a moment she was not
    there, which is worse than the missing row."""
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(snapshot(status=status(positions=(LocationPoint(1.0, 2.0),))))
    assert rows(db, "SELECT * FROM position") == []


# -- the collar -----------------------------------------------------------


def test_an_unchanged_collar_reading_is_recorded_once(tmp_path):
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    for _ in range(5):
        rec.record(snapshot(status=status()))
    assert rows(db, "SELECT COUNT(*), battery_percent FROM device_state") == [(1, 68.0)]


def test_a_new_connection_time_is_a_new_row(tmp_path):
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    rec.record(snapshot(status=status()))
    rec.record(
        snapshot(
            status=status(
                connection_at=dt.datetime(2026, 9, 14, 16, 4, tzinfo=U), battery_percent=67
            )
        )
    )
    assert rows(db, "SELECT COUNT(*) FROM device_state") == [(2,)]


def test_a_collar_with_no_connection_time_is_not_recorded(tmp_path):
    """Without it there is no way to tell a new reading from the same one
    seen again, and a row per page load would swamp the table."""
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(snapshot(status=status(connection_at=None)))
    assert rows(db, "SELECT * FROM device_state") == []


# -- overnight ------------------------------------------------------------


def test_overnight_and_its_interruptions(tmp_path):
    db = tmp_path / "kona.db"
    night = Overnight(
        date=dt.datetime(2026, 9, 13, tzinfo=U),
        sleep_seconds=35513,
        sleep_start=dt.datetime(2026, 9, 14, 3, 20, tzinfo=U),
        sleep_end=dt.datetime(2026, 9, 14, 11, 4, tzinfo=U),
        interruptions=(
            (dt.datetime(2026, 9, 14, 6, 12, tzinfo=U), dt.datetime(2026, 9, 14, 6, 31, tzinfo=U)),
            (dt.datetime(2026, 9, 14, 9, 40, tzinfo=U), dt.datetime(2026, 9, 14, 9, 52, tzinfo=U)),
        ),
    )
    rec = Recorder(str(db))
    rec.record(snapshot(overnight=night))
    rec.record(snapshot(overnight=night))
    assert rows(db, "SELECT day, sleep_s FROM overnight") == [("2026-09-13", 35513.0)]
    assert rows(db, "SELECT COUNT(*) FROM overnight_interruption") == [(2,)]


# -- every row says where it came from ------------------------------------


def test_every_table_records_its_source(tmp_path):
    """The stated plan is to replace Fi. Rows written before that must still
    be attributable afterwards, or the comparison this store exists for
    cannot be made."""
    db = tmp_path / "kona.db"
    Recorder(str(db)).record(
        snapshot(
            hourly=hourly(HourBucket(steps=1)),
            rest_days=[RestDay(window=RestWindow(DAY_START, None, 1, 1), complete=True)],
            walks=(walk(path=(LocationPoint(1.0, 2.0),)),),
            status=status(positions=(LocationPoint(1.0, 2.0, NOW),)),
            overnight=Overnight(date=DAY_START, sleep_seconds=1, sleep_start=None, sleep_end=None),
        )
    )
    for table in ("hour", "day", "walk", "walk_point", "position", "device_state", "overnight"):
        found = rows(db, f"SELECT DISTINCT source FROM {table}")
        assert found == [("fi",)], f"{table} did not record its source: {found}"


# -- it must never break the caller ---------------------------------------


def test_an_unwritable_path_does_not_raise(tmp_path):
    rec = Recorder(str(tmp_path / "no" / "such" / "dir" / "kona.db"))
    assert rec.record(snapshot()) is False


def test_a_file_that_is_not_a_database_does_not_raise(tmp_path):
    db = tmp_path / "kona.db"
    db.write_bytes(b"this is not a SQLite file, it is a photograph of a dog" * 40)
    assert Recorder(str(db)).record(snapshot()) is False


def test_a_snapshot_of_the_wrong_shape_does_not_raise(tmp_path):
    class NotASnapshot:
        pet_id = "x"

    assert Recorder(str(tmp_path / "kona.db")).record(NotASnapshot()) is False


def test_a_broken_database_is_not_retried_on_every_page_load(tmp_path, caplog):
    """A misconfigured path should cost one warning, not one per refresh for
    the rest of the day."""
    db = tmp_path / "kona.db"
    db.write_bytes(b"not a database" * 100)
    rec = Recorder(str(db))
    with caplog.at_level("WARNING"):
        for _ in range(5):
            rec.record(snapshot())
    assert sum("Recording is off" in r.message for r in caplog.records) == 1


def test_one_bad_snapshot_does_not_switch_recording_off_for_good(tmp_path):
    """The opposite of the rule above: a snapshot this code could not read is
    not evidence that the *file* is broken, and the next one may be fine."""
    db = tmp_path / "kona.db"
    rec = Recorder(str(db))
    assert rec.record(object()) is False
    assert rec.record(snapshot(hourly=hourly(HourBucket(steps=7)))) is True
    assert rows(db, "SELECT steps FROM hour") == [(7.0,)]


# -- the schema itself ----------------------------------------------------


def test_migrate_is_safe_to_run_repeatedly(tmp_path):
    conn = connect(str(tmp_path / "kona.db"))
    try:
        migrate(conn)
        migrate(conn)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        conn.close()


def test_a_database_from_a_newer_build_is_refused_rather_than_written_to(tmp_path):
    """An older build must not quietly drop columns it does not understand."""
    conn = connect(str(tmp_path / "kona.db"))
    try:
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
        with pytest.raises(RuntimeError, match="Refusing to write"):
            migrate(conn)
    finally:
        conn.close()


def test_the_recorder_reports_a_newer_database_as_off_rather_than_crashing(tmp_path):
    db = tmp_path / "kona.db"
    conn = connect(str(db))
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    assert Recorder(str(db)).record(snapshot()) is False


# -- the wiring into FiService --------------------------------------------


class Spy:
    def __init__(self):
        self.recorded = []

    def record(self, snap):
        self.recorded.append(snap)
        return True


class Boom:
    def record(self, snap):
        raise RuntimeError("the disk caught fire")


def service(spy, snapshots):
    """A FiService whose fetch returns canned snapshots, or raises."""
    calls = iter(snapshots)

    class Client:
        def close(self):
            pass

    svc = FiService("e", "p", 0.0, client_factory=Client, recorder=spy)
    svc._fetch = lambda: next(calls)  # noqa: SLF001 - the seam under test
    return svc


def test_a_successful_refresh_is_recorded(tmp_path):
    spy = Spy()
    svc = service(spy, [snapshot(hourly=hourly(HourBucket(steps=3)))])
    svc.snapshot(force=True)
    assert len(spy.recorded) == 1
    assert spy.recorded[0].hourly.hours[0].steps == 3


def test_a_failed_refresh_records_nothing(tmp_path):
    """The snapshot the page then shows is the *previous* reading wearing a
    failure flag. Recording it again would invent an observation."""
    from kona_tracker.fi.client import FiError

    spy = Spy()
    good = snapshot(hourly=hourly(HourBucket(steps=3)))

    def fetches():
        yield good
        raise FiError("Fi did not answer")

    svc = service(spy, fetches())
    svc.snapshot(force=True)
    svc.snapshot(force=True)
    assert len(spy.recorded) == 1


def test_a_recorder_that_explodes_does_not_break_the_page(tmp_path):
    """`Recorder.record` swallows its own failures, but FiService must not
    depend on that: anything duck-typed into this slot could raise."""
    svc = service(Boom(), [snapshot(hourly=hourly(HourBucket(steps=3)))])
    result = svc.snapshot(force=True)
    assert result.hourly.hours[0].steps == 3


def test_no_recorder_configured_is_the_normal_case(tmp_path):
    svc = service(None, [snapshot()])
    assert svc.snapshot(force=True) is not None
