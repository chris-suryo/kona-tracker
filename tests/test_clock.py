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

    It reads string literals only, docstrings excluded: a directive can only
    reach strftime inside a string, and the docstrings are where the ban is
    explained by name. The first version of this test stripped *every*
    string token and then searched what was left -- so it could never have
    found a real `strftime("%-I")`, and passed for two weeks while guarding
    nothing. Found when the views module became a package and the guard was
    widened to every file in it: injecting `%-I` did not make it fail.
    """
    import ast  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    import kona_tracker.web.views as package  # noqa: PLC0415

    # Every module of the package, not `package.__file__`: that is the
    # __init__, which only re-exports and would pass while checking nothing.
    sources = sorted(Path(package.__file__).parent.glob("*.py"))
    assert len(sources) > 1, "the views package has no modules to scan"
    for source in sources:
        tree = ast.parse(source.read_text())
        docstrings = {
            id(node.body[0].value)
            for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and node.body
            and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)
        }
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ]
        for bad in ("%-I", "%-d", "%-m", "%-H", "%-M", "%-S", "%-j", "%-y"):
            hits = [text for text in literals if bad in text]
            assert not hits, f"{bad} in {source.name} is a glibc extension; raises on Windows"


def test_the_app_no_longer_writes_a_24_hour_clock_anywhere_a_person_looks():
    """A single 24-hour survivor is worse than none at all: it reads as a bug
    rather than as a choice."""
    from pathlib import Path  # noqa: PLC0415

    web = Path(__file__).resolve().parent.parent / "src" / "kona_tracker" / "web"
    offenders = []
    for path in [*web.rglob("*.py"), *(web / "templates").glob("*.html")]:
        if path.name == "build.py":
            continue  # the build stamp is for developers, not for the page
        if "%H:%M" in path.read_text():
            offenders.append(path.name)
    assert not offenders, f"24-hour clock still rendered in: {offenders}"
