# Overnight brief, 2026-09-11

For a fresh session picking this up while Chris sleeps. Read `CLAUDE.md`,
then this, then `docs/codex-polish-handoff.md` for what Codex just landed.
Everything below is either decided or explicitly marked as needing Chris.

---

## Starting state, verified

- Branch **`claude/elegant-sagan-tit1xp`**, commit **`91f7826`**, pushed.
- Codex's UI and reliability work is **already merged in** as a fast-forward,
  so this branch is the single trunk. PR #5 may still show open on GitHub
  because its commits arrived by fast-forward; its content is here.
- `uv run pytest -q` → **234 passed**. `uv run ruff check .` → clean. CI
  green on ubuntu and windows.
- Verify before starting. If any of that is not true, stop and say so.

Work on this branch. Do not open new long-lived branches: Chris asked twice
to keep it consolidated, and two assistants on two branches is what made
the last stretch awkward.

---

## The queue, in priority order

### 1. Chris's UI list, from the phone, in his words

He sent these with a screenshot of `/settings`. The first four are explicit
instructions; build them.

**a. The goal ring must go past 100% and overlap.** Today
`activity.html` clamps at 100, so the day she does half again her goal reads
as "exactly done". Proposed shape, already thought through:

- Move the percentage maths out of Jinja into `views.py`. It currently does
  `steps|replace(',', '')|float` on an already-formatted string, which is
  fragile, and `CLAUDE.md`'s own convention is that formatting lives in
  Python where it can be tested.
- A `step_ring(steps, goal)` returning `{"percent", "arc", "overflow"}`:
  `percent` is the true figure for the label, `arc` is the first lap capped
  at 100, `overflow` is the surplus capped at 100.
- The template draws a second `<circle class="over">` over the first when
  `overflow` is non-zero. Use `--t3` for it against the `--t5` base ring, so
  the second lap reads as brighter green over dark.
- A third lap would paint over the second and say nothing new, hence the cap.

**b. Naps in hours and minutes, "for everything".** `_hours()` renders
`8.5` with a small `h`. He wants `8h 30m`. Applies to naps **and** last
night. Suggested `duration_parts(seconds)` returning `[("8", "h"), ("30",
"m")]` rather than a string, so the template keeps its display-numeral look:
a big tabular figure with a small unit beside it. Note `1290` seconds should
read `22m`, and zero should read `0m` rather than a dash, because zero naps
is a thing we know rather than a thing we are missing.

**c. The bottom row and the text under it.** He said: *"just building a
clean baseline and all the text on the bottom: I need to put something there
that's more useful."* Two separate problems:

- The row says "Building a clean baseline / from today" during the seven-day
  cutoff. That is a status message about **our** data hygiene, not about
  Kona. Minimum fix: say when the weekly total becomes available, as a date
  he can act on. Better: put something about Kona there instead.
- The paragraph under it explains the midnight-to-midnight rule every single
  time. Show it only when something unusual is true, such as the cutoff
  being active or the first night still pending. Otherwise nothing.
- **Recommended addition, using data we already fetch and throw away:**
  `status.activity_since` gives when the current rest or walk began, so
  "Resting since 10:42" can sit next to "Right now / Resting" at the top,
  which currently says what she is doing but not for how long. Real data, no
  new query. `activity_from(data, "monthlyStat")` is also fetched and
  discarded today if a monthly figure is wanted.
- This is the one item where the right answer is a product judgement rather
  than a defect. Make the reversible choice, keep it small, and say clearly
  in the morning summary what was chosen so Chris can redirect cheaply.

**d. The profile page has redundant things.** From his screenshot, all real:

- Two avatars on one screen: the header one and the hero one.
- The "Profile" eyebrow above a huge "Kona" says nothing.
- "Back to Activity" duplicates the Activity tab directly above it.
- **The tab bar shows neither Activity nor Camera selected**, because
  `app.py` sets `tab = "settings"` and `base.html` highlights on an exact
  match. It reads as broken. Either mark it as a third destination or drop
  the bar on this page.
- `usb index 0` is developer language on a user-facing page.
- Battery appears both here and in the Activity header.
- The `›` chevron on the Preview row floats oddly far right.

Codex has just been in `settings.html`, so read it before editing.

**e. Other UI observations are welcome**, but propose rather than build.
He asked what else I would change; that is a conversation, not a mandate.

### 2. The camera, which is what he actually cares about

`kona serve` closes the webcam **five seconds** after the last viewer
leaves, and that timeout is hard-coded with no setting behind it
(`camera/hub.py`, `idle_stop_seconds: float = 5.0`; `create_app` never
passes it). So switching to Activity for six seconds closes the device, and
returning reopens it.

Put that beside the failure already recorded in
`docs/device-capabilities.md`: a wedged USB webcam opens cleanly, lights its
LED, and delivers nothing until it is physically replugged. Rapid
close-then-reopen is the classic way to provoke exactly that on Windows.
**Hypothesis: the app manufactures its own hardware fault every time he
changes tabs.** It fits every symptom he reported, including that refreshing
the Activity tab blacks out the camera.

Codex's pass bounded reader threads and fixed races around idle shutdown. It
did **not** change the close-and-reopen cycle itself.

Safe work now: make the idle timeout a setting, default it to something that
keeps a USB device open far longer, and add a cooldown so a close is always
followed by a pause before the next open. Tests with the fake camera.

**Do not claim this fixes his black screen.** It cannot be verified without
his hardware, and Codex's handoff says the same. Frame it as ready to test.

### 3. Smaller, all verified as real

- `tests/browser_runtime.test.cjs` is not run by CI. `ci.yml` runs only ruff
  and pytest, and Codex did not change it. Either wire it in, which means
  Node in CI and is a dependency question for Chris, or say plainly in the
  file that it is a manual test so nobody trusts it as a gate.
- A dark map was asked for. CARTO now needs an API key, so the no-dependency
  answer is a filter on the tile layer, roughly
  `invert(1) hue-rotate(180deg) brightness(.95) contrast(.9) saturate(.6)`,
  replacing the current dark-mode brightness filter. Prototype and screenshot
  it rather than assuming it looks good.

---

## Constraints that fail silently

Each one has a test, and each one has already cost real time.

- **No inline `<script>`, no `on*=` attributes.** The app sends
  `script-src 'self'`. An inline handler simply will not run in the browser.
- **No CDN links.** Leaflet is vendored and byte-pinned.
- **Page zoom is off deliberately**, at Chris's explicit request, knowing it
  is a WCAG 1.4.4 trade. The map is exempt. Do not "fix" either half.
- **The `prefers-reduced-motion` block must stay last in `app.css`.** A test
  slices the file from that media query to the end. Any new animation,
  including the ring's second lap, belongs inside it.
- **No new dependencies without asking.**
- **Never add an unverified field to a Fi GraphQL document.** A rejected
  field fails the whole document.

---

## What cannot be verified overnight, and must not be claimed

No sandbox can reach: the USB webcam, the Fi API, an iPhone, or the tunnel.
So the camera fix, anything about Fi's real responses, and any iOS Safari
behaviour are all "ready to test", never "fixed". Say which, explicitly, in
the morning summary.

What *can* be verified: pytest, ruff, and a real Chromium at phone width
against `kona serve --fake-camera`, which is how the pull-to-refresh and CSP
work was checked. Take screenshots of the UI changes so Chris can see them
before touching his PC.

---

## Still waiting on Chris, do not block on these

1. **The probe's `whereabouts` line.** Run from this branch,
   `uv run kona probe --out probe-out\round5`, then read `whereabouts` in
   `summary.md`. It settles whether Fi returns `... on OngoingRest
   { position }`, the field the map's resting tier depends on. Unmeasured
   since it was written. If Fi rejects it, the page already says so and
   falls back to the home pin, so nothing is broken either way.
2. **The camera experiment.** Open Camera, leave it five minutes. If good,
   switch to Activity, wait thirty seconds, return. Black on return but fine
   when left alone confirms the hypothesis above.
3. **What the badge says when it is black:** LIVE, CHECK CAMERA, STALE or
   OFFLINE, and whether the picture carries "NO SIGNAL" text. Those two
   answers separate a wedged device from a dead stream from a browser stall.
4. Whether to add Node to CI for the browser test.
5. Whether the bottom-row choice was the right one.

---

## Finishing

Commit in logical units with why-carrying messages. Keep CI green on both
platforms; check it, do not assume it. Run `/security-review` before the
work is merged. End with `/wrap` so the session lands in Otto, and leave a
short morning summary saying what was built, what was only proposed, and
what is waiting on him.
