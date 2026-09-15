# Handoff to a ChatGPT session

Paste the block at the bottom into ChatGPT. This page is the long version, and
it stays here: `PROJECT.md` is the project, this is the brief for a visiting
assistant. Written 2026-09-11; rewritten 2026-09-14, twice in one day, because
the premise under it moved.

**The repository is public as of 2026-09-14.** For its first five days it was
private, and two rounds of outside audit were run as though it were not —
the second even asked the reviewer to echo the commit SHA it had read, a check
on something that could not happen. What came back was inference in the
register of reading, which is why findings arrived describing code that had
been rewritten weeks earlier. Nobody was lying; the prompt asked for something
unobtainable and left no graceful way to say so.

That is fixed at the source now: a visiting assistant can read the code. So
the brief asks for both halves of the evidence —

- **the source**, pinned to a commit, with the SHA echoed back, which is now a
  check that can actually pass; and
- **the screenshots** in `docs/screenshots/current-ui/`, because reading the
  templates is not the same as seeing what they render, and nobody outside can
  run this app. Regenerate them (`docs/screenshots/README.md`) before asking.

**The job is an audit, not a branch.** Claude Code has several branches open at
once, so a second assistant writing code produces exactly the reconciliation
PR #7 cost a whole session. Ask for a report with specific proposals; the
implementation comes back here.

---

## The project in a paragraph

A public-source, passcode-gated, iPhone-first web app so Chris and his sister
can check on Kona, a Labrador. Three tabs: **Activity** from her Fi collar,
**Camera** from a Tapo C120 over RTSP in the house, and **Robot** — a Hiwonder
TurboPi rover with its own camera, which they can drive around the house from
a landscape-only page. Python, FastAPI, Jinja templates, plain CSS, no build
step, no JavaScript framework, no npm. It runs on a Windows PC at home because
the video originates there. `docs/history/design-brief.md` explains why it is HTML and
not React, and is the block to paste into a design session.

**The code being public does not make the deployment public.** Secrets live in
`.env`, which is gitignored and has never been committed; every token, key and
password in the tests is a visible fake. The app itself is passcode-gated and
reachable only over the home network or Tailscale.

## Where the code is

**`main`**, as of 2026-09-14 (`86727a6`). Everything through PR #44 is
merged; nothing is stacked or waiting, and every branch on the remote is fully
contained in `main`. CI green on ubuntu and windows.

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
house. Screenshots of every state are in `docs/screenshots/history/2026-09-15/` and
`docs/screenshots/history/2026-09-14/`, including the failure states: the robot may
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
  and hands the `<img>` an object URL. `docs/history/camera-black-screen-handoff.md`
  is why, and `docs/scaling-limits.md` is what it costs.
- Do not trust a forwarded-IP header from a non-loopback peer.
- A mock that answers any query tests the parser, not the query.

---

## The paste-able block

Rewritten **2026-09-14**, second revision of the day: the repository went
public between the two, so the reviewer can now read the code as well as see
it. Both halves are asked for, and the tagging separates them — `[READ]` cites
a path, `[OBSERVED]` cites a screenshot, and neither may be used for the other.

`[MEASURED]` is still not offered. A reviewer who can read the source and see
the output still cannot *run* the app, and a tag that invites someone to
report a measurement they did not take is worse than no tag at all.

**On the pin, and why it is written loosely.** A document cannot pin the commit
that contains it: the moment this file is merged, the tip it names is one
behind. Chasing that with another commit only moves the problem. So the pin
names a known-good commit *and* permits the current tip, and the reviewer is
asked to report which it actually read rather than to fail a check that the
repository's own history guarantees it will eventually fail. Verify it is still
true before pasting — `git diff --stat <pinned>..main -- src/ tests/` should be
empty — and re-pin when it is not.

## ✂️ ——— START ———

I need a professional UI/UX critique of a phone-first web app. **Give me a
report with specific, concrete proposals — not code, and not a pull request.**
A second assistant writing code here cost a whole session in reconciliation
once already.

### Read this exact commit

**`chris-suryo/kona-tracker`** is a public GitHub repository. Read it at commit
**`b6e20cda863c42c8fe70cba49e1ada838fee49dc`**, or at the current tip of `main`
if that has moved on — `src/` and `tests/` have not changed since `38afbeb`, so
either way you are reading the same application.

**Begin your report with the commit SHA you actually read.** An earlier round
audited a three-day-old commit and most of its findings had already been built;
one line at the top would have caught it in seconds. If the SHA you read is not
one of the two above, say so plainly and carry on — that is information, not a
failure.

Useful entry points:

- `src/kona_tracker/web/templates/` — every page
- `src/kona_tracker/web/static/app.css` — the entire stylesheet, hand-written
- `src/kona_tracker/web/static/app.js`, `drive.js`, `camera.js`, `map*.js`
- `src/kona_tracker/web/views.py` — where most user-facing strings are built
- `PROJECT.md`, `docs/history/design-brief.md`, `docs/device-capabilities.md`

### Also look at the screenshots I attached

Reading a template is not seeing what it renders, and you cannot run this app.
The screenshots are captured from the **real running application** at
**390×844 logical pixels, 2× device pixel ratio** (iPhone 14/15), full-page, in
**both light and dark**. They are in `docs/screenshots/current-ui/` in the repo
as well, if you would rather fetch them.

Every file below exists twice, `-light` and `-dark`:

| File | Page |
|---|---|
| `login` | the passcode gate, signed out |
| `activity` | the Activity tab — the front page, opened most |
| `map-live` | the full-screen live map |
| `rest` | sleep and naps, hour by hour |
| `steps` | steps, hour by hour |
| `walk-detail` | one walk, with its route |
| `camera` | the house camera |
| `robot` | the robot's camera tab |
| `settings` | collar details and app settings |
| `history-preview` | the sample-data history view |
| `drive-landscape` | **drive mode**, 844×390 |
| `drive-portrait-prompt` | drive mode held upright |

### How to mark every claim

- **[READ]** — the source says so. **Cite the path, and the line if you can.**
- **[OBSERVED]** — visible in a screenshot. **Name the file.**
- **[INFERRED]** — you reasoned your way there; you did not read it or see it.
- **[ASK]** — you need something you could not get. Say what.

These are not interchangeable. Reading `RESISTANCE = 0.5` is `[READ]`; saying
the gesture therefore *feels* sluggish is `[INFERRED]`. Neither a still frame
nor the source shows motion, gesture feel, timing on a real device, or
haptics — claims about those are `[INFERRED]` at best and should say what
would confirm them.

Never round an unknown up to a known. If the most important thing is still
unknown when you finish, **lead with that.**

### The app

A passcode-gated site two people — a man and his sister — use to check on
their dog, Kona, a Labrador. Three tabs: **Activity** from her Fi collar,
**Camera** (a Tapo C120 in the house), and **Robot** (a small Raspberry Pi
rover they drive around the house, with its own camera). It is used on
iPhones, one-handed, usually for about ten seconds at a time, often while
doing something else. Two users, ever.

Python, FastAPI, Jinja templates, plain ES5 JavaScript, one hand-written
stylesheet. **No build step, no framework, no CDN, no inline script.**

You can run it yourself if you want to — `uv run kona serve --fake-camera`
needs no hardware, and `scripts/audit_server.py` is what produced the attached
screenshots. But **do not report anything as measured unless you genuinely ran
it and are quoting the output.**

### What I want, in priority order

**1. Hierarchy and rhythm.** What earns its place above the fold on each page?
What is repeated, what is decorative, what would a person checking on their dog
for ten seconds actually need? Be willing to say "delete this."

**2. Alignment, spacing, and the grid.** The owner's words: *"the text not
aligning right."* He is not a designer and cannot name what is wrong, so name
it for him — baselines, optical alignment, inconsistent gutters, ragged right
edges, things that are nearly-but-not aligned, anything that overflows or clips
at 390 px. You have the stylesheet **and** the rendered output, so this is the
section where you can be most useful and most exact. Be pedantic; this is the
complaint that started it.

**3. Every string, audited.** The house rule: a line either tells you something
about **Kona** or about something **you can do**. Anything describing the
server, the polling interval, the API, or the app's own internals is a bug.
Most of them are built in `views.py` and the templates, so you can go through
them exhaustively rather than sampling. Flag what fails that test, what is
jargon, what is redundant, what is longer than it needs to be, and what is
missing. The owner's standard: it should not *"seem AI-generated."*

**4. Light and dark as equals.** Dark is not a filter over light. Compare the
pairs, and check the token definitions in `app.css` against what actually
renders.

**5. The Drive page — a real open design question, not a critique.** See below;
this is where I most want you to design rather than review.

**6. Anything that reads as decoration where it should read as an instrument.**
This app's one hard rule is that the screen never says something it does not
know. Flag anything that looks more confident than the data behind it could
justify.

### The Drive page — the question I actually want designed

Read `templates/drive.html`, `static/drive.js` and the `.drive-*` rules in
`app.css`, and look at `drive-landscape-*.png`.

Today: one thumb stick bottom-left for movement, rotate buttons, an always-live
**STOP**, a speed-cap toggle, and a telemetry strip. The robot has **mecanum
wheels**, so it strafes sideways as well as driving and rotating. Its camera
sits on a **pan/tilt servo that is not yet wired to anything on screen** — that
is what this question is for.

The owner's instinct: **two sticks, like a game controller.** Left drives the
body, right aims the camera. Answer concretely:

- Does that work with two thumbs on an 844×390 landscape phone, when the thing
  you are actually watching is the camera picture filling the background? Where
  does each stick sit, how big, how far from which edge?
- The left stick is **relative** (thumb position = velocity, springs back to
  centre). A camera stick would most naturally be **absolute** (thumb position
  *is* the camera angle, ±45°, and it stays where you put it). Is mixing those
  two grammars on one screen confusing? If so, what beats it?
- Where does STOP go so it is never more than a thumb-flick away but cannot be
  hit by accident — including by a palm resting on a phone held in landscape?
- The controls sit on top of a live photograph that could be any colour. How do
  they stay legible without covering the thing being steered?
- **Nobody has yet measured which way the robot physically moves.** If an axis
  turns out mirrored, does your layout survive a sign flip, or does it bake the
  wrong assumption into muscle memory?

### In the screenshots but NOT bugs — please don't spend the report on them

- **"Map unavailable"** on every map: the capture machine has no network route
  to the tile server. On a real phone a map renders there.
- **The camera pictures are a synthetic test pattern** from the fake camera
  driver. Judge the frame, the controls and the overlays around it; not the
  image.
- **Every number, walk, time and place is a fixture** (`scripts/audit_server.py`
  if you want to see exactly which). Judge the formatting and layout, not the
  values.
- **The avatar is a "K" monogram** because the fixture carries no photo.
- The robot is named **"Rover"** in the fixture.
- Settings says the camera source is **"Webcam on this computer"** — the
  capture uses the fake driver; the real one is a network camera. The row is
  real, the value is a fixture.

### Constraints that will fail silently if you design around them

- No build step, no framework, no CDN, **no inline `<script>` or `<style>`** —
  the page carries a Content-Security-Policy with `script-src 'self'`.
- Plain ES5 JavaScript (no arrow functions, no `const`), Jinja templates, one
  hand-written stylesheet. **No new dependencies.**
- Both themes must work. Colours are tokens defined once and swapped.
- **Page zoom is deliberately off** everywhere except the map and the camera
  picture. The owner asked for it, was told it is a WCAG 1.4.4 failure, and
  reaffirmed it; it is recorded as a decision in `docs/device-capabilities.md`
  with its one-line revert. Don't re-litigate it; do flag anything that makes
  its cost worse.
- Two users, both on iPhones, in Safari. No desktop, no tablet, no Android.
- Leaflet is vendored into `static/leaflet/` and a test pins its sha256.
- There is a test suite (473 tests) that pins a lot of behaviour. If a proposal
  breaks a test, say so — `tests/test_audit_regressions.py` in particular exists
  to keep previous audit fixes from being undone.

### Already known — don't spend the report re-finding these

- The pull-to-refresh gesture on Activity feels wrong and is being redesigned
  separately. Read it if you like (`static/app.js`), but it is already queued.
- "Updated" after a refresh reports that our own server answered, not that
  fresh data arrived. Known, being fixed.
- "Ask Fi every 20 s while you are out" is exactly the kind of string rule 3 is
  about. Known — but tell me if you find others like it, because that is the
  point.
- The collar battery in the Activity header clips at 390 px, and the Robot
  tab's subtitle wraps to three ragged right-aligned lines. Both already spotted.

### What would help most

A report I can hand to an engineer and have them know what to change. Ranked,
most-worth-doing first. Concrete numbers rather than adjectives. Cite the file
you read or the screenshot you saw for each finding. If something is genuinely
fine, say so in one line and move on — an audit that finds something wrong with
everything is not useful to me.

## ✂️ ——— END ———
