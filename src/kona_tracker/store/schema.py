"""The shape of a dog's day, in SQLite.

**Why this exists at all.** `pet_hourly()` takes no cursor: Fi will only tell
us about *today*, hour by hour, and at midnight her time that detail is gone
and cannot be fetched again. Daily rest survives about fourteen days in
`restSummaryFeed` and then goes too. Everything this app has ever shown has
been a live read of a window that keeps closing behind it.

**Why the schema looks like this and not like Fi's API.** The plan is to stop
relying on Fi hardware -- an open-source collar, or a home-made one. A store
shaped around `restSummaryFeed` and `pet_hourly` would make that migration a
rewrite, and would quietly encode one vendor's opinions (a day starts at 04:00;
"rest" splits into sleep and nap) as though they were facts about dogs. So the
tables describe what was true of the animal, and every row carries `source`,
because the day a second collar arrives is the day "steps" needs to say whose.

Nothing reads from this yet. It is a recorder, deliberately: the first job is
to stop losing data, and a store with no readers cannot break a page.

## What is NOT here, on purpose

**The raw payloads.** An earlier sketch had a second layer of gzipped,
de-duplicated API responses, so that fields we do not parse today could be
mined later. It is not in this pass because capturing them means threading a
tap through `FiClient`, which is the one piece of code that holds the account
password, and doubling the surface area of a change whose entire value is that
it cannot break anything. Everything `FiSnapshot` carries is recorded here;
what is lost is only what the parser already discards. Worth revisiting, but
not worth coupling to this.
"""

from __future__ import annotations

import sqlite3

#: Bumped when the statements below change in a way that needs new tables.
#: `user_version` is a SQLite header field, so reading it costs no query and
#: an unmigrated file identifies itself without a schema table of our own.
SCHEMA_VERSION = 1

#: Every statement is `IF NOT EXISTS`, so applying this to a current database
#: is a no-op rather than an error. Migration between versions, when there is
#: ever a version 2, goes in `migrate()` -- not here.
STATEMENTS = (
    # -- the perishable one ------------------------------------------------
    #
    # One row per hour of her local day. This is the table the whole module
    # exists for: it is the only record of it that will exist after midnight.
    #
    # `day` is her calendar day as Fi reckons it, stored as an ISO string so
    # it sorts and compares without a timezone library. `hour` is 0-23 from
    # that day's start. Any of the three measurements may be NULL, and NULL
    # means *we were not told*, never zero -- the difference between a dog
    # who did not move and an hour that had not happened yet.
    """
    CREATE TABLE IF NOT EXISTS hour (
        source      TEXT    NOT NULL,
        pet_id      TEXT    NOT NULL,
        day         TEXT    NOT NULL,
        hour        INTEGER NOT NULL,
        steps       REAL,
        sleep_s     REAL,
        nap_s       REAL,
        observed_at TEXT    NOT NULL,
        PRIMARY KEY (source, pet_id, day, hour)
    )
    """,
    # -- daily totals ------------------------------------------------------
    #
    # `complete` distinguishes a finished day from one still being lived, and
    # `partial_first_day` marks the day the collar was set up, whose totals
    # start mid-afternoon and must never be charted as a short night.
    """
    CREATE TABLE IF NOT EXISTS day (
        source            TEXT    NOT NULL,
        pet_id            TEXT    NOT NULL,
        day               TEXT    NOT NULL,
        steps             REAL,
        step_goal         REAL,
        distance          REAL,
        sleep_s           REAL,
        nap_s             REAL,
        complete          INTEGER,
        in_progress       INTEGER,
        partial_first_day INTEGER,
        observed_at       TEXT    NOT NULL,
        PRIMARY KEY (source, pet_id, day)
    )
    """,
    # -- walks, and their routes ------------------------------------------
    #
    # Fi's own id is the key: a walk is immutable once it has ended, so the
    # same walk seen on ten refreshes is one row, not ten.
    """
    CREATE TABLE IF NOT EXISTS walk (
        source      TEXT NOT NULL,
        walk_id     TEXT NOT NULL,
        pet_id      TEXT NOT NULL,
        kind        TEXT,
        started_at  TEXT,
        ended_at    TEXT,
        steps       REAL,
        distance_m  REAL,
        area_name   TEXT,
        observed_at TEXT NOT NULL,
        PRIMARY KEY (source, walk_id)
    )
    """,
    # `seq` rather than a timestamp, because a route's points are ordered but
    # not always stamped -- Fi sends the path for a finished walk as a bare
    # list of coordinates.
    """
    CREATE TABLE IF NOT EXISTS walk_point (
        source      TEXT    NOT NULL,
        walk_id     TEXT    NOT NULL,
        seq         INTEGER NOT NULL,
        latitude    REAL    NOT NULL,
        longitude   REAL    NOT NULL,
        recorded_at TEXT,
        accuracy_m  REAL,
        PRIMARY KEY (source, walk_id, seq)
    )
    """,
    # -- where she was -----------------------------------------------------
    #
    # The live trail, keyed on the collar's own timestamp so that re-reading
    # the same fix on the next refresh does not duplicate it. Positions with
    # no timestamp are dropped rather than invented: an unstamped fix cannot
    # be placed in a history, and a guessed time would be worse than no row.
    """
    CREATE TABLE IF NOT EXISTS position (
        source      TEXT NOT NULL,
        pet_id      TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        latitude    REAL NOT NULL,
        longitude   REAL NOT NULL,
        accuracy_m  REAL,
        area_name   TEXT,
        PRIMARY KEY (source, pet_id, recorded_at)
    )
    """,
    # -- the collar itself -------------------------------------------------
    #
    # Not about the dog, and kept anyway: battery curves and signal quality
    # are exactly what you want when judging whether some other collar would
    # do better. Keyed on Fi's `lastConnectionTime` so an unchanged reading
    # re-seen is one row.
    """
    CREATE TABLE IF NOT EXISTS device_state (
        source           TEXT NOT NULL,
        pet_id           TEXT NOT NULL,
        connection_at    TEXT NOT NULL,
        battery_percent  REAL,
        time_to_empty_s  REAL,
        signal_percent   REAL,
        on_base          INTEGER,
        activity         TEXT,
        mode             TEXT,
        escaped          INTEGER,
        lost             INTEGER,
        area_name        TEXT,
        observed_at      TEXT NOT NULL,
        PRIMARY KEY (source, pet_id, connection_at)
    )
    """,
    # -- last night as an interval ----------------------------------------
    #
    # `day` totals say how much she slept; this says between when and when,
    # and how often she got up. Keyed on the night's date.
    """
    CREATE TABLE IF NOT EXISTS overnight (
        source      TEXT NOT NULL,
        pet_id      TEXT NOT NULL,
        day         TEXT NOT NULL,
        sleep_s     REAL,
        sleep_start TEXT,
        sleep_end   TEXT,
        observed_at TEXT NOT NULL,
        PRIMARY KEY (source, pet_id, day)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS overnight_interruption (
        source   TEXT    NOT NULL,
        pet_id   TEXT    NOT NULL,
        day      TEXT    NOT NULL,
        seq      INTEGER NOT NULL,
        start_at TEXT    NOT NULL,
        end_at   TEXT    NOT NULL,
        PRIMARY KEY (source, pet_id, day, seq)
    )
    """,
    # Reading back "the last month of hours" is the first query anyone will
    # write, and the primary key already sorts that way; this covers the
    # other obvious one, "what did we learn and when".
    "CREATE INDEX IF NOT EXISTS hour_observed ON hour (observed_at)",
    "CREATE INDEX IF NOT EXISTS walk_started ON walk (started_at)",
)


def connect(path: str) -> sqlite3.Connection:
    """Open the database with the settings this recorder needs.

    WAL so that a reader -- a future page, or Chris with a SQLite browser
    open -- never blocks the writer and never sees a half-written refresh.
    `busy_timeout` because two processes *will* eventually run at once (a
    `kona serve` left open while another is started), and the loser should
    wait a moment rather than raise.
    """
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Bring a database up to `SCHEMA_VERSION`. Safe to call on every open.

    A file from a *newer* version is left alone and not written to: an older
    build must not quietly drop columns it does not know about. The caller
    finds out by the exception, which is the one case where this module is
    allowed to be loud.
    """
    found = conn.execute("PRAGMA user_version").fetchone()[0]
    if found > SCHEMA_VERSION:
        raise RuntimeError(
            f"This database is version {found}; this build understands "
            f"{SCHEMA_VERSION}. Refusing to write to it."
        )
    with conn:
        for statement in STATEMENTS:
            conn.execute(statement)
        # Not a parameter: PRAGMA does not take one, and the value is an
        # integer constant in this file rather than anything from outside.
        conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
