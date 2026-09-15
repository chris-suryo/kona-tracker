# Overnight report, 2026-09-11

For Chris, on the phone, before touching the PC. Read with
`docs/screenshots/history/2026-09-11/` open. The queue and its reasoning are in
`docs/history/overnight-brief.md`; this is what happened to it.

Starting state verified before anything was touched: branch
`claude/elegant-sagan-tit1xp` at `1ea0b99`, 234 passed, ruff clean, CI run
81 green on both runners. Ending state: 260 passed, ruff clean, five
commits plus this report, all on the same branch. `/security-review` ran on
the diff and reported no findings above its threshold.

**Correction, the morning after.** That "260 passed" was true in the
sandbox and in CI and still failed on Chris's PC: one new test asserted a
literal clock face, which is really an assertion about the machine's
timezone. Both CI runners are UTC, so the matrix could not catch it. Fixed
in the commit after this report and re-run across eight zones from UTC-11
to UTC+14; 262 pass. The lesson is the one already in this repo, missed
one file away: `tests/test_fi_service.py` had solved it by pinning Kona's
zone and computing the expectation with `.astimezone()`.

---

## Built

Each is one commit; the commit message carries the why.

1. **The goal ring goes past 100%.** `views.step_ring()` returns the true
   percentage for the label, the first lap capped at 100, and the surplus as
   a second lap capped at 100, drawn in `--t3` over the `--t5` base. The
   Jinja maths that re-parsed "18,240" is gone. Screenshot: 42,000 of 28,000
   reads 150% with a half lap of the brighter green over the full ring.

2. **Hours and minutes everywhere.** `views.duration_parts()` gives
   `[("8","h"),("30","m")]`; 1,290 s reads `22m`; zero reads `0m`. The
   big-figure, small-unit look is kept through a Jinja macro. A figure that
   is not credible as seconds still shows as raw, as before.

3. **The bottom row and the text under it.** During the seven-day cutoff
   the row now says **"Available 17 Sep"** with "weekly steps" beside it,
   the date being `KONA_FI_DATA_START` plus seven days. The midnight
   paragraph only appears while the cutoff or a pending first night makes it
   worth saying; on an ordinary day there is nothing under the freshness
   line. And "Right now / Resting" now carries **"since 10:42"** from
   `activity_since`, a field Fi already sent. On a walk it reads "420 m so
   far · since 10:42". No new Fi fields were requested.

   *Product judgement made here, reversible:* the row states a date rather
   than a monthly figure or a distance. Distance is still untrusted (0 on a
   3,383-step day) and the monthly stat would be withheld by the same cutoff.
   If you would rather see something about Kona there permanently, say what.

4. **The profile page.** No header on `/settings` (`tab=None` in `app.py`,
   one line to revert), so: one avatar, no unselected tab bar, no "Profile"
   eyebrow, and a "‹ Activity" back link at the top instead of "Back to
   Activity" at the bottom. "usb index 0" became "Webcam on this computer"
   via `Settings.camera_description()`; the console wording is unchanged.
   The Preview chevron is the same SVG as the back link, centred on the row.
   The Collar group (battery, connection) stays: with the header gone it no
   longer repeats anything on the same screen. Chosen over a third tab
   because the toggle's design is two destinations.

5. **Camera: the idle close and the reopen are now slow on purpose.**
   `KONA_CAMERA_IDLE_SECONDS` (default **120**, was a hard-coded 5 that
   `create_app` never set) and `KONA_CAMERA_REOPEN_SECONDS` (default **2**),
   a cooldown the hub observes between releasing a source and opening the
   next, whatever caused the release. While waiting, the status reads
   "connecting", not a failure. Tests with the fake source prove the timings.
   Cost: the webcam LED stays on for two minutes after you leave.

   **This is not a fix for the black screen and is not claimed as one.** No
   sandbox can reach the webcam. It removes a way for the app to manufacture
   the wedged-USB fault itself; only your hardware can say whether that was
   the cause.

6. **The Node browser test says at the top that CI does not run it.**

7. **Screenshots** in `docs/screenshots/history/2026-09-11/`: Activity (light,
   dark), the sample preview, the profile page (light, dark), and the
   dark-map prototype. Real Chromium at 390 px against the real app. Two
   gaps: the Bricolage font could not load in the sandbox, so these show the
   system fallback, and `tile.openstreetmap.org` is blocked, so the map area
   is grey.

## Proposed only

- **Dark map.** `docs/screenshots/history/2026-09-11/dark-map-prototype.png` shows a
  synthetic tile in OpenStreetMap's palette under today's dark filter and
  under `invert(1) hue-rotate(180deg) brightness(.95) contrast(.9)
  saturate(.6)`. On the synthetic tile it reads as a proper dark basemap:
  water dark blue, park dark green, labels light. Not shipped, because the
  brief said screenshot it rather than assume, and only a real tile can
  settle it. To try it on the PC, replace the `filter` line inside the
  `@media (prefers-color-scheme: dark)` block under `.map .leaflet-tile-pane`
  in `app.css`, load the page in dark mode, and look.
- **Node in CI** for `tests/browser_runtime.test.cjs`: a dependency decision
  (Node on both runners). Left as the file's header comment.
- **Other UI observations**, offered as conversation, not built: the
  freshness dots in light mode read as pale pills when caught mid-pulse; the
  "Last report 05:07" time on the location card and the "since 02:58" line
  are two different clocks for the same collar and may want one wording;
  the profile page's "Sign out on this phone" is the only control on a page
  that is otherwise all reading, so it may belong lower or smaller.

## Waiting on you

1. **The camera experiment**, unchanged from the brief: `git pull`, restart
   `kona serve`, open Camera, leave it five minutes. If good, switch to
   Activity, wait thirty seconds, return. Black on return but fine when left
   alone would confirm the close-and-reopen hypothesis; with the new
   defaults the thirty-second absence should no longer close the device at
   all, so also try a five-minute absence.
2. **What the badge says when it is black:** LIVE, CHECK CAMERA, STALE or
   OFFLINE, and whether the picture carries "NO SIGNAL" text.
3. **Probe round 5** for the `whereabouts` line, from the brief.
4. Whether to add Node to CI.
5. Whether the bottom-row choice (a date, not a Kona fact) is right.
6. Whether the dark-map filter looks right on real tiles.

## Branch housekeeping

Everything is on `claude/elegant-sagan-tit1xp`, as asked. This session's
harness also created `claude/elegant-sagan-tit1xp-wu5zdk` and requires a
push there; it is kept identical to the trunk and is safe to delete along
with the other merged branches (this sandbox cannot delete remote refs).
