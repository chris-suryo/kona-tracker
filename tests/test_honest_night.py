"""Two readings that were being presented as something they were not.

Both were found in Chris's own data on 2026-09-13, and the numbers here are
his, not invented ones.

1. "Asleep last night" showed 9h 52m -- Fi's SLEEP total for the whole
   calendar day of 12 September -- above a caption reading "00:20 - 08:04",
   which is the overnight bout of 7h 44m. A figure and its own caption two
   hours apart. He chose the overnight bout.

2. "On charger" was printed in the present tense while she was 878 m from
   the house on a walk. Fi's field is `lastConnectionState`, and its date
   was hours old; we had thrown the date away.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from kona_tracker.fi.parse import CollarStatus, Overnight, RestWindow
from kona_tracker.fi.service import FiSnapshot
from kona_tracker.web.views import connection_label, last_night

#: Kona's zone, as Fi reports it.
NEW_YORK = ZoneInfo("America/New_York")
NOW = datetime(2026, 9, 13, 16, 27, tzinfo=UTC)

#: Straight from Chris's /activity.json capture, 2026-09-13 16:27 UTC.
DAY_SLEEP = 35513  # 9h 52m, all sleep in the calendar day of 12 Sep
NIGHT_SLEEP = 27832  # 7h 44m, the overnight bout the span describes
NIGHT_START = datetime(2026, 9, 12, 4, 20, 24, tzinfo=UTC)  # 00:20 EDT
NIGHT_END = datetime(2026, 9, 12, 12, 4, 17, tzinfo=UTC)  # 08:04 EDT


def _snapshot(*, with_night: bool = True) -> FiSnapshot:
    return FiSnapshot(
        fetched_at=NOW,
        window=RestWindow(
            start=datetime(2026, 9, 12, 4, 0, tzinfo=UTC),
            end=datetime(2026, 9, 13, 3, 59, 59, tzinfo=UTC),
            sleep=DAY_SLEEP,
            nap=16527,
        ),
        overnight=(
            Overnight(
                date=datetime(2026, 9, 11, 12, 0, tzinfo=UTC).date(),
                sleep_seconds=NIGHT_SLEEP,
                sleep_start=NIGHT_START,
                sleep_end=NIGHT_END,
                interruptions=(),
            )
            if with_night
            else None
        ),
    )


def test_last_night_is_the_night_not_the_calendar_day():
    night = last_night(_snapshot(), NEW_YORK)
    assert night is not None
    # 7h 44m, the bout the caption describes -- not 9h 52m, the day total.
    assert night["parts"] == [("7", "h"), ("44", "m")]
    assert night["raw"] == NIGHT_SLEEP
    assert night["source"] == "overnight"
    assert night["labels"]["span"] == "12:20 am – 8:04 am"
    assert night["labels"]["wake_label"] == "slept through"


def test_without_an_overnight_summary_the_day_total_says_so():
    """Fi does not always send the overnight summary. Falling back to the
    day total is fine; pairing it with a night's span is not, so the caller
    is told which number it got."""
    night = last_night(_snapshot(with_night=False), NEW_YORK)
    assert night is not None
    assert night["parts"] == [("9", "h"), ("52", "m")]
    assert night["source"] == "day"
    assert night["labels"] is None


def test_no_snapshot_is_none_rather_than_a_zero():
    assert last_night(None, NEW_YORK) is None


def test_a_current_connection_reading_speaks_in_the_present():
    """On the base, Fi stamps the connection state and the collar's last
    report with the same instant -- 16:26:20.201Z in Chris's capture."""
    same = datetime(2026, 9, 13, 16, 26, 20, tzinfo=UTC)
    label = connection_label(
        CollarStatus(on_base=True, connection_at=same, last_report=same), NEW_YORK
    )
    assert label == {"text": "Connected to base", "current": True}


def test_cellular_carries_the_signal_when_it_is_current():
    now = datetime(2026, 9, 13, 13, 48, tzinfo=UTC)
    label = connection_label(
        CollarStatus(on_base=False, signal_percent=64, connection_at=now, last_report=now),
        NEW_YORK,
    )
    assert label == {"text": "Cellular 64%", "current": True}


def test_a_stale_reading_is_a_memory_and_says_when():
    """The bug, in one test. On the walk the collar was reporting at 13:48
    while the last connection Fi recorded was hours earlier, on the base."""
    last_report = datetime(2026, 9, 13, 13, 48, tzinfo=UTC)
    label = connection_label(
        CollarStatus(
            on_base=True,
            connection_at=last_report - timedelta(hours=5),
            last_report=last_report,
        ),
        NEW_YORK,
    )
    assert label["current"] is False
    assert label["text"] == "Last connected to the base · 4:48 am"
    # Never the bare present tense that started this.
    assert label["text"] != "On charger"


def test_a_reading_a_few_seconds_behind_is_still_current():
    """Timestamps from two subsystems rarely match to the second; a minute
    of slack keeps a fresh reading from being demoted to a memory."""
    last_report = datetime(2026, 9, 13, 13, 48, tzinfo=UTC)
    label = connection_label(
        CollarStatus(
            on_base=False,
            signal_percent=29,
            connection_at=last_report - timedelta(seconds=30),
            last_report=last_report,
        ),
        NEW_YORK,
    )
    assert label == {"text": "Cellular 29%", "current": True}


def test_no_connection_state_shows_nothing_rather_than_guessing():
    assert connection_label(CollarStatus(), NEW_YORK) is None
    assert connection_label(None, NEW_YORK) is None


def test_a_reading_with_no_date_is_taken_at_face_value():
    """Older snapshots, and any response where Fi omits the date, keep the
    behaviour they had: state it plainly rather than invent a doubt."""
    label = connection_label(CollarStatus(on_base=True), NEW_YORK)
    assert label == {"text": "Connected to base", "current": True}
