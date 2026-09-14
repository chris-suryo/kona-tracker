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

Refreshed 2026-09-15 for the robot. Paste everything between the scissors,
and attach the PNGs from `docs/screenshots/2026-09-15/` and
`docs/screenshots/2026-09-14/`.

## ✂️ ——— START ———

I need a UI/UX critique of two screens in a private, phone-first web app. I
will paste screenshots. **Give me a report with specific proposals — not
code, and not a branch.** A second assistant writing code here cost a whole
session in reconciliation once already.

**The app**: a passcode-gated page two people use to check on their dog, and
now also to drive a small four-wheeled robot around the house. Python,
FastAPI, Jinja templates, plain ES5 JavaScript, one hand-written stylesheet.
**No build step, no framework, no CDN, no inline script** (the page carries a
Content-Security-Policy with `script-src 'self'`). Both light and dark themes
follow the phone. Page zoom is off everywhere by the owner's explicit
request. No new dependencies.

**The two screens**:

1. `/robot` — portrait. The robot's camera on its own tab, with a link into
   drive mode. It says ROBOT OFF when the robot is off, which is most of the
   time: it runs on two rechargeable cells.
2. `/drive` — **landscape only**. Full-bleed camera picture with controls
   over it: a thumb stick bottom-left for translate (this robot strafes
   sideways, so the stick genuinely moves it sideways rather than turning
   it), two rotate buttons and a big STOP bottom-right, a telemetry strip
   across the top, and a Slow/Full speed limiter centre-bottom. Portrait
   shows "Turn sideways" instead, because iOS Safari cannot be asked to
   rotate the screen.

**What matters here that would not matter on an ordinary screen**: this one
moves a physical object that can fall off a table or hit someone. The robot
holds its last motor command until something tells it otherwise. So the
screen's job is not only to look good — it is to never be calm when the robot
might be moving, and never to claim a reading it does not have.

Three different alarms can appear:
- "The robot may still be moving. The gateway has not had a stop confirmed."
- "The stop did not reach the robot." (plus a reason)
- "Picture 1.4 s behind" — the video has frozen while someone steers by it.

**Please tell me:**
1. Is the alarm hierarchy right? The first currently outranks the second, and
   the third sits quietly in the top strip. Someone driving has about a
   second of attention.
2. Landscape ergonomics — thumbs, reach, whether STOP can be hit without
   looking. It has never been held by a person.
3. The telemetry strip: is "7.90 V" meaningful to a human, or should battery
   be a bar? Is "Picture live" / "1.4 s behind" understandable?
4. Is the Slow/Full limiter findable, and is its state obvious? It is the one
   control that changes how fast a real object moves.
5. Anything that reads as decoration where it should read as instrument.

Be specific and concrete. If something is fine, say so and move on.

## ✂️ ——— END ———
