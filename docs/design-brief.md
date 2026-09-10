# Design brief — paste this into a design session

Two rounds have been burned already: one drew controls the hardware cannot
perform, one came back in a format that had to be hand-translated. This file
exists so a third round starts from what is true. Paste the block below,
unchanged, at the top of any Claude Design (or similar) session, then add
what you want changed.

Refresh the "What the data actually is" section from
`probe-out/summary.md` whenever the probe is re-run — that file is the only
evidence about Fi we have, and a design built on hoped-for fields is a
design we cannot ship.

---

## The block to paste

> **Project.** Kona Tracker: a private, passcode-gated web app for two
> people — Chris and their sister — to check on one dog, Kona. Two tabs:
> Activity (from her Fi collar) and Camera (live video from a camera in the
> house). Nothing else. It is not a dashboard, a social app, or a product.
>
> **Device.** iPhone, portrait, one-handed, ~390 x 844 CSS pixels. Usually
> opened for ten seconds to answer "is she OK?". Added to the Home Screen,
> so it launches full-screen with no browser chrome and must respect the
> safe-area insets. Light and dark both matter and follow the phone; there
> is no in-app theme switch.
>
> **What the data actually is.** Measured on Kona's collar on 2026-09-10 —
> every value below is a real reading (private ones blanked), not a guess.
> The app asks Fi every 5 minutes; the collar reports every ~3.
>
> *Who she is (from the Fi profile)*
> - name `Kona` · Labrador Retriever · female · born 15 Aug 2025, so **13
>   months old** · weight `15.42` (unit unverified, probably kg)
> - **her photo**, the one set in the Fi app — a real image URL, dated 7 Sep.
>   The avatar should be her, not an initial.
>
> *Rest — durations in seconds, verified*
> - Fi's day is midnight-to-midnight in the owner's timezone. The newest
>   daily window is **today, in progress**: its SLEEP is 0 until tonight and
>   its NAP climbs through the day (`1290` → `3146` s across one afternoon).
> - **Last night** is the window before it: yesterday `SLEEP 8796` (2.4 h),
>   `NAP 6971` (1.9 h).
> - This week `SLEEP 27202` (7.6 h), `NAP 40238` (11.2 h). Monthly is the
>   same because the collar went on 7 Sep.
> - Coming in the next data round: `overnightRestSummary` (Fi's own "last
>   night"), and `restFeed` — a history, so a week strip or sparkline is
>   realistic to design for.
>
> *Activity*
> - Today `3579` steps of a `28000` goal. This week `5370` of `196000`.
>   Monthly exists too.
> - Distance is **walk distance only** and she has not been logged on a walk
>   yet (today `0`, week `93`). Do not headline it. `stepFeed` and
>   `activityFeed` exist for history.
>
> *The collar itself*
> - battery `57`%, with an estimated `4.3 days` to empty
> - **on the charger right now** (`ConnectedToBase`); when she is out it
>   reports cellular `signalStrengthPercent` instead
> - LED colour `White`, LED currently off; lost-dog mode `NORMAL` (off)
> - next update expected in ~3 minutes — a "live" affordance is honest
>
> *Where she is*
> - status is either **resting** or **on a walk** (`OngoingRest` /
>   `OngoingWalk`). Resting since 7 Sep 18:51 — i.e. home.
> - a resting place name and a home location exist and arrive next round;
>   on a walk there is live distance and GPS with an error radius.
>
> *Does not exist — confirmed at every level, do not design for it*
> - no sleep quality, score, restfulness or wake-ups, on the pet or on any
>   rest summary
> - no barking, scratching, licking, eating or drinking counts
> - no heart rate, calories or active minutes
> - no geofences
>
> A rejection with no "did you mean" is how we know: Fi suggests a near
> match when one exists (`currentBehaviorSummary` → "did you mean
> `currentActivitySummary`?"), so silence is absence. If a layout only
> works with a 0-100 score, it does not work.
>
> *What is on screen today*, so you know the baseline: a passcode page; a
> Camera tab (live video, snapshot, and a pan/tilt pad only when the camera
> has motors); an Activity tab with a 12-hour ring for last night's sleep,
> then three tiles — steps today vs goal, naps so far today, steps this week
> — and one line of plain-language state (fresh / partial / stale /
> not-configured / couldn't-reach-Fi). Nothing on it is fake.
> **What the camera can do.** Live video and a still snapshot on every
> model — proven today on a fixed Logitech C270 over USB, on the phone. Pan, tilt and presets on the C210/C220/C225 only — the C120 is
> fixed and has no motors, and the same page has to render correctly for
> both, so any control has to survive being absent. Night vision, privacy
> mode, alarm, LED and motion settings exist on the local API but are not
> wired up yet. **Two-way talk is impossible** on every Tapo (TP-Link ships
> ONVIF Profile S; the audio backchannel is Profile T). Never draw a
> hold-to-talk button.
>
> **The visual direction already chosen** is "Meadow": a bone ground
> (`#F3F1EA`), a single moss-green ramp (`#DCE5D0` → `#27512A`), Bricolage
> Grotesque, one big tabular hero number, hairline rules instead of cards,
> and a pill toggle at the top for the two tabs. The dark variant is
> `#121611` with the ramp inverted. Keep this unless I say otherwise.
>
> **Output format — important.** Return **one self-contained `.html` file
> with the CSS inline in a `<style>` block**. No JSX, no React, no build
> step, no npm, no external JS libraries. The app is FastAPI + Jinja
> templates, so a plain HTML file maps onto it almost line for line, while
> JSX has to be translated by hand every round. Static markup with real
> sample values is exactly right; I will wire the data.
>
> **Also.** Motion is welcome but must sit inside
> `@media (prefers-reduced-motion: reduce)` guards. Assume no JavaScript
> unless you say why it is needed. Hit targets at least 44px.

---

## Why HTML and not React

Worth having written down, because it comes up.

React does not replace HTML — it generates it. Every React app ships HTML to
the browser; JSX is HTML-shaped syntax that a build step compiles into
JavaScript. The polish — type, spacing, colour, motion — is CSS, and CSS is
identical either way.

React earns its keep coordinating complex state across many components. This
app is three pages: a video frame, a dial and four numbers, and a passcode
box. Adding React would mean Node, npm and a bundler running on the
Raspberry Pi to render a dial.

The one real advantage a single-page app had was that it did not reload
between pages. That is now four lines of CSS:

```css
@view-transition { navigation: auto; }
```

Supported in Safari 18.2+ (iOS included) and Chrome 126+; every other
browser navigates as before. Named elements — the header, the current tab
pill, the camera frame — morph across the navigation instead of flashing.
It is in `web/static/app.css` today.

Verified rather than assumed: in Chromium 141 the `pageswap` and
`pagereveal` events both fire carrying a live `viewTransition`, in both
directions between the two tabs. The same check turned up one real caveat —
when the Google Fonts stylesheet cannot be reached, the *incoming* page
declines the transition, because a render-blocking stylesheet that never
arrives pushes first paint past the browser's deadline. The page still
navigates correctly, so it degrades the right way, but if the animation ever
seems to be missing, suspect the font CDN before suspecting the browser.
