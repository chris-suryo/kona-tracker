# What the data affords: a brief for UI work

For a session doing design or front-end work. `docs/chatgpt-handoff.md`
covers the constraints and the queue; this covers the thing underneath
both. Every tile on that page is a claim about a live animal, and what Fi
actually returns decides which claims we are entitled to make. Design that
outruns the data is not a nicer app, it is a confident lie about a dog.

Sources: measured against Kona's collar by `kona probe`, plus what Fi's own
in-app assistant said on 2026-09-11, recorded in `docs/device-capabilities.md`
as claims rather than facts.

---

## 1. What we actually have

Every field below reaches the browser today at `/activity.json`.

**Movement**
- `steps` today, and `step_goal`. **The goal adapts**: Fi sets it from
  breed, age and weight, then moves it with her recent activity. A goal
  that differs between days is Fi working, not a bug, and the page must not
  imply a fixed target.
- `week_steps`. Monthly totals are **fetched by the query and thrown away**
  in `fi/service.py`; only daily and weekly are parsed.
- `distance_m` and `week_distance_m`, in metres. **This is outdoor GPS
  distance, not steps converted.** A day of 3,383 indoor steps legitimately
  reports zero. That was an open mystery in our docs for a week and is now
  explained, which unblocks showing it, provided it is labelled as outdoor
  or walk distance and a zero never reads as "she did not move".
- `walk_distance_m` during a walk in progress.

**Rest**
- `sleep_seconds` for last night, `today_nap_seconds` for naps so far, plus
  `window_start` / `window_end` bounding the night. Fi splits these by
  duration and continuity: the long consolidated overnight block is sleep,
  short fragmented daytime rest is naps.
- Fi's day rolls over at **midnight in the dog's timezone**, not the
  server's and not the viewer's. `timezone` comes from Fi; `clock` says
  whether we managed to use it or fell back to the server.

**Where she is**
- `positions`, the 1 Hz GPS route during a walk, with `accuracy_m` from 65 m
  on a cold fix down to 4 to 7 m. `positions_carried` flags a route kept
  from a finished walk so it can never be dressed up as current.
- `rest_position`, her position while resting. **Unverified**: sourced from
  pytryfi, asked for in its own query, awaiting a probe run. Fi's assistant
  says the app does show a resting location, synced every few minutes, so
  the prior is good.
- `home_position`, the saved home pin. A place, not a fix; it carries no
  timestamp and must never be labelled as one.
- `area_name`, a place label. A saved place's name is street-address-shaped
  and is normalised to "Home" server-side; the raw address must never reach
  the page.

**The collar**
- `battery_percent`, and `on_base` plus `signal_percent` for charger versus
  cellular. `time_to_empty_s` exists but swings from four days to twelve
  hours depending on whether GPS is running. It is a power estimate, not a
  battery fact. Never headline it.
- `activity` is `rest` or `walk`, with `activity_since` saying when that
  began. **`activity_since` is parsed, exposed, and never rendered.**
- `escaped` and `lost` from Fi's mode. The escape flag is real and was
  measured when she left the safe zone.

**Her**
- Name, breed, birthday, and her photo from the Fi app, proxied through
  `/avatar.jpg` so the CDN URL never reaches the browser.

**Whether to believe any of it**
- `fetched_at`, `stale`, `problem`, and a derived `partial`. Three different
  failures that must never share a sentence: old numbers, current numbers
  with a hole in them, and nothing at all.

## 2. Confirmed absent: do not design for these

Asked for, rejected by Fi's server with no near-miss suggested, which this
project treats as evidence of absence.

Sleep quality or score at any level. Heart rate. Calories. Active minutes.
Barking, scratching, licking, eating or drinking counts. Geofences as such.

Fi's assistant claimed twice that the collar reports behaviours and active
minutes. It is a language model describing a product line; the server
rejects the field names. **The measurement wins, and none of it goes on the
page.** A "behaviour" card would be inventing data about someone's pet.

## 3. The cadence, which is the real design constraint

The collar does not stream. It samples continuously and **syncs in batches
over Bluetooth or Wi-Fi, several times a day**. Today's numbers fill in
gradually. At rest, location is a periodic check-in every few minutes, not
a live feed. Walks are recognised a few minutes after they start and closed
a few minutes after they end.

So the app cannot be more live than the collar, and a design language that
implies real-time telemetry would be lying on Fi's behalf. The only live
thing in this product is the camera. Everything from the collar is a
reading with an age, and the age belongs on screen.

## 4. The honesty doctrine, as a design language

This is the part most worth internalising, because it is the project's
character and it is enforced by tests.

- A dash means we do not know. A zero means we know it is zero. They must
  look different.
- Nothing stale may be styled like something live. The page already dims
  stale figures and changes their wording.
- Every claim traces to a measured field. If a design needs a number Fi
  does not send, the answer is a different design, not a plausible value.
- Failure states are first-class, not error screens bolted on. Not
  configured, partial, stale and failing each get their own honest sentence.

## 5. Where the differentiation actually is

- **Fi has no camera.** This is the only place where "where is she" and
  "let me look at her" are the same screen. That is the whole product.
- **The job is different.** Fi's app is a dashboard for an owner. This is a
  check-in for two people who want one answer: is she OK. One glance, no
  scrolling, no feed.
- **Honesty is a feature.** Fi shows a number. We say when we do not know
  one. For a person away from home, "we last heard from her at 18:42" beats
  a stale figure presented as current.
- **We can derive Fi's own alerts.** Asked what it notifies on, Fi named
  safe-zone crossings, meeting or missing the step goal, low battery or
  disconnection, and walk milestones. Every input to all four is already in
  our snapshot.

## 6. Real data lying unused

Opportunities that need no new API access and no new query.

| Available now | Currently |
|---|---|
| `activity_since` | Parsed and exposed, never shown. "Resting since 10:42" answers a question the page raises and does not close. |
| Monthly steps | Fetched by the query, discarded before parsing. |
| `distance_m` | Hidden pending an explanation that now exists. |
| `next_update` | Parsed, unused. Fi tells us when the next location check-in is due. |
| `led_on`, `led_color` | Parsed, unused. |
| `week_distance_m` | In the JSON, not on the page. |

One more that needs a single probe query, not new access: a Safe Zone is
very likely a saved Place with a radius, which would let the map draw the
boundary rather than only reporting a crossing after it happens.

## 7. Constraints that fail silently

Each has a test, and each has already cost real time.

- **No inline `<script>`, no `on*=` attributes.** The page sends
  `script-src 'self'`. An inline handler will simply never run.
- **No CDN links.** Leaflet is vendored and byte-pinned.
- **Page zoom is off deliberately**, at Chris's explicit request, knowing it
  is a WCAG 1.4.4 trade. The map is exempt. Do not "fix" either half.
- **The `prefers-reduced-motion` block must stay last in `app.css`.**
- **No new dependencies without asking.** No npm, no build step.
- **Never add an unverified field to a Fi query.** A rejected field fails
  the entire document and takes working data down with it.

---

## The paste-able block

> I'm working on kona-tracker, a private iPhone-first web app showing my dog
> Kona's Fi collar data and a live camera from my house. Python, FastAPI,
> Jinja, plain CSS, no build step, no JS framework.
>
> Before more UI work, understand what the data can support. The full brief
> is `docs/data-brief.md` on branch `claude/elegant-sagan-tit1xp`. The short
> version:
>
> **We have:** steps and an adaptive step goal, weekly steps, outdoor GPS
> distance, last night's sleep and today's naps in seconds, her GPS route
> during walks, a home pin, her resting position (unverified), battery,
> charger versus cellular with signal, resting or walking plus when that
> started, an escape flag, and her photo, breed and birthday.
>
> **We do not have, and must never imply:** sleep quality or score, heart
> rate, calories, active minutes, barking or scratching counts. Fi's own
> in-app assistant claims some of these exist; Fi's API rejects every one of
> those field names. The measurement wins.
>
> **The cadence is the real constraint.** The collar syncs in batches
> several times a day, not in real time. At rest, location is a check-in
> every few minutes. So the app cannot be more live than the collar, and
> only the camera is genuinely live. Every collar number is a reading with
> an age, and the age belongs on screen.
>
> **The design language has to encode certainty.** A dash means unknown, a
> zero means known-zero, and they must look different. Nothing stale may be
> styled like something live. If a design needs a number Fi does not send,
> the answer is a different design, not a plausible value.
>
> **Where we differentiate:** Fi has no camera, so this is the only screen
> where "where is she" and "let me see her" are the same question. And the
> job is a two-person check-in answering "is she OK" at a glance, not a
> dashboard to browse.
>
> **Unused data worth designing with:** how long she has been resting or
> walking, monthly step totals, outdoor distance, and when the collar's next
> location check-in is due. All already fetched, none currently on screen.
>
> **Constraints that break things silently:** the page sends a
> Content-Security-Policy so no inline `<script>` and no `onclick`
> attributes; Leaflet is vendored and byte-pinned so no CDN links; page zoom
> is disabled deliberately and the map is deliberately exempt; the
> reduced-motion block must stay last in `app.css`; no new dependencies
> without asking.
>
> Propose changes before writing code, keep `uv run pytest -q` and
> `uv run ruff check .` green, and work on a branch.
