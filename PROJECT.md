# kona-tracker

Private, passcode-gated, iPhone-first web app for Chris and their sister to
check on Kona (dog). Activity tab from her Fi collar (Whoop later); Camera tab
once the hardware exists.

---
kit: 3e06b156508b881bef26345c0bb7a63c90db4824 · stamped by dos new
---

## Status (2026-09-11, chapter 2)

**Start from `main`.** It is no longer stale: chapter 2's work lands there by
PR rather than accumulating on a long-lived branch. Branch from `main`, open
a PR, Chris merges. The overnight UI pass is in; the Fi data brief and the
camera rewrite from MJPEG to snapshot polling are PRs #9 and #8. One branch
stays deliberately unmerged -- `chatgpt/ui-pass` (PR #7), a visiting
assistant's work in flight.

`docs/production-punchlist.md` is the queue and carries the reasoning behind
every item; `docs/scaling-limits.md` is the standing list of ceilings;
`docs/chatgpt-handoff.md` is the brief for a visiting assistant.

- **Slice 1:** `kona probe` dumps every Fi API field, redacted. Still
  unverified against the real API. `docs/slice-1-probe-plan.md`.
- **Slice 2 + 2b:** `kona serve` = passcode gate, live camera (USB or RTSP,
  reconnects, "NO SIGNAL" when stale). Verified with simulated cameras only.
  `docs/slice-2-camera-plan.md`, `docs/slice-2b-rtsp-plan.md`.
- **Pan/tilt:** abilities are data (`KONA_CAMERA_MODEL` ->
  `camera/capabilities.py`); the fake camera is steerable so the control
  surface exists before the hardware. `docs/device-capabilities.md`.
- **Slice 3 (Activity is real):** `fi/parse.py` holds the only parsers, shared
  by the probe and the page. `fi/service.py` caches one snapshot, refreshes on
  a background thread past `KONA_FI_REFRESH_SECONDS`, and never discards a good
  reading when a refresh fails. `/activity` and `/activity.json` render four
  honest states: not configured, failing, **partial** (fresh but a query
  failed), and stale (old data, refresh failed).
- **Slice 4 (first contact with the real API, 2026-09-10):** steps are live.
  Sleep was rejected — `RestSummary.data` is abstract and `sleepAmounts` needs
  an inline fragment on `ConcreteRestSummaryData`. Fixed. The probe now also
  asks for profile/photos, device/connection, and location, and
  `FiGraphQLError` preserves the whole graphql-js validation family instead of
  one message shape. See `docs/device-capabilities.md` §2 for what is
  confirmed present, confirmed **absent**, and untrustworthy.
- **Motion:** `@view-transition { navigation: auto; }` gives animated
  cross-document navigation on Safari 18.2+ and Chrome 126+; the dial arc
  sweeps up and the stats stagger in. All CSS, no build step, all inside
  `prefers-reduced-motion` guards. `docs/design-brief.md` explains why the app
  is HTML and not React, and is the block to paste into a design session.
- **Slice 5 (production pass, 2026-09-11):** her resting position on the map
  with honest tiers, a login lockout that survives a tunnel, Secure cookies
  by setting, a CSP with every script in a file, vendored Leaflet,
  pull-to-refresh that repaints without dropping the video, page zoom off by
  request, camera health readable from a phone, a rotating log, times in
  Kona's timezone, and an outbound heartbeat so a dead PC still raises an
  alarm. `docs/production-punchlist.md` marks what is done and what is left.
- **Hardware:** Fi collar paired and live since 2026-09-10. The USB webcam
  (Logitech C270, fixed) works; its recurring failure is a **wedged USB
  device**, cleared by a replug, not a code or resolution problem. Blink
  Mini 2K+ and Wyze v4 do NOT work without unofficial bridges.
- **Hardware bought 2026-09-11** (an earlier version of this bullet said a
  Pi was already bought and unopened -- it was not, and acting on that sent
  a session telling Chris the wrong thing while he stood in the store):
  one **Raspberry Pi 5 8GB, open box**, a 52Pi case with fan, a 128 GB
  microSD, a card reader, an RTC battery, a **Hiwonder TurboPi** robot kit
  (**no Pi included**, so the Pi 5 is its brain for now), and a 6 ft USB-A
  extension for the C270. **No power supply** -- Chris is trying a charger
  he already owns, so an undervoltage check is the first thing to do.
- **Kona still runs on the Windows PC**, and should. The Pi migration waits
  on the Tapo, per `docs/handoff.md`: prove the new camera on a machine that
  already works. `KONA_KEEP_AWAKE=true` in `.env` is the whole of "leave it
  running"; boot-start (`docs/remote-access.md` 3c) stays deferred as the
  least-tested step in the setup.

**next:**

*The camera on the phone: fixed, merged, and confirmed on 2026-09-11.*
`docs/camera-black-screen-handoff.md` is the whole record. Two bugs. The
slow reveal is fixed. The second, the one that hung the phone on
"Connecting…" after a tab switch, was abandoned MJPEG streams piling up
until the small pool the stream waits use was full; restarting `kona serve`
cleared it every time, which is what proved it was ours and not Safari's.
The Camera tab now polls `/snapshot.jpg` one frame at a time, so nothing
outlives a request and nothing can pile up; the MJPEG path that remains is
fenced and capped; `/status.json` reports `streams` and `viewers`.

**Chris confirmed it on the real phone**: force-close and reopen, switching
browsers, restarting `kona serve` with the page open, and **three devices
streaming at once** off one camera open. He also reached it over the
Cloudflare tunnel on cellular with Wi-Fi off, which was the first real
exercise of `docs/remote-access.md` Part 0.

0. **Still unverified, and both are his to run:** the ten-minute soak
   (`/status.json` should hold `streams: 0`, `viewers` bouncing 0/1, and
   `opens` at 1), and the cellular data cost -- baseline noted at 37.7 GB on
   Safari's counter, and the delta tests the 1.2 GB/hour estimate in
   `docs/scaling-limits.md` §1. If it disagrees, that doc is wrong.
1. **After a week of polling holding up**, delete `/stream.mjpg` and the
   containment that exists only for it.

*Needs Chris, and blocks the Fi half:*
2. **Probe round 5.** `uv run kona probe --out probe-out\round5`, then read
   `whereabouts` in `summary.md`. It settles whether Fi returns
   `... on OngoingRest { position }`, which is the one field the map's
   resting tier rests on. Sourced from pytryfi, not yet measured on Kona's
   collar. If Fi rejects it the page already says so and falls back to the
   home pin, so nothing is broken either way.

*The road to always-on, in order, and nothing here has been run:*
3. `docs/remote-access.md` Part 1: a Cloudflare quick tunnel, about fifteen
   minutes, no domain needed. The proving step.
4. `KONA_HEARTBEAT_URL` against healthchecks.io, so a sleeping or dead PC
   raises an alarm. Part 3d.
5. `KONA_KEEP_AWAKE=true` while serving, rather than switching sleep off in
   the power plan. Part 3b has the electricity arithmetic.
6. A domain, then a named tunnel, so the URL survives a restart. Part 3a.
   Without it the quick tunnel hands out a new address every time.
7. The Pi as the real host. Everything above is a patch on a machine that
   was never meant to be a server.

*Still owed, needs the hardware:*
8. One lights-off evening to check the camera's black-frame rule behaves in
   a genuinely dark room. The wedged-device half is measured; the dark-room
   half is reasoned.

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
uv run pytest -q                # tests
uv run ruff check . ; uv run ruff format .
Copy-Item .env.example .env     # then fill KONA_PASSCODE, camera keys (and FI_* when the collar arrives)
uv run kona cameras             # usb only: which webcam indexes open -> KONA_CAMERA_INDEX
uv run kona camera-test         # open the configured camera once: size, fps, redacted URL, exact error
uv run kona serve               # http://0.0.0.0:8000 ; allow the Windows Firewall prompt
uv run kona serve --fake-camera # no camera needed; test pattern
uv run kona probe               # Fi API discovery -> probe-out\summary.md
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
