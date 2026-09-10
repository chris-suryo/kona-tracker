# Handoff — kona-tracker, 2026-09-10

Everything another assistant (or a future session) needs to pick this up.
Written at the end of the day the collar and the camera both went live.

---

## The one-paragraph version

A private, passcode-gated, iPhone-first web app for Chris and his sister to
check on Kona, a one-year-old Labrador. Two tabs: **Activity** (her Fi
collar) and **Camera** (live video from the house). Python: FastAPI + Jinja
templates + plain CSS, no build step, no JavaScript framework. It runs on a
machine at home because the camera stream originates there. Today it went
from "mocked everything" to real collar data and real video on a phone.

## Where it stands

| Piece | State |
|---|---|
| Passcode gate, signed-cookie sessions, lockout | Working |
| Camera over USB (Logitech C270), live on the phone | **Verified on real hardware** |
| Camera over RTSP (Tapo C120) | Code written, **never run against a real camera**. C120 arrives 2026-09-11 |
| Pan/tilt capability model | Working; correctly showed **no** pad for the fixed C270 |
| Activity: last night's sleep, naps today, steps, weekly steps | **Real Fi data** |
| Four honest page states: configured / partial / stale / failing | Working, tested |
| Her photo, collar battery, charge state, signal, escape flag | **Fetched and in `/activity.json`; deliberately not rendered yet** |
| `kona probe` — Fi API discovery, redacted | Four rounds run against the real API |
| Design pass | In flight in a separate session. `web/templates/` and `web/static/app.css` were left untouched all day so it cannot collide |

155 tests. `main` and `claude/nice-bohr-6tnfn0` are both at the same commit.
CI is a ubuntu + windows matrix and is green.

## How to run it

Windows PowerShell, from the repo root. `uv` runs Python; you never invoke
Python directly.

```powershell
git clone https://github.com/chris-suryo/kona-tracker.git
cd kona-tracker
uv sync
uv run pytest -q                       # expect 155 passed
Copy-Item .env.example .env            # then fill it in, see below
uv run kona serve                      # http://localhost:8000
uv run kona serve --fake-camera        # no camera needed, test pattern
uv run kona probe --out probe-out\NAME # Fi API discovery
uv run ruff check . ; uv run ruff format .
```

`.env` needs four values. `FI_EMAIL`/`FI_PASSWORD` are Chris's own Fi app
login. `KONA_PASSCODE` is what he and his sister type into this app — a
different thing, and confusing the two lines has already cost an hour.
`KONA_SECRET` is any long random string. `KONA_CAMERA_SOURCE=usb` with
`KONA_CAMERA_INDEX=0` for the webcam, or `fake`.

`.env` and `probe-out/` are gitignored. **Never commit either.**

Two Windows gotchas, both hit today and both in `docs/first-run.md`:
pytest's temp directory is blocked (use the `PYTEST_ADDOPTS` fix), and a USB
camera belongs to one program at a time — Windows Settings > Camera being
open is enough to make the app show NO SIGNAL.

## The thing that makes this project unusual

**Fi has an API but does not document it.** `api.tryfi.com` is what their own
iPhone app talks to. There is no manual, no field list, no support. So this
repo contains a *client* — the other half of a conversation whose language
nobody published — plus `kona probe`, which is how the language gets learned:
ask for a field, read the validation error, and Fi's server says *"did you
mean X?"*. Introspection is disabled, so the errors are the documentation.

Two consequences that govern everything:

1. **Measured, not assumed.** With no docs, a guess that looks right is
   indistinguishable from a fact until it fails in front of the user. Every
   claim in `docs/device-capabilities.md` is either measured against Kona's
   collar or explicitly marked unverified.
2. **The probe is permanent.** Fi can change the API without telling anyone,
   and already has — the sleep query broke on first contact. The probe is the
   drift detector.

## What is confirmed, and what is confirmed absent

Read `docs/device-capabilities.md` before designing anything. Short version.

**Real:** sleep and nap durations in **seconds** (daily/weekly/monthly);
steps and step goal; distance in **metres, walks only**; her photo; breed,
weight, birthday; battery percent; on-charger vs cellular-with-signal;
resting vs walking; a GPS track at 1 Hz with 4-7 m accuracy on a walk; an
**escape flag** (`mode` went `POST_ESCAPE_NOTIFICATION` when she left the
safe zone).

**Confirmed absent — do not design for these:** no sleep quality or score at
any level, no barking/scratching/licking/eating/drinking counts, no heart
rate, no calories or active minutes, no geofences. Fi offers a near-match
when one exists, so a rejection with no suggestion is evidence of absence.

**Two traps that produced wrong output before they were caught:**
- Fi's day is midnight-to-midnight *local*, and the newest daily rest window
  is **today, in progress**, with SLEEP=0 until tonight. "Last night" is the
  window before it. Reading the newest one showed 0 h under "Last night".
- `timeToEmptyS` swings from 4 days to 12 hours depending on whether GPS is
  running. It is a live power estimate. Never headline it; show percent.

Also: any collar data before 2026-09-10 belongs to an **earlier collar that
did not fit and sat in a drawer**. Fi attaches data to the pet, not the
device. Only today onward is Kona.

## The next tasks, in priority order

1. **Fold in the UI.** This is the ChatGPT-shaped task: it touches only
   `web/templates/*.html` and `web/static/app.css`, needs no hardware, and
   those files were deliberately left alone. The data it should render is
   already in the page context and in `/activity.json` — see
   `docs/design-brief.md`, whose paste-able block carries real sample values.
   Things worth surfacing that are fetched but unrendered: her photo (an
   `<img src="/avatar.jpg">` with the existing initial as fallback), battery
   percent, on-charger vs out-with-signal, resting vs walking, and the
   **escape state**, which is the one alert an owner actually cares about.
2. **Probe round 4.** `uv run kona probe --out probe-out\round4`. The
   allowlist fix means the required-argument messages will finally name the
   arguments for `overnightRestSummary` (Fi's own "last night", better than
   the current heuristic) and the three history feeds.
3. **The Tapo C120** when it arrives — `docs/first-run.md` step 4. Turn on
   **Third-Party Compatibility** in the Tapo app first or nothing connects.
   This is the first real RTSP test.
4. **Host it properly** — the spare laptop as a dedicated always-on machine,
   then a permanent URL. The Raspberry Pi is bought but unopened; add it
   only after the C120 is proven on a machine that already works.

## House rules for whoever picks this up

From `CLAUDE.md`, which is checked in and applies to every session:

- **Plan first, stop for approval** on anything non-trivial.
- **Never commit secrets.** No `.env` contents, tokens or passwords in code,
  commits or logs.
- **No new dependencies without asking.** Name the dependency and the why.
- **Never force-push**, never rewrite published history.
- **Touch only what the task requires.** No drive-by refactors.
- **Fail loud, not silent.** Surface uncertainty; never paper over a gap with
  confident-sounding output. If something cannot be verified, say so.
- Tests live beside the code they cover; a change to logic comes with a test.
- CI must stay green on both ubuntu and windows.

One more, learned twice today at real cost: **a test written against an
assumption only ever confirms the assumption.** A mock that answered any
query let a malformed GraphQL query ship; an allowlist test using an invented
error message hid the fact that every real message was being redacted. When
testing against an external API, use a shape that API actually sent.

## Where to look

- `src/kona_tracker/fi/` — client, GraphQL documents, parsers, snapshot cache
- `src/kona_tracker/camera/` — USB/RTSP/fake sources, capability model, hub
- `src/kona_tracker/web/` — FastAPI app, auth, settings, templates, CSS
- `src/kona_tracker/probe/` — probe orchestration, redaction, schema scan
- `docs/device-capabilities.md` — **the source of truth for what the hardware
  can do.** Read before designing any control.
- `docs/design-brief.md` — paste-able block for a design session
- `docs/first-run.md` — plain-language setup, and the troubleshooting that
  was earned the hard way
- `PROJECT.md` — status, stack, and the constraints that shape the design
