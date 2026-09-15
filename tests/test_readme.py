"""The README is the front door, and a front door with a broken link on it
says nobody has been through in a while.

Every path it names must exist, every screenshot it shows must be in the
tree, and every page in its Pages table must be a route the app actually
serves -- checked against `create_app()`, not against a list, so the table
cannot describe a page that was renamed or dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.responses import HTMLResponse
from starlette.routing import Route

from kona_tracker.camera.source import FakeSource
from kona_tracker.web.app import create_app
from kona_tracker.web.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def backticked_paths(prefixes: tuple[str, ...]) -> list[str]:
    """`docs/x.md`, `src/kona_tracker/...`, `tests/...`, `scripts/...`: the
    repository paths the README names in code spans."""
    found = re.findall(r"`([^`\s]+)`", README)
    return sorted({p.rstrip("/") for p in found if p.startswith(prefixes)})


def test_every_repository_path_the_readme_names_exists():
    paths = backticked_paths(("docs/", "src/", "tests/", "scripts/", ".claude", ".dos/"))
    assert paths, "the README names no repository paths at all?"
    missing = [p for p in paths if not (ROOT / p).exists()]
    assert not missing, f"named in README.md but not in the tree: {missing}"


def test_every_screenshot_the_readme_shows_exists():
    shown = [p for p in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", README) if not p.startswith("http")]
    assert len(shown) >= 4, "the screenshot strip is gone"
    missing = [p for p in shown if not (ROOT / p).is_file()]
    assert not missing, missing


def routes():
    app = create_app(
        Settings(
            passcode="4242",
            secret="s" * 20,
            robot_snapshot_url="http://192.0.2.3:8080/?action=snapshot",
            robot_control_url="http://192.0.2.3:9031",
            robot_token="token-" * 4,
            robot_name="TurboPi",
        ),
        source_factory=lambda: FakeSource(fps=100),
        robot_source_factory=lambda: FakeSource(fps=100),
    )
    try:
        yield from flatten(app.routes)
    finally:
        app.state.hub.stop()
        app.state.robot_hub.stop()
        app.state.robot.close()


def flatten(items):
    for route in items:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from flatten(included.routes)
        elif isinstance(route, Route):
            yield route


def html_page(route: Route) -> bool:
    """FastAPI wraps an unset response_class in a DefaultPlaceholder."""
    cls = getattr(route, "response_class", None)
    cls = getattr(cls, "value", cls)
    return cls is HTMLResponse


def pages_table() -> list[str]:
    """The paths in the Pages table: everything backticked that starts with
    a slash, between the Pages heading and the next heading."""
    section = README.split("## Pages", 1)[1].split("\n## ", 1)[0]
    return sorted({p for p in re.findall(r"`(/[^`\s,]*)`", section)})


@pytest.mark.parametrize("path", pages_table())
def test_every_page_in_the_table_is_a_route_the_app_serves(path):
    # The table writes `/walks/<id>`; the route is `/walks/{walk_id}`.
    candidate = re.sub(r"<[^>]+>", "x", path)
    assert any(r.path == path or r.path_regex.match(candidate) for r in routes()), (
        f"{path} is in the README's Pages table but the app has no such route"
    )


def test_the_pages_table_is_not_missing_a_page_a_person_would_open():
    """Every HTML page the app serves should be in the table, so a route
    added without a line here fails. JSON, images and the control endpoints
    are named in prose or are not pages."""
    pages = [r for r in routes() if html_page(r) and r.path != "/login"]  # the gate, not a page
    listed = [re.sub(r"<[^>]+>", "x", q) for q in pages_table()]
    unlisted = sorted(r.path for r in pages if not any(r.path_regex.match(q) for q in listed))
    assert not unlisted, f"pages the README does not mention: {unlisted}"


def test_the_license_section_names_every_licence_in_the_tree():
    """Two dependencies are vendored, each under its own licence. A reader who
    forks this needs all three named, and the section goes stale the moment a
    third thing is vendored without being added."""
    section = README.split("## License", 1)[1]
    assert "MIT" in section and "`LICENSE`" in section
    for path, name in (
        ("src/kona_tracker/web/static/leaflet/", "BSD-2"),
        ("src/kona_tracker/web/static/fonts/", "OFL"),
    ):
        assert path in section, f"{path} is vendored but not named in the licence section"
        assert name in section, f"{path} is named without its licence"
        assert (ROOT / path).is_dir()


def test_the_readme_declares_the_same_project_as_the_package_metadata():
    """The pyproject description said "camera later" for a month after the
    camera shipped. Nobody reads it, which is exactly why it drifts."""
    import tomllib  # noqa: PLC0415 - test-only

    meta = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert meta["description"], "pyproject needs a description; it is what GitHub shows"
    assert "later" not in meta["description"], (
        "a description promising a future feature has drifted"
    )
    assert meta["urls"]["Repository"].endswith("/kona-tracker")
    assert meta["readme"] == "README.md"
