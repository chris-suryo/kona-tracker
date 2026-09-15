"""`python -m kona_tracker` — the same CLI, without the console-script shim.

**Why this exists.** `uv run kona serve` spawns `.venv\\Scripts\\kona.exe`, a
small generated launcher. On 2026-09-15 Chris's PC refused to run it:

    error: Failed to spawn: `pytest`
      Caused by: An Application Control policy has blocked this file.
      (os error 4551)

Windows Application Control blocks unsigned executables, and every console
script in a virtualenv is exactly that -- a freshly written, unsigned .exe.
`pytest` hit it first; `kona` is the same shape and would have hit it next,
which matters more, because `kona serve` is the command that actually runs
this app on the one machine it runs on.

`python -m` imports the module instead of spawning a launcher, so there is no
new executable for the policy to judge. That makes this the reliable way in on
a locked-down Windows box, and it costs nothing anywhere else.

The console script stays. It is nicer to type and it works on machines without
such a policy; this is the door that is always open.
"""

from __future__ import annotations

from kona_tracker.cli import main

if __name__ == "__main__":
    main()
