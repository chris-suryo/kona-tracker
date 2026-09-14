# Handoff to a ChatGPT session

Paste the block at the bottom into ChatGPT. This page is the long version it
can read from the repo. Written 2026-09-11, refreshed 2026-09-13 for the
visual audit. `PROJECT.md` is the project; this is the brief for a visiting
assistant.

**2026-09-13: the current job is an audit, not a branch.** Claude Code is
working on several branches at once, so a second assistant writing code
produces exactly the reconciliation that PR #7 cost a whole session. Ask for
a report with screenshots and specific proposals; the implementation comes
back here.

---

## The project in a paragraph

A private, passcode-gated, iPhone-first web app so Chris and his sister can
check on Kona, a one-year-old Labrador. Two tabs: **Activity** from her Fi
collar, **Camera** from a Tapo C120 over RTSP in the house. Python, FastAPI, Jinja
templates, plain CSS, no build step, no JavaScript framework, no npm. It runs
on a Windows PC at home because the video originates there. `docs/design-brief.md`
explains why it is HTML and not React, and is the block to paste into a
design session.

## Where the code is

**`main`**, as of 2026-09-13. Everything through PR #33 is merged. CI green
on ubuntu and windows.

## The five rules that matter most here

1. **Plan first, stop for approval** on anything non-trivial. `CLAUDE.md` is
   checked in and governs.
2. **No new dependencies without asking.** That includes a CDN: Leaflet is
   vendored into `web/static/leaflet/` and a test pins its sha256. Adding
   `<script src="https://...">` breaks the build and the CSP at once.
3. **Tests live beside the code.** A change to logic comes with one.
4. **Fail loud, never confident-wrong.** The whole project's character is
   here. If a number is not known, the page shows a dash and says why. Never
   invent a value, never style a stale one as live.
5. **CI must stay green on ubuntu and windows.** `uv run pytest -q`,
   `uv run ruff check .`, `uv run ruff format --check .`

## Things that will break if you touch them without reading first

These are not style preferences. Each one cost real time to get right and
has a test pinning it.

- **No inline `<script>`, no `on*=` attributes, no `style=` attributes.** The
  app sends a Content-Security-Policy of `script-src 'self'`. Every script is
  a file under `web/static/`. The map's data travels as
  `<script type="application/json">`, which is data, not code. An inline
  handler will silently not run in the browser and will fail a test.
- **Zoom is off page-wide on purpose**, at Chris's explicit request, knowing
  it is a WCAG 1.4.4 trade. The map is deliberately exempt. Do not "fix"
  either half. `docs/device-capabilities.md` §2b has the reasoning and the
  revert.
- **`web/static/leaflet/` is byte-pinned.** Do not reformat, re-minify or
  re-download it.
- **The reduced-motion block must stay last in `app.css`.** A test slices the
  file from that media query to the end.
- **`img-src` in the CSP must keep `blob:`.** The Camera tab fetches each
  frame and hands the `<img>` an object URL. Remove `blob:` and the picture
  becomes a silent black rectangle with no error anywhere. A test pins it.
- **Fi's API is undocumented and unversioned.** `fi/parse.py` holds the only
  parsers, shared by the probe and the page. Never add a field to a GraphQL
  document on a guess: a rejected field fails the *whole* document, which is
  why `pet_whereabouts` carries one unverified field alone.
- **`.env` and `probe-out/` are gitignored and must never be committed.**

## What is done

Activity and Camera both work against real data. Recent: her resting
position on the map with honest tiers, a lockout that survives a tunnel,
Secure cookies by setting, security headers, vendored Leaflet,
pull-to-refresh that repaints without tearing down the video, camera health
readable from a phone, a rotating log, times in Kona's timezone, and an
outbound heartbeat so a dead PC still raises an alarm.

## Every page, and what each one is for

Run it with `uv run --no-sync kona serve` (or `--fake-camera` without
hardware) and open `http://localhost:8000`.

| Path | What it is |
|---|---|
| `/activity` | The home screen. Steps against a moving goal, naps today, last night's sleep, where she is, walks today. Re-fetches once a minute while visible; pull down to force it. |
| `/steps` | Today's steps by the hour. `?hour=N` selects one. |
| `/rest` | Today's sleep and naps by the hour, then one bar per day since the collar came online. |
| `/walks/<id>` | One finished walk: distance, pace, the route on a map. Reached from "Walks today". |
| `/map` | The live map, full screen. Route, her dot, how old the fix is. Reached by "Open full map". |
| `/camera` | The picture. Pinch or double-tap to zoom. Night vision, privacy and status light when the camera answers. |
| `/settings` | Kona's profile, collar battery, camera health, sign out. Reached from the avatar. |
| `/robot` | The TurboPi robot's camera, on its own tab. Appears only when `KONA_ROBOT_SNAPSHOT_URL` is set. Says **ROBOT OFF** when it cannot reach it, which is the robot's normal state. |
| `/drive` | **Landscape** drive mode for the robot: a thumb stick, two rotate buttons, an always-live STOP, and a telemetry strip. Portrait deliberately shows "Turn sideways" rather than a squeezed version. Appears only when `KONA_ROBOT_CONTROL_URL` and `KONA_ROBOT_TOKEN` are both set. |
| `/login` | The passcode gate. |
| `/activity?preview=1` | Sample-data mode, fictional readings, for judging layout without a collar. |

## What the numbers mean, so nothing load-bearing gets designed away

- **Steps against the goal.** Fi moves the goal with her fitness, so "of
  28,000" changes between days. That is Fi working, not a bug.
- **Asleep last night** is one overnight bout with the span that describes
  it, e.g. 7h 44m, 00:20 - 08:04. It is deliberately *not* the calendar-day
  total, which is what `/rest` charts per day.
- **A dash is a real state.** It means Fi did not send that value. Never
  replace one with a zero, an average, or a guess.
- **Four honest failure modes** the page must keep distinguishing: not
  configured, failing, **partial** (fresh but one query failed), and stale
  (old numbers, refresh failed). They read differently on purpose.
- **The fix age on `/map`** goes amber past two minutes and red past five,
  because a confident dot in a place she left four minutes ago is worse than
  no map.

## What is genuinely open, in the order that would help

**Read this first, 2026-09-15:** the highest-value target has moved. `/drive`
and `/robot` are the two newest screens and **no human has ever looked at
either on a real phone.** `/drive` is also the only screen in this app where
a design mistake has a physical cost — it moves a four-wheeled robot around a
house. Screenshots of every state are in `docs/screenshots/2026-09-15/` and
`docs/screenshots/2026-09-14/`, including the failure states: the robot may
still be moving, the picture frozen mid-drive, a rejected token, a flat
battery, a stop that did not land.

What would help most on those two, in order:

1. **Is the alarm hierarchy right?** Three things can shout at once — "the
   robot may still be moving", "the stop did not reach the robot", "picture
   1.4 s behind". Today the first outranks the second and the third lives
   quietly in the top strip. Someone steering a robot has about one second of
   attention; is that the right ordering, and is the third one loud enough?
2. **Landscape ergonomics.** The stick sits bottom-left, rotate and STOP
   bottom-right, telemetry across the top, and it has never been held. Are
   the thumbs where they should be? Is STOP reachable without looking?
3. **The telemetry strip's vocabulary.** "Battery 7.90 V" is the robot's own
   number; "Ahead 0.41 m" is the sonar; "Picture live" is how far behind the
   video is. Is volts the right unit for a person, or should it be a bar?
4. **The Slow/Full limiter** is a small pill at the bottom centre and is the
   one control that changes how fast a physical object moves. Is it findable,
   and is its state obvious at a glance?

Then, still open from the last pass:

1. **Visual polish on what landed.** The new pieces were built for honesty
   first and never had a design eye on them: the camera-health rows on
   `/settings`, the map's empty state, the "Resting at Home" location card,
   and the pull-to-refresh indicator. This is the highest-value touchpoint.
2. **`?preview=1` audit.** A sample-data mode exists for reviewing the UI on
   a new collar. Confirm it is unmistakably sample data in *every* state and
   can never be read as Kona's real numbers.
3. **Copy pass.** The page's voice is plain and specific. Check the states
   nobody has seen: not configured, partial, stale, no GPS.
4. Not for a visiting session: the Fi probe, the tunnel, the Raspberry Pi
   migration, and anything about the robot's own software. Those need Chris's
   machine, his decisions, or the other session that owns the robot.

## What a visiting session cannot do

- **Reach the Fi API.** `api.tryfi.com` is blocked from sandboxes. Only Chris
  can run `uv run kona probe`.
- **See the camera or the LAN.** Use `uv run kona serve --fake-camera`.

## Don't retry, each learned the expensive way

- Black camera frames are a **wedged USB device**; replug fixes it. Not the
  resolution, which was disproved.
- Do not add `user-scalable=no`... it is already there deliberately, and the
  iOS half needs the JavaScript, not the meta tag.
- Do not hard-code `secure=True` on the session cookie: it breaks LAN login
  silently.
- Do not use `location.reload()` to refresh: pull-to-refresh repaints in
  place so the picture never blinks. The Camera tab no longer holds an MJPEG
  stream at all -- it fetches one frame at a time from `/snapshot.jpg?after=`
  and hands the `<img>` an object URL. `docs/camera-black-screen-handoff.md`
  is why, and `docs/scaling-limits.md` is what it costs.
- Do not trust a forwarded-IP header from a non-loopback peer.
- A mock that answers any query tests the parser, not the query.

---

## The paste-able block

Refreshed 2026-09-16. **Two things in it are load-bearing and were missing
before.** The commit is pinned, and the report is asked to echo the SHA it
actually read as its first line — because the previous round audited a
three-day-old tip of `main` and nobody could tell until five of its seven
findings were cross-checked by hand against the code. One line would have
caught it. The other is the evidence tagging, copied from the robot session's
post-drive reply, which is the best handoff this project has received from
anyone.

Attach the PNGs from `docs/screenshots/2026-09-15/` and `2026-09-14/`.

## ✂️ ——— START ———

I need a UI/UX critique of a private, phone-first web app. **Give me a report
with specific proposals — not code, and not a branch.** A second assistant
writing code here cost a whole session in reconciliation once already.

### Read this exact commit

`chris-suryo/kona-tracker`, commit
**`1523d362b7768f1953e2a2d43883a39da05dc50e`**.

**Begin your report with the commit SHA you actually read.** If you cannot
fetch that one, say so and stop rather than auditing whatever tip you get — a
previous round audited a three-day-old commit and most of its findings had
already been built.

### How to mark every claim

Tag each finding:

- **[MEASURED]** — I ran it and this is the output.
- **[OBSERVED]** — I saw it on screen; screenshot attached or described.
- **[INFERRED]** — the source says so; I did not see it happen.

Never round an unknown up to a known. Quote captured output rather than
remembered output. If something is a guess, say it is a guess. If the most
important thing is still unknown at the end of your work, lead with that.

### The app

A passcode-gated page two people use to check on their dog, Kona, from a Fi
collar, plus a camera at home and a small robot they drive around the house.
Python, FastAPI, Jinja templates, plain ES5 JavaScript, one hand-written
stylesheet. **No build step, no framework, no CDN, no inline script** (the
page carries a Content-Security-Policy with `script-src 'self'`). Light and
dark follow the phone. Page zoom is off everywhere by the owner's explicit
request. No new dependencies.

Run it with `uv run --no-sync kona serve --fake-camera`; no hardware needed.
`/activity?preview=1` renders the layout against fictional readings.

### What I want looked at

**Pull-to-refresh on `/activity`, and the Activity tab as a whole.** The
owner's words: it "needs a little bit more of a tasteful, professional eye,
just so the mechanics and everything don't seem AI-generated."

**I already know why it feels wrong. I want a design, not a diagnosis** — so
here is the diagnosis, to argue with rather than rediscover
(`src/kona_tracker/web/static/app.js`):

- `RESISTANCE = 0.5` is a flat linear multiplier. No curve, no damping, no
  asymptote. The finger travels 120 px to cross a 60 px threshold.
- The indicator **hard-stops** at 88 px of travel while the finger keeps
  going, so past that point the gesture has no feedback at all.
- Opacity maxes out at 72 px — *before* the threshold — so the last half of
  the pull is visually inert.
- The real tell: `overscroll-behavior: contain` stops iOS's own reload but
  **not** its elastic scroll. So during a pull the page content rubber-bands
  at 1:1 while the pill slides at 0.5x. Two surfaces moving at different
  speeds is what reads as unconsidered.
- There are no haptics at any stage.
- Returning to the app plays the full "Refreshing…" → "Updated" sequence
  unprompted, with no gesture.

### Constraints that fail silently here

Vendored Leaflet (not a CDN copy); `img-src blob:` in the CSP is load-bearing
for the camera; the map and the camera picture are the only two deliberate
exceptions to the no-zoom rule; both themes must work; no new dependencies.

**Behaviour pinned by tests — a proposal that breaks one of these needs to say
so explicitly:** the 60 s quiet refresh tick; the `?fresh=1` versus plain
`/activity` split; the 20 s request timeout; the 650 ms "Updated" hold; the
220 ms dismissal; and that 150 px of finger travel must still arm the gesture.

### Already fixed — please do not re-report

From the 13 September round, all built and pinned by tests: preview no longer
links into the real-data map; hidden map panels now respect `[hidden]`; an
unknown step goal shows `–` and "Goal progress unavailable" rather than `0%`;
camera health says "Idle · opens when viewed" and its failure advice is
source-aware rather than assuming USB; the reduced-motion block is last in the
stylesheet again.

Still open and known, so no need to find them: the refresh says "Updated"
regardless of whether the data came back stale or partial; several strings
describe the server rather than the dog (including one that prints our polling
interval on screen); `.env` variable names appear on user-facing pages.

### What would help most

1. The pull gesture's **feel**: the curve, what the indicator should show
   between rest and threshold, how it should settle, and what — if anything —
   should mark completion. Concrete numbers, not adjectives.
2. The Activity tab's **rhythm**: what earns its place above the fold, what is
   repeated, what a person checking on their dog for ten seconds needs.
3. **Copy**: the page should tell someone about Kona or about something they
   can do. Flag anything that is about us instead.
4. Anything that reads as decoration where it should read as instrument.

Be specific and concrete. If something is fine, say so and move on.

## ✂️ ——— END ———
