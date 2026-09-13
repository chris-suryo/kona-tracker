"""The stylesheet a phone already has must not be served against newer HTML.

On 2026-09-12 the /rest page rendered as black rectangles with a run-together
axis and a link floating outside its block, on a phone, while the same page
was correct everywhere else. Nothing was wrong with the page: Safari was
holding yesterday's /static/app.css and had no reason to ask for another,
because the URL had not changed. These tests hold the fix to the only
property that matters -- a changed file gets a changed URL.
"""

from __future__ import annotations

import hashlib

from kona_tracker.web.assets import asset_url, asset_versions


def test_a_changed_file_gets_a_changed_url_and_an_unchanged_one_does_not(tmp_path):
    (tmp_path / "app.css").write_text("body { color: red }", encoding="utf-8")
    (tmp_path / "app.js").write_text("// unchanged", encoding="utf-8")
    before = asset_versions(tmp_path)

    (tmp_path / "app.css").write_text("body { color: blue }", encoding="utf-8")
    after = asset_versions(tmp_path)

    assert after["app.css"] != before["app.css"], "an edited file must break the cache"
    assert after["app.js"] == before["app.js"], "an untouched file must stay cacheable"


def test_nested_files_keep_their_url_path(tmp_path):
    (tmp_path / "leaflet").mkdir()
    (tmp_path / "leaflet" / "leaflet.js").write_text("L", encoding="utf-8")
    versions = asset_versions(tmp_path)

    assert "leaflet/leaflet.js" in versions, "posix separators, because these are URLs"
    assert asset_url(versions, "leaflet/leaflet.js").startswith("/static/leaflet/leaflet.js?v=")


def test_the_version_is_the_content_hash_not_a_timestamp(tmp_path):
    """A mtime would change on every checkout and re-download every asset for
    no reason; the bytes are what the browser actually cares about."""
    (tmp_path / "app.css").write_text("body{}", encoding="utf-8")
    version = asset_versions(tmp_path)["app.css"]

    assert hashlib.sha256(b"body{}").hexdigest().startswith(version)


def test_an_unknown_name_falls_back_to_the_plain_path(tmp_path):
    """A template asking for a file that is not there is a broken page either
    way. A plain 404 in the network tab reads better than a versioned one."""
    assert asset_url(asset_versions(tmp_path), "nope.css") == "/static/nope.css"


def test_a_missing_static_directory_is_not_a_crash(tmp_path):
    assert asset_versions(tmp_path / "gone") == {}


def test_served_pages_carry_the_version_of_the_file_on_disk():
    """End to end: the URL in the HTML matches the bytes the server will
    serve for it, so the two can never drift apart."""
    from fastapi.testclient import TestClient

    from kona_tracker.camera.source import FakeSource
    from kona_tracker.web.app import HERE, create_app
    from kona_tracker.web.settings import Settings

    app = create_app(
        Settings(passcode="4242", secret="t"), source_factory=lambda: FakeSource(fps=100)
    )
    with TestClient(app) as client:
        page = client.get("/login").text
    app.state.hub.stop()
    on_disk = asset_versions(HERE / "static")

    assert f'href="/static/app.css?v={on_disk["app.css"]}"' in page
    assert f'src="/static/app.js?v={on_disk["app.js"]}"' in page
