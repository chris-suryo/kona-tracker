# Handoff to a ChatGPT session

Paste the block at the bottom into ChatGPT. This page is the long version it
can read from the repo. Written 2026-09-11, after the production-punchlist
pass. `docs/handoff.md` is the project; this is the brief for a visiting
assistant.

---

## The project in a paragraph

A private, passcode-gated, iPhone-first web app so Chris and his sister can
check on Kona, a one-year-old Labrador. Two tabs: **Activity** from her Fi
collar, **Camera** from a USB webcam in the house. Python, FastAPI, Jinja
templates, plain CSS, no build step, no JavaScript framework, no npm. It runs
on a Windows PC at home because the video originates there. `docs/design-brief.md`
explains why it is HTML and not React, and is the block to paste into a
design session.

## Where the code is

Branch **`claude/elegant-sagan-tit1xp`**, thirteen commits ahead of `main`,
CI green on ubuntu and windows, 219 tests. `main` is stale; work from the
branch. Chris merges.

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

## What is genuinely open, in the order that would help

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
   migration. Those need Chris's machine or his decisions.

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
- Do not use `location.reload()` to refresh: it tears down the MJPEG stream.
- Do not trust a forwarded-IP header from a non-loopback peer.
- A mock that answers any query tests the parser, not the query.

---

## The paste-able block

> I'm working on kona-tracker, a private iPhone-first web app that shows my
> dog Kona's Fi collar data and a live camera from my house. Python, FastAPI,
> Jinja templates, plain CSS, no build step, no JS framework.
>
> The code is on GitHub at chris-suryo/kona-tracker, branch
> `claude/elegant-sagan-tit1xp`. Read `docs/chatgpt-handoff.md` first, then
> `docs/handoff.md` and `CLAUDE.md`. The handoff doc lists constraints that
> will silently break things if you miss them, especially: the page sends a
> Content-Security-Policy so there can be no inline `<script>` and no `onclick`
> attributes, Leaflet is vendored and byte-pinned so no CDN links, page zoom
> is disabled deliberately, and no new dependencies without asking me.
>
> What I'd like from you is a visual and copy pass on the parts that were
> built for correctness and never got a design eye: the camera-health rows on
> the settings page, the map's empty state, the "Resting at Home" location
> card, and the pull-to-refresh indicator. Match the existing look rather than
> introducing a new one.
>
> Propose the changes before writing code, and keep `uv run pytest -q` and
> `uv run ruff check .` green. Work on a branch of your own and open a PR.
