"""`python -m kona_tracker` must keep working, because on one machine it is
the only way in.

Windows Application Control refused to run `.venv\\Scripts\\pytest.exe` on
Chris's PC on 2026-09-15 (`os error 4551`). Every console script in a
virtualenv is a freshly generated, unsigned executable, so `kona.exe` is the
same shape -- and `kona serve` is the command that runs this app on the only
machine that serves it.

`python -m` imports rather than spawning a launcher, so the policy has no new
executable to judge. These tests exist so nobody removes the module entry as
dead code: it looks redundant next to the console script right up until the
console script is blocked.
"""

from __future__ import annotations

import subprocess
import sys


def test_the_module_entry_point_runs_the_same_cli():
    done = subprocess.run(
        [sys.executable, "-m", "kona_tracker", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert "kona-tracker tools" in done.stdout


def test_it_reaches_the_commands_and_not_just_the_help_banner():
    """A `__main__.py` that imported the wrong thing would still print a
    usage line. `serve` is the one that has to be reachable."""
    done = subprocess.run(
        [sys.executable, "-m", "kona_tracker", "serve", "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr


def test_the_console_script_is_still_declared():
    """The module entry is a second door, not a replacement: `kona serve` is
    nicer to type and works anywhere without such a policy."""
    from pathlib import Path  # noqa: PLC0415 - test-only

    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    assert 'kona = "kona_tracker.cli:app"' in pyproject


# -- and the docs for that machine must say so -----------------------------
#
# 2026-09-30: Application Control escalated from the console scripts to
# `.venv\Scripts\python.exe` itself. While fixing that, both runbooks for the
# Windows PC still told you to run the `kona.exe` that had been blocked two
# weeks earlier: PROJECT.md's command block, and the Scheduled Task in
# docs/remote-access.md. Nobody had noticed, because the person who hits it is
# the person who cannot run anything to find out.
#
# The Scheduled Task is the worse of the two. A blocked interactive command
# tells you it was blocked; a blocked task just quietly does not serve.


def _text(name: str) -> str:
    from pathlib import Path  # noqa: PLC0415 - test-only

    return (Path(__file__).resolve().parent.parent / name).read_text(encoding="utf-8")


def test_the_windows_pc_command_block_uses_the_module_form():
    """PROJECT.md is the runbook for the one machine that serves this app."""
    body = _text("PROJECT.md")
    marker = "**On the Windows PC, none of the `kona ...` forms above are usable.**"
    assert marker in body, "PROJECT.md must keep the Windows-PC caveat"
    windows_half = body.split(marker, 1)[1].split("\n## ", 1)[0]
    assert "-m kona_tracker serve" in windows_half
    assert "-m pytest -q" in windows_half
    # A bare `kona <cmd>` in this half would be the blocked launcher again.
    for blocked in ("uv run kona ", "uv run --no-sync kona ", "\nkona "):
        assert blocked not in windows_half, f"blocked console-script form: {blocked!r}"


def test_the_scheduled_task_launches_the_interpreter_not_the_console_script():
    """The unattended path: a refusal here is silent, so it is pinned."""
    body = _text("docs/remote-access.md")
    assert "New-ScheduledTaskAction" in body
    task = body.split("New-ScheduledTaskAction", 1)[1][:400]
    assert "-m kona_tracker serve" in task, "the task must reach the CLI as a module"
    assert '-Argument "run kona serve"' not in task, "that spawns the blocked kona.exe"


def test_the_incident_is_written_down_where_the_docs_point():
    """Three docs now cite this note by name; a dead link here is worse than
    no link, because it is read by someone whose app will not start."""
    from pathlib import Path  # noqa: PLC0415 - test-only

    note = "docs/history/2026-09-30-application-control-blocks-python.md"
    root = Path(__file__).resolve().parent.parent
    assert (root / note).is_file(), f"{note} is cited by the docs and must exist"
    for name in ("PROJECT.md", "docs/first-run.md", "docs/remote-access.md"):
        assert note.rsplit("/", 1)[1] in _text(name), f"{name} should cite the note"
