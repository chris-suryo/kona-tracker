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
> **What the data actually is.** Measured against the real collar on
> 2026-09-10, not assumed:
>
> - Steps and a step goal, for today / this week / this month. **Confirmed
>   working** (3,383 of 28,000 on the first real run).
> - Sleep duration and nap duration, for a window Fi groups them into. The
>   window is a calendar day — it is **not** the moment she fell asleep, so
>   nothing may be labelled "fell asleep at 10:40pm".
> - Distance is returned but **is not trustworthy**: 0 for the day against
>   3,383 steps. Do not put it in a layout as a headline number.
>
> There is **no sleep-quality score** and **no behaviour counts** — not
> barking, scratching, licking, eating or drinking — and no heart rate.
> That is confirmed, not assumed: Fi's API rejects every one of those field
> names, and it offers a "did you mean" when something is close, so silence
> means absence. Do not design a component that needs one. If a layout only
> works with a 0-100 score, it does not work.
>
> Likely available but not yet verified: her photo from the Fi app, the area
> she is in, whether she is out on a walk, and collar charge/signal. Ask
> before building on these.
>
> **What the camera can do.** Live video and a still snapshot on every
> model. Pan, tilt and presets on the C210/C220/C225 only — the C120 is
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
