"""Which build is this, said on screen.

Nothing in the app named the running version, so the only way to tell whether
a `git pull` had taken was to look for a behaviour change -- which fails
exactly when the change is invisible. On 2026-09-14 a day's work landed that
touched one template and a store nothing reads from yet, and the honest
answer to "am I on the latest?" was a five-minute investigation.

So: read it once at startup, show it quietly at the foot of Settings.

Three rules, because a build stamp that lies is worse than no build stamp:

- **Never guess.** No git, no `.git`, a stripped copy -- all report `unknown`
  rather than inventing a plausible version.
- **Say when the tree is dirty.** A local edit must not be able to present
  itself as a released commit.
- **Date first.** "14 Sep 18:40" answers the question at a glance; a SHA
  answers it only if you have another SHA to compare against.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: Anything slower than this and it is not worth blocking startup for.
TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class Build:
    """What is running. `known` is False when we could not find out."""

    known: bool
    sha: str = ""
    committed_at: datetime | None = None
    dirty: bool = False

    @property
    def label(self) -> str:
        """One line, for the foot of a page.

        Date first because that is the question being asked -- "is this the
        code from after the pull?" -- and the SHA second because that is the
        one you can paste into a message.
        """
        if not self.known:
            return "Build unknown"
        if self.committed_at is None:
            when = "date unknown"
        else:
            # `.day` rather than a strftime directive. "%-d" is a glibc
            # extension -- it raises ValueError on Windows, where the no-pad
            # flag is "%#d" -- and this app's home is a Windows PC. Ubuntu CI
            # was green and Windows CI was not; without that matrix the
            # Settings page would simply have 500'd on the machine it runs on.
            stamp = self.committed_at
            when = f"{stamp.day} {stamp:%b} {stamp:%H:%M}"
        return f"{when} · {self.sha}{' · edited' if self.dirty else ''}"


def _git(root: Path, *args: str) -> str | None:
    """One git command, or None for every way it can fail to answer.

    A missing binary, a directory that is not a checkout, a hung filesystem
    and a non-zero exit all mean the same thing here: we do not know.
    """
    try:
        done = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
            ["git", *args],  # noqa: S607 - PATH lookup is the point on Windows
            cwd=root,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def read_build(root: Path | None = None) -> Build:
    """Ask git what is checked out. Called once, at startup."""
    # Two parents up from this file is the repo root in a normal checkout;
    # in an installed copy it is site-packages, where git will simply say no.
    here = root or Path(__file__).resolve().parent.parent.parent.parent
    sha = _git(here, "rev-parse", "--short", "HEAD")
    if not sha:
        return Build(known=False)
    when = _git(here, "log", "-1", "--format=%cI")
    committed_at = None
    if when:
        try:
            committed_at = datetime.fromisoformat(when)
        except ValueError:
            committed_at = None
    # `--porcelain` prints one line per changed path and nothing at all for a
    # clean tree, so emptiness is the signal. A failure here is treated as
    # clean rather than dirty: we already know the commit, and claiming an
    # edit we did not observe would be its own small lie.
    status = _git(here, "status", "--porcelain")
    return Build(known=True, sha=sha, committed_at=committed_at, dirty=bool(status))
