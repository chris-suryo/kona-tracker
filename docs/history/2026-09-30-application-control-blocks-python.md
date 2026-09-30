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

## Why the interpreter was unsigned

`uv`'s default `python-preference` is `managed`: it prefers a uv-managed
CPython and, with downloads enabled, will fetch one rather than use the system
Python. uv-managed CPython comes from `python-build-standalone`, which is **not
signed by the Python Software Foundation**. Creating a venv copies that
interpreter into `.venv\Scripts\`, and Application Control refuses unsigned
executables.

Two details corroborate it. `py --list` showed only 3.14.6 while the venv was
running something else — uv-managed installs are not registered with the `py`
launcher, so an interpreter invisible to `py` is exactly what you would expect.
And the 2026-09-15 incident fits the same shape one layer up: uv's console-script
launchers are generated per-project and signed by nobody.

The trigger was a `git pull` + `uv sync` + `uv run kona serve` sequence run that
morning, against `PROJECT.md`'s standing `--no-sync` note. That sync is what
wrote a fresh copy of the unsigned interpreter.

**Still unexplained, and recorded as such:** the app came *up* after that sync
and only failed later, after an unrelated camera reset. An unsigned interpreter
should have been refused on the first launch. The likeliest account is Smart App
Control sitting in evaluation mode and flipping to enforcement in between, which
is why the diagnosis below reads `VerifiedAndReputablePolicyState` rather than
assuming. Nobody has confirmed it.

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

## The fix

Rebuild the venv on the signed python.org interpreter, and stop uv choosing its
own. Keep the broken venv rather than deleting it; it is the only evidence.

```powershell
$real = & py -V:3.14 -c "import sys; print(sys.executable)"
Rename-Item .venv .venv-blocked
$env:UV_PYTHON_DOWNLOADS = "never"
uv venv --python $real --no-managed-python
Get-AuthenticodeSignature .venv\Scripts\python.exe | Format-List Status, Path
```

**That signature check is the load-bearing step.** Authenticode signatures are
embedded in the PE and survive a byte-for-byte copy, so a venv built on a signed
base should itself be signed. If `Status` is not `Valid`, uv wrote its own
launcher instead of copying the interpreter — fall back to the stdlib, which
copies:

```powershell
Remove-Item -Recurse -Force .venv
& $real -m venv .venv
Get-AuthenticodeSignature .venv\Scripts\python.exe | Format-List Status
```

Then install, and run everything as a module:

```powershell
uv sync --python .venv\Scripts\python.exe --no-managed-python
# if uv sync is refused:  .venv\Scripts\python.exe -m pip install -e .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m kona_tracker serve
```

Make it permanent for every project on that machine, in `%APPDATA%\uv\uv.toml`:

```toml
python-preference = "only-system"
python-downloads = "never"
```

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
