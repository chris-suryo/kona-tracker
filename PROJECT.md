# kona-tracker

Private, passcode-gated, iPhone-first web app for Chris and their sister to
check on Kona (dog). Activity tab from her Fi collar (Whoop later); Camera tab
once the hardware exists.

---
kit: 3e06b156508b881bef26345c0bb7a63c90db4824 · stamped by dos new
---

## Status (2026-09-13, chapter 2)

**Start from `main`.** Every PR through #28 is merged; nothing is stacked or
waiting. Branch from `main`, open a PR, CI green, merge. ChatGPT's UI pass
(PR #7) was reconciled in as #14 and #7 closed.

`docs/production-punchlist.md` is the queue and carries the reasoning behind
every item; `docs/scaling-limits.md` is the standing list of ceilings;
`docs/chatgpt-handoff.md` is the brief for a visiting assistant.

- **Slice 1:** `kona probe` dumps every Fi API field, redacted. Eleven rounds
  run against Kona's collar; each round asks one unknown per query so the
  validation error names the next thing. `docs/slice-1-probe-plan.md`.
- **Slice 2 + 2b:** `kona serve` = passcode gate, live camera (USB or RTSP,
  reconnects, "NO SIGNAL" when stale). `docs/slice-2-camera-plan.md`,
  `docs/slice-2b-rtsp-plan.md`.
- **Camera is the Tapo C120 (2026-09-12).** RTSP `stream1` at 2560x1440,
  downscaled server-side to `KONA_CAMERA_WIDTH` after decode so the phone
  gets a sharp 1280-wide frame without the full bitrate. Latency: the reader
  drains the decoder's queue to the newest frame before every snapshot and
  opens FFmpeg with `nobuffer`/`low_delay`, which is what the 8-second lag
  Chris measured was made of. **The lag after that fix is not yet measured
  on his phone.** Pinch-to-zoom and double-tap on the picture (PR #27).
  Night vision, privacy mode and the status light are real switches on the
  Camera tab through pytapo (PR #28, the one new dependency, approved
  2026-09-13). `docs/device-capabilities.md`.
- **Slice 3 (Activity is real):** `fi/parse.py` holds the only parsers, shared
  by the probe and the page. `fi/service.py` caches one snapshot, refreshes on
  a background thread past `KONA_FI_REFRESH_SECONDS`, and never discards a good
  reading when a refresh fails. `/activity` and `/activity.json` render four
  honest states: not configured, failing, **partial** (fresh but a query
  failed), and stale (old data, refresh failed).
- **Slice 4 (first contact with the real API, 2026-09-10):** steps are live.
  Sleep was rejected -- `RestSummary.data` is abstract and `sleepAmounts` needs
  an inline fragment on `ConcreteRestSummaryData`. Fixed. See
  `docs/device-capabilities.md` §2 for what is confirmed present, confirmed
  **absent**, and untrustworthy.
- **History pages (2026-09-11 to 13):** `/rest` = today by hour (24 buckets
  from `restFeed(period: DAY)`) then one bar per day since the collar came
  online (`restSummaryFeed`); `/steps` = today by hour from `stepFeed`;
  last night's span and interruptions from `overnightRestSummary`; a walk
  log from `activityFeed` with the route drawn on `/walks/<id>`. The walk
  routes and the Fi hourly buckets' field names came from "Did you mean"
  hints across rounds 8-11 and **have not yet been seen rendering on
  Chris's phone**; a query that fails shows up as a labelled problem line on
  the page, never as a blank.
- **Refresh (PR #20):** static files are cache-busted by content hash, the
  Activity page re-fetches once a minute while visible, and the map keeps
  its tiles unless none ever loaded. Three clocks decide how old the
  position on screen is; `.env.example` explains them and why 120 is the
  better `KONA_FI_REFRESH_SECONDS` for watching a walk.
- **Motion:** `@view-transition { navigation: auto; }` gives animated
  cross-document navigation on Safari 18.2+ and Chrome 126+. All CSS, no
  build step, all inside `prefers-reduced-motion` guards.
  `docs/design-brief.md` explains why the app is HTML and not React.
- **Slice 5 (production pass, 2026-09-11):** her resting position on the map
  with honest tiers, a login lockout that survives a tunnel, Secure cookies
  by setting, a CSP with every script in a file, vendored Leaflet,
  pull-to-refresh that repaints without dropping the video, page zoom off by
  request (the camera picture is the one exception, by design), camera
  health readable from a phone, a rotating log, times in Kona's timezone,
  and an outbound heartbeat so a dead PC still raises an alarm.
- **Robot tab (2026-09-14):** the TurboPi is a second camera, read one
  JPEG per GET from its port 8080 through its own `CameraHub`, behind the
  same gate, on its own tab. `KONA_ROBOT_SNAPSHOT_URL` is the switch; blank
  means no tab. Driving is **gated** on the Pi-side watchdog service
  existing and answering `/health` (its contract is in
  `docs/device-capabilities.md` §1b); the app never talks to the robot's
  raw port 9030. Chris still owes `Test-NetConnection 10.0.0.3 -Port 8080`
  from the PC and a DHCP reservation for the robot.
- **Windows PC:** `uv sync` is blocked by Application Control (error 4551)
  on Chris's machine. `uv run --no-sync kona serve` runs what is already
  installed; a new dependency needs `uv sync --no-build-isolation`, which
  is untested there. The USB webcam (Logitech C270) is retired by the Tapo.
- **Hardware bought 2026-09-11:** one Raspberry Pi 5 8GB, a 52Pi case, a
  128 GB microSD, an RTC battery, a Hiwonder TurboPi kit (no Pi included).
  No power supply; an undervoltage check is the first thing to do. **Kona
  still runs on the Windows PC**, and should, until the Tapo is proven
  there. `KONA_KEEP_AWAKE=true` in `.env` is the whole of "leave it running".

**next:**

*Chris's checks, all on the real phone against the real collar and camera
(none has been done; every item below was built against fakes):*

0. Pull, install the new dependency, add `KONA_TAPO_PASSWORD` (the Tapo app
   login, not the camera account) and `KONA_FI_REFRESH_SECONDS=120` to
   `.env`, restart. `docs/first-run.md` "Updating later" has the commands.
1. **Camera lag** after the drain fix: wave at the camera, count. Under
   two seconds is the target on the LAN; report the number either way.
2. **The three switches** on the Camera tab: they only appear when the
   camera answered `GET /control/settings`. If the section is missing, the
   pytapo login failed; `/settings` shows the last problem. The likeliest
   cause is the password (cloud password vs camera account).
3. **`/rest` "Today by hour", `/steps`, and the walk log** on Activity. Any
   line starting "Hourly:" or "Walks:" is a field name Fi rejected; paste
   it back and it is a one-line fix.
4. **A walk while the page is open**: with refresh at 120 the position
   should move within about four minutes of the collar reporting. Pull to
   refresh for sooner.
5. **Pinch-zoom** on the camera; double-tap to 2.5x, double-tap again to
   reset.
6. **The Robot tab** with `KONA_ROBOT_SNAPSHOT_URL` set and the robot on;
   then switch the robot off and confirm the tab says ROBOT OFF within
   about 15 s; then on again and confirm the picture returns without a
   restart. `docs/first-run.md` §4b.

*Still owed, in order:*
6. The ten-minute polling soak (`/status.json` holds `streams: 0`) and the
   cellular data delta against `docs/scaling-limits.md` §1.
7. Pan/tilt for a C225 if one is ever bought; the C120 has no motors.
   `KONA_CAMERA_MODEL` already gates the pad.
8. `KONA_HEARTBEAT_URL` against healthchecks.io, not yet run. A domain and a
   named tunnel (`docs/remote-access.md` 3a) so the URL survives a restart
   and the Stadia key can move to domain auth. Then the Pi as the real host.
9. One lights-off evening for the camera's black-frame rule in a genuinely
   dark room; with night vision now switchable this is also the check that
   "auto" actually kicks in.
10. After a week of polling holding up, delete `/stream.mjpg` and the
    containment that exists only for it.

*Record, for the reasoning behind any of the above:* `docs/archive/`,
`docs/camera-black-screen-handoff.md` (why the camera polls one frame at a
time), `docs/remote-access.md` "When it breaks" (the quick tunnel failure),
and `.dos/outbox/` (every session's artifact).

## Ownership

| Who | Owns |
|---|---|
| Claude Code (cloud) | code, tests, CI, docs. Cannot see hardware, LAN, or the Fi API. |
| Chris | runs the local steps (`docs/first-run.md`), hardware, `.env`, merges. |
| Astro (ChatGPT) | visual and copy passes. Brief it with `docs/chatgpt-handoff.md`, which lists the constraints that now fail silently (CSP, vendored Leaflet, zoom). |
| Claude Design | Meadow direction chosen; further visual passes edit `web/templates` + `static/app.css`. |

Shared only via GitHub. One branch per assistant.

## v0 scope

In: Fi login, rest/sleep as hero metric, Field visual direction (dark mode
primary, single-hue teal ramp, big tabular hero number, hairlines not cards),
one shared passcode.

In (moved up because the hardware came first): Camera tab, live over LAN.

Not in v0: Whoop, behavior metrics (barking/scratching/eating/drinking:
unconfirmed in the API), remote camera access, HTTPS, per-user accounts.

## Stack (shape: web app, minimal stamp; decided by /grill 2026-09-09)

Python 3.11+, uv, typer, httpx. Web: FastAPI + Jinja (htmx not needed yet),
uvicorn, itsdangerous (signed cookie), opencv-python-headless (webcam, lazy
import). Tests: pytest with `httpx.MockTransport` for Fi and a fake camera
source for the web app; no live Fi calls or hardware in CI.
Lint/format: ruff. CI: ubuntu + windows matrix.

Hosting: the camera server must live at home (the stream originates there):
Windows PC now, Raspberry Pi 5 next. Remote access (Tailscale) and where the
rest lives (Chris mentioned Vercel + Supabase to Astro) are still open; the
app is env-var configured only, so nothing locks that in.

## Commands (PowerShell or Mac Terminal, repo root; plain-language walkthrough in `docs/first-run.md`)

```powershell
uv sync                         # install (first run pulls the OpenCV wheel, ~50 MB)
uv sync --no-build-isolation    # Windows PC only: Application Control blocks plain uv sync
uv run --no-sync kona serve     # Windows PC only: run what is installed without re-syncing
uv run pytest -q                # tests
uv run ruff check . ; uv run ruff format .
Copy-Item .env.example .env     # then fill KONA_PASSCODE, camera keys (and FI_* when the collar arrives)
uv run kona cameras             # usb only: which webcam indexes open -> KONA_CAMERA_INDEX
uv run kona camera-test         # open the configured camera once: size, fps, redacted URL, exact error
uv run kona serve               # http://0.0.0.0:8000 ; allow the Windows Firewall prompt
uv run kona serve --fake-camera # no camera needed; test pattern
uv run kona probe --out probe-out\round12   # Fi API discovery -> summary.md, one round per folder
ipconfig                        # IPv4 of the PC; iPhone opens http://<that-ip>:8000
```

`.env` and `probe-out/` are gitignored. Never commit either.

## Locations

- `src/kona_tracker/fi/` — Fi API client + GraphQL documents
- `src/kona_tracker/probe/` — probe orchestration, redaction, schema scan
- `src/kona_tracker/camera/` — sources (USB, RTSP, steerable fake), capabilities, control protocol, credential redaction, placeholder frame, the supervisor/reader hub
- `src/kona_tracker/web/` — FastAPI app, passcode auth, settings, templates, CSS
- `src/kona_tracker/cli.py` — `kona probe | serve | cameras | camera-test`; `cli_env.py` reads `.env`
- `tests/` + `tests/fixtures/` — mocked Fi responses; fake camera
- `docs/` — per-slice plans; `fi-api-fields.md` once the probe has run
- `.dos/outbox/` — session artifacts (wrap)

## Facts that constrain design

- **Only the camera is location-bound.** The video originates on the home
  network, so the server that reads it must sit there. The Fi probe and the
  app itself run on any machine with internet, home or not.
- `api.tryfi.com` is an ordinary cloud API, blocked *only* from claude.ai/code
  sandboxes (proxy 403). Chris can run `kona probe` from any laptop with
  internet and the Fi credentials; it does not need the home machine.
- Fi's API is undocumented and unversioned; pytryfi (the reference) has not
  shipped since Dec 2023. Expect drift; the probe is the drift detector.
  Its `const.py` is still the best source for field names — read it before
  guessing. Introspection is disabled on the production API.
- **A mock that answers any query tests the parser, not the query.** The
  malformed sleep query passed 102 tests because `tests/conftest.py` routed on
  operation name alone. Mocks must refuse what the server refuses.
- **Fi's day is midnight-to-midnight local, and the newest daily rest window
  is today, in progress.** "Last night" is the window before it. Fetch two.
- **Distance is metres, walks only; walks are detected with a 2-3 min lag;
  escape and walk are independent flags; `timeToEmptyS` is a live power
  estimate, not a battery fact.** All measured on a real walk 2026-09-10.
- **`device.info` is an arbitrary blob and grows when the collar changes
  state.** It carried the home SSID, IMEI, ICCIDs and cell id once on
  cellular. The redactor blanks those key families now; assume the next new
  block will need a look too.
- **Never redact the error that names the fix.** `FiGraphQLError` keeps
  graphql-js validation messages verbatim (they contain schema identifiers
  only) and redacts everything else, including `Expected type "X", found
  <value>`, which echoes literals.
- Starlette's TestClient runs the ASGI app to completion, so an endless
  MJPEG stream cannot be tested through it; `/stream.mjpg?frames=N` caps it.
- A USB webcam opens once per process; the hub is what lets two phones watch.
- An MJPEG `<img>` freezes on the last frame when frames stop; the hub streams
  a placeholder when stale so "frozen" can never pass for "live".
- RTSP credentials must live inside the URL for OpenCV/FFmpeg; `redact_url()`
  runs on every string that could carry it. Keep it that way.
- No RTSP server exists in the cloud sandbox; the network path is proven via
  an in-process HTTP MJPEG server. Real RTSP auth/decode needs the hardware.
- **`docs/device-capabilities.md` is the source of truth for what the
  hardware can do.** Read it before designing any control. Short version:
  the C120 is fixed and the C225/C220/C210 pan and tilt, so abilities are
  data (`KONA_CAMERA_MODEL` -> `camera/capabilities.py`), never assumed in
  a template. Two-way talk is impossible on every Tapo: TP-Link implements
  ONVIF Profile S and the audio backchannel is Profile T. Night vision,
  privacy mode, alarm, LED and motion settings are all available over the
  camera's local API using the same credentials as the video. Recent
  firmware needs **Third-Party Compatibility** enabled in the Tapo app or
  nothing connects.
- **Bandwidth is the camera's real ceiling, and Chris watches on cellular.**
  One viewer at 1280x720 is ~85 KB/frame at 4 fps -- ~340 KB/s, ~1.2 GB an
  hour. JPEG quality is hard-coded at 80 with no env var; width, height and
  fps are configurable. `docs/scaling-limits.md` is the standing list of
  ceilings and what a product version would have to change.
- Scope line: camera control belongs in this app; Apple TV and general home
  automation belong in Home Assistant on the same Pi. See the doc for why.
