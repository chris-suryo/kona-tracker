"""How this app writes a time of day.

One place decides, so no other test has to. Three of them used to build their
expected string with `%H:%M` while actually testing timezone conversion, and
a format change broke all three for a reason that had nothing to do with what
they were checking.
"""

from __future__ import annotations

import datetime as dt

import pytest

from kona_tracker.web.views import _hhmm, _hour_range


def at(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(2026, 9, 15, hour, minute)


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (0, 5, "12:05 am"),  # midnight is twelve, not zero
        (9, 27, "9:27 am"),  # no leading zero -- "09:27 am" is not how it is written
        (11, 59, "11:59 am"),
        (12, 0, "12:00 pm"),  # noon is twelve pm, the other easy one to get wrong
        (13, 26, "1:26 pm"),
        (21, 27, "9:27 pm"),
        (23, 59, "11:59 pm"),
    ],
)
def test_the_clock_reads_the_way_her_people_read_one(hour, minute, expected):
    assert _hhmm(at(hour, minute)) == expected


def test_minutes_keep_their_leading_zero_even_though_hours_do_not():
    """9:05, not 9:5 -- and not 09:05 either."""
    assert _hhmm(at(9, 5)) == "9:05 am"


@pytest.mark.parametrize(
    ("hour", "expected"),
    [
        (0, "12–1 am"),
        (9, "9–10 am"),
        (11, "11 am–12 pm"),  # crosses noon, so both halves are named
        (12, "12–1 pm"),
        (23, "11 pm–12 am"),  # and midnight
    ],
)
def test_an_hour_bucket_names_its_range_without_repeating_the_suffix(hour, expected):
    assert _hour_range(at(hour)) == expected


def test_no_platform_specific_strftime_directives_in_the_clock():
    """`%-I` drops the leading zero on glibc and raises ValueError on Windows,
    which is the machine this app is served from. That mistake already broke
    the Settings page once (PR #49); this is the guard for the clock.

    Comments are tokenised away first, because this docstring names the very
    directive it bans.
    """
    import io  # noqa: PLC0415
    import tokenize  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    import kona_tracker.web.views as module  # noqa: PLC0415

    source = Path(module.__file__).read_text()
    code = "".join(
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type not in (tokenize.COMMENT, tokenize.STRING)
    )
    for bad in ("%-I", "%-d", "%-m", "%-H", "%-M", "%-S", "%-j", "%-y"):
        assert bad not in code, f"{bad} is a glibc extension and raises on Windows"


def test_the_app_no_longer_writes_a_24_hour_clock_anywhere_a_person_looks():
    """A single 24-hour survivor is worse than none at all: it reads as a bug
    rather than as a choice."""
    from pathlib import Path  # noqa: PLC0415

    web = Path(__file__).resolve().parent.parent / "src" / "kona_tracker" / "web"
    offenders = []
    for path in [*web.glob("*.py"), *(web / "templates").glob("*.html")]:
        if path.name == "build.py":
            continue  # the build stamp is for developers, not for the page
        if "%H:%M" in path.read_text():
            offenders.append(path.name)
    assert not offenders, f"24-hour clock still rendered in: {offenders}"
