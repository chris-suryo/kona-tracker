"""Daily rest history, using the windows Kona's collar actually returned.

The fixture below is the real shape from `probe-out/round6/summary.md`,
2026-09-11: five daily windows, midnight-to-midnight in Kona's timezone
(04:00Z), newest first, with 2026-09-07 the day the collar was set up and
2026-09-11 still in progress. Durations are seconds.
"""

from datetime import UTC, date, datetime, timedelta

from kona_tracker.fi.parse import RestWindow, rest_history


def _w(day: int, sleep, nap) -> RestWindow:
    start = datetime(2026, 9, day, 4, 0, tzinfo=UTC)
    return RestWindow(start=start, end=start + timedelta(days=1), sleep=sleep, nap=nap)


#: Newest first, exactly as Fi returns them.
MEASURED = [
    _w(11, 0, 23356),  # today, in progress
    _w(10, 24760, 7373),
    _w(9, 8796, 6971),
    _w(8, 18406, 16545),
    _w(7, 0, 13576),  # collar set up this day
]
NOW = datetime(2026, 9, 11, 20, 57, tzinfo=UTC)
COLLAR_START = date(2026, 9, 7)


def test_history_comes_back_oldest_first_with_every_measured_day():
    days = rest_history(MEASURED, NOW, COLLAR_START)

    assert [d.window.start.date().day for d in days] == [7, 8, 9, 10, 11], (
        "oldest first, because a chart reads left to right"
    )
    assert len(days) == 5


def test_the_two_incomplete_days_are_excluded_from_averages_and_say_why():
    """They are excluded for different reasons and must not be collapsed."""
    days = {d.window.start.date().day: d for d in rest_history(MEASURED, NOW, COLLAR_START)}

    today = days[11]
    assert today.complete is False
    assert today.in_progress is True
    assert today.partial_first_day is False

    first = days[7]
    assert first.complete is False
    assert first.partial_first_day is True, (
        "the collar was set up partway through this day; Fi still reports a "
        "whole calendar window for it with no coverage figure"
    )
    assert first.in_progress is False

    complete = [d.window.start.date().day for d in days.values() if d.complete]
    assert complete == [8, 9, 10]


def test_a_days_total_is_sleep_plus_naps_and_unknown_is_not_zero():
    days = {d.window.start.date().day: d for d in rest_history(MEASURED, NOW, COLLAR_START)}

    assert days[10].total == 24760 + 7373
    assert days[11].total == 23356, "SLEEP=0 is measured; it counts"

    # Neither measured is not a zero-rest day, and summing None as 0 is
    # exactly how this project has been wrong before.
    nothing = rest_history([_w(9, None, None)], NOW, None)
    assert nothing[0].total is None
    only_naps = rest_history([_w(9, None, 600)], NOW, None)
    assert only_naps[0].total == 600


def test_days_before_the_collar_cutoff_are_dropped_not_marked():
    """Those belong to a replaced or unworn collar. Same rule the single
    window already follows in service.py."""
    older = [_w(5, 30000, 1000), _w(6, 29000, 900), *MEASURED]

    days = rest_history(older, NOW, COLLAR_START)
    assert [d.window.start.date().day for d in days] == [7, 8, 9, 10, 11]

    # With no cutoff configured, nothing is dropped -- the caller decides.
    assert len(rest_history(older, NOW, None)) == 7


def test_a_window_without_bounds_is_dropped_rather_than_placed_on_a_guess():
    unbounded = RestWindow(start=None, end=None, sleep=100, nap=100)
    assert rest_history([unbounded, *MEASURED], NOW, COLLAR_START) == rest_history(
        MEASURED, NOW, COLLAR_START
    )


def test_no_cutoff_means_no_day_is_marked_a_partial_first_day():
    days = rest_history(MEASURED, NOW, None)
    assert [d.partial_first_day for d in days] == [False] * 5
    assert [d.window.start.date().day for d in days if d.complete] == [7, 8, 9, 10]
