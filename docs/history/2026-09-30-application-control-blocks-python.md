# Application Control blocked python.exe, and 3.14 turned out to be fine

2026-09-30. The app would not start on the PC that serves it. This is the third
and largest escalation of one problem, so it is written down once, properly.

```
> .venv\Scripts\python.exe --version
Program 'python.exe' failed to run: An Application Control policy has
blocked this file
```

## The three escalations

| Date | Refused | Workaround at the time |
|---|---|---|
| 2026-09-12 | `uv sync` | `uv run --no-sync`, or `uv sync --no-build-isolation` |
| 2026-09-15 | `pytest.exe`, `kona.exe` | `python -m kona_tracker` (`src/kona_tracker/__main__.py`) |
| 2026-09-30 | `.venv\Scripts\python.exe` | none — the escape hatch was the interpreter |

Each workaround assumed the next layer down would keep working. The third one
removed that assumption, which is why the fix below is about *which binary
exists* rather than about which command to type.

## Why the interpreter was unsigned — confirmed

`uv`'s default `python-preference` is `managed`: it prefers a uv-managed
CPython and, with downloads enabled, will fetch one rather than use the system
Python. uv-managed CPython comes from `python-build-standalone`, which is **not
signed by the Python Software Foundation**. Creating a venv copies that
interpreter into `.venv\Scripts\`, and Application Control refuses unsigned
executables.

This started as a hypothesis and the PC confirmed every part of it:

| Check | Result on the PC |
|---|---|
| old `.venv\pyvenv.cfg`, `home =` | `%APPDATA%\uv\python\cpython-3.14-windows-x86_64-none`, written by uv 0.11.26 — **uv-managed** |
| old `.venv\Scripts\python.exe` | `NotSigned` |
| python.org `pythoncore-3.14-64\python.exe` | `Valid`, CN=Python Software Foundation |
| CodeIntegrity log | events 3033 and 3077: the venv's `python.exe` "did not meet the Enterprise signing level requirements", policy `{0283ac0f-fff1-49ae-ada1-8a933130cad6}` |
| `VerifiedAndReputablePolicyState` | `1` — Smart App Control, enforcing |
| rebuilt venv (`& $real -m venv .venv`), `python.exe` | `Valid` |

Two details had corroborated it before the evidence came in. `py --list` showed only 3.14.6 while the venv was
running something else — uv-managed installs are not registered with the `py`
launcher, so an interpreter invisible to `py` is exactly what you would expect.
And the 2026-09-15 incident fits the same shape one layer up: uv's console-script
launchers are generated per-project and signed by nobody.

The trigger was a `git pull` + `uv sync` + `uv run kona serve` sequence run that
morning, against `PROJECT.md`'s standing `--no-sync` note. That sync is what
wrote a fresh copy of the unsigned interpreter.

**Not fully explained, and recorded as such:** the app came *up* after that
sync and only failed later. An unsigned interpreter should have been refused on
its first launch. The process list narrows it without closing it: processes of
another project, running on the same uv-managed 3.14 and started 2026-09-27,
were still alive on 09-30 while the same kind of file was being refused. That
fits Smart App Control switching itself from evaluation mode to On in between —
evaluation mode does that without asking, and a registry value of `1` only
says what it is *now*. It is also consistent with the policy's name: "Verified
and Reputable" admits an unsigned file on cloud reputation, judged file by
file, which is why some unsigned programs on the machine still start. Neither
is proven. The practical upshot is the same either way: only a signature is
reliable, so only a signed interpreter was worth building on.

**Anything else on that machine whose venv uv built will hit the same wall** the
next time it starts, and the same rebuild applies.

## Diagnosis — read-only, run this first

```powershell
Get-Content .venv\pyvenv.cfg                      # home = names the base interpreter
Get-AuthenticodeSignature .venv\Scripts\python.exe | Format-List Status, Path
$real = & py -V:3.14 -c "import sys; print(sys.executable)"
Get-AuthenticodeSignature $real | Format-List Status, SignerCertificate

# What the policy actually named. This is the authoritative answer.
Get-WinEvent -LogName 'Microsoft-Windows-CodeIntegrity/Operational' -MaxEvents 40 |
  Where-Object { $_.Message -match 'python|kona|pytest' } |
  Select-Object TimeCreated, Id, Message | Format-List

# Smart App Control (one-way) or a managed App Control policy (editable)?
# 0 = off, 1 = enforced, 2 = evaluation
Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\CI\Policy' `
  -Name VerifiedAndReputablePolicyState -ErrorAction SilentlyContinue
```

The distinction in that last command decides whether a policy exception is even
available. Smart App Control has no user-configurable exclusions and cannot be
re-enabled once turned off — it is one-way on Windows 11 — so **do not turn it
off to get past this.**

## The fix — the sequence that worked

Rebuild the venv on the signed python.org interpreter with Python's own `venv`,
and stop uv choosing its own. Run it from the repo: an Administrator
PowerShell opens in `C:\WINDOWS\system32`, and that cost two rounds.

```powershell
cd $HOME\kona-tracker
$real = & py -V:3.14 -c "import sys; print(sys.executable)"
Get-Content .venv\pyvenv.cfg                 # capture the evidence first
Remove-Item -Recurse -Force .venv
& $real -m venv .venv
Get-AuthenticodeSignature .venv\Scripts\python.exe | Format-List Status   # Valid
```

**That signature check is the load-bearing step.** The stdlib's `venv` puts the
signed python.org launcher in `.venv\Scripts\`, so the result is `Valid`.
`uv venv --python $real` was the first plan and was never seen to finish here,
so it is not the recipe; if you try it, run the same check.

What went wrong on the way, so it does not again:

- **The old venv was locked.** `Rename-Item` and uv both failed with "in use".
  Nothing kona-related showed in the process list afterwards, so the holder was
  probably a window or editor since closed. `Get-Process python | Format-Table
  Id, StartTime, Path -AutoSize` and Resource Monitor's Associated Handles are
  the ways to find it.
- **uv's "replace it?" prompt, answered yes on a locked venv, half-deleted it**
  before failing. Capture `pyvenv.cfg` and the signature first; after that the
  folder itself is not evidence worth keeping.

Make the guard permanent for every project on that machine, in
`%APPDATA%\uv\uv.toml`, before installing anything:

```toml
python-preference = "only-system"
python-downloads = "never"
```

Then install, and run everything as a module:

```powershell
uv sync --no-managed-python      # reused the new venv; installed 61 packages, no builds
.venv\Scripts\python.exe -m kona_tracker camera-test
.venv\Scripts\python.exe -m kona_tracker serve
```

If `uv sync` is ever refused, `.venv\Scripts\python.exe -m pip install -e .`
does the same job — but it resolves from PyPI rather than `uv.lock`, so treat
it as a way back up, not a routine.

**Why machine-level and not `[tool.uv]` in this repo:** CI installs Python
through `astral-sh/setup-uv`, which relies on uv-managed interpreters.
`only-system` committed to the repo would apply there too and likely break all
six cells, for no benefit. The policy is a property of one machine, so the
setting lives on that machine and the repo only records it.

**If a *signed* copy is still refused**, the mechanism is not signature-based (a
path or hash rule, or reputation on a user-writable directory) and the answer is
to never launch a copy — run the signed interpreter in place:

```powershell
& $real -m pip install --user -e .
& $real -m kona_tracker camera-test
```

That costs environment isolation and puts this project's dependencies in the
user site. Acceptable to get the app back up, not the new normal.

## Python 3.14 was the forced choice, and it is fine

The machine's only signed interpreter is 3.14.6, and `requires-python` is
`>=3.11` with CI covering 3.11 and 3.12 — so the version the app would now run
on was the one version nobody tested. Both halves of that were checked before
anything on the PC was touched.

**Install:** all 63 packages in `uv.lock` have a wheel installable on
`cp314`/`win_amd64`, checked by exact PEP 425 tag matching. Nothing builds from
source, so no compiler is needed. The one that looked fatal does not bite:

| Package | Wheel | Why it works |
|---|---|---|
| `opencv-python-headless` 5.0.0.93 | `cp37-abi3-win_amd64` | stable ABI, valid on any CPython >= 3.7 |
| `pycryptodome` 3.23.0 | `cp37-abi3-win_amd64` | stable ABI |
| `cryptography` 50.0.1 | `cp311-abi3-win_amd64` | stable ABI |
| `numpy`, `pydantic-core`, `httptools`, `watchfiles`, `websockets`, `PyYAML`, `aiohttp`, `yarl`, `multidict`, `frozenlist`, `propcache`, `cffi` | `cp314-cp314-win_amd64` | native builds published |
| `uvloop` 0.22.1 | none, any version | gated `sys_platform != 'win32'` in the lock — never installed on Windows, and already true on 3.12 |

A `uv sync --python 3.14.6 --python-platform windows --dry-run` resolves 61
packages with no build step and no `uvloop`.

**Runtime:** the suite passes on 3.14.6 — 629 tests, ruff clean.

### The trap worth writing down: 3.14.0rc2 fails, and it is not our bug

The first attempt used 3.14.0rc2, because that was the newest build the pinned
`uv` knew about. Nineteen test files failed at *collection*:

```
TypeError: _eval_type() got an unexpected keyword argument 'prefer_fwd_module'
```

pydantic 2.13.5 declares support for 3.14 and, for `sys.version_info >= (3, 14)`,
calls `typing._eval_type(..., prefer_fwd_module=True)`. CPython renamed that
parameter between rc2 and final:

| Build | `typing._eval_type` keyword |
|---|---|
| 3.14.0rc2 | `parent_fwdref` |
| 3.14.6 | `prefer_fwd_module` |

So the failure is an rc-versus-final signature difference, not a 3.14
incompatibility — and testing on the rc would have produced exactly the wrong
conclusion. Getting the real 3.14.6 needed uv's newer download manifest, since
`UV_PYTHON_DOWNLOADS_JSON_URL` rejects a remote URL:

```bash
curl -o dlmeta.json https://raw.githubusercontent.com/astral-sh/uv/main/crates/uv-python/download-metadata.json
UV_PYTHON_DOWNLOADS_JSON_URL=./dlmeta.json uv python install 3.14.6
```

**The lesson: pin the patch version when testing a new Python line.** `3.14` is
not a version, it is a moving target that included a signature change.

CI now runs `"3.14"` alongside 3.11 and 3.12 on both platforms — six cells — so
the version the PC serves from is no longer the untested one.

## The same day, after Python ran again

Two camera problems surfaced once the app could start. They are unrelated to
Application Control, and are recorded here only so the day reads in one place;
the instructions live in `docs/first-run.md` section 5.

- **`401 Unauthorized` on the picture.** The camera had been hard-reset after a
  Wi-Fi change, which wipes its camera account, so the password in `.env` no
  longer existed on the camera. Setting a fresh one in the Tapo app and copying
  it into `.env` fixed it: 10 fps at 1280x720.
- **The switches refused every login, then locked out for half an hour.** The
  docs had carried an untested 2026-09-13 theory: the camera account plus a
  cloud password. pytapo's secure login rejects any non-root account however
  right the password, so that could never work, and each attempt — every
  Camera-tab visit, plus pytapo's own internal retries — counted towards the
  camera's lockout ("Temporary Suspension: Try again in 982 seconds"). `admin`
  with the TP-Link account password worked first time once the lockout
  expired: the first time the switches were ever seen working. The app does
  not yet back off when the camera says to wait; that is a separate change.
