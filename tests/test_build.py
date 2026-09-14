"""The build stamp, and the three ways it must refuse to lie.

A version indicator that guesses is worse than none: it turns "am I running
the new code?" from an open question into a confidently wrong answer.
"""

from __future__ import annotations

import datetime as dt
import subprocess

import pytest

from kona_tracker.web.build import Build, read_build


def test_a_directory_that_is_not_a_checkout_says_unknown(tmp_path):
    build = read_build(root=tmp_path)
    assert build.known is False
    assert build.label == "Build unknown"


def test_a_missing_git_binary_says_unknown_rather_than_raising(tmp_path, monkeypatch):
    """Windows without git on PATH is a real configuration, and it must cost
    a quiet "unknown" rather than a server that will not start."""

    def no_git(*a, **k):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)
    assert read_build(root=tmp_path).known is False


def test_a_hung_git_does_not_hang_the_page(tmp_path, monkeypatch):
    def too_slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="git", timeout=2.0)

    monkeypatch.setattr(subprocess, "run", too_slow)
    assert read_build(root=tmp_path).known is False


def test_the_label_leads_with_the_date_then_the_sha():
    """Date first because that is the question being asked -- is this from
    after the pull? -- and the SHA second because that is the part you paste
    into a message."""
    build = Build(
        known=True,
        sha="ec3398e",
        committed_at=dt.datetime(2026, 9, 14, 18, 40),
    )
    assert build.label == "14 Sep 18:40 · ec3398e"


def test_a_dirty_tree_says_so():
    """A local edit must not be able to present itself as a released commit."""
    build = Build(
        known=True,
        sha="ec3398e",
        committed_at=dt.datetime(2026, 9, 14, 18, 40),
        dirty=True,
    )
    assert build.label.endswith("· edited")


def test_a_commit_with_an_unreadable_date_still_reports_its_sha():
    """Losing the date is not a reason to lose the whole stamp."""
    build = Build(known=True, sha="ec3398e", committed_at=None)
    assert "ec3398e" in build.label
    assert "date unknown" in build.label


@pytest.mark.parametrize("dirty", [False, True])
def test_a_real_checkout_is_read_end_to_end(tmp_path, dirty):
    """Not mocked: an actual repository, so the argv and the parsing are
    exercised rather than described."""
    run = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "a.txt").write_text("one")
    subprocess.run([*run, "add", "."], cwd=tmp_path, check=True)
    subprocess.run([*run, "commit", "-qm", "first"], cwd=tmp_path, check=True)
    if dirty:
        (tmp_path / "a.txt").write_text("two")

    build = read_build(root=tmp_path)
    assert build.known is True
    assert len(build.sha) >= 7
    assert build.committed_at is not None
    assert build.dirty is dirty
    assert ("· edited" in build.label) is dirty


def test_the_stamp_reaches_the_settings_page():
    from fastapi.testclient import TestClient  # noqa: PLC0415 - test-only

    from kona_tracker.camera.source import FakeSource  # noqa: PLC0415
    from kona_tracker.web.app import create_app  # noqa: PLC0415
    from kona_tracker.web.settings import Settings  # noqa: PLC0415

    app = create_app(
        Settings(passcode="4242", secret="s" * 20),
        source_factory=lambda: FakeSource(fps=100),
    )
    client = TestClient(app)
    with client:
        client.post("/login", data={"passcode": "4242"})
        page = client.get("/settings").text
    assert 'class="build"' in page
