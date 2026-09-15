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
