# The black camera: handoff to a local session, 2026-09-11

Written for a Claude Code or Codex session running **on Chris's Windows PC**,
in `C:\Users\harim\kona-tracker`. A cloud session cannot finish this: it
cannot run PowerShell, cannot open the camera, and cannot look at the phone.
That limitation, not the bug, is what has made this slow.

Read `CLAUDE.md` first. It governs. Then this.

---

## The one-line summary

**The picture does arrive. It takes far too long, and while it is coming
the page is indistinguishable from a dead camera.** That is the bug to
chase first, and it may be the whole story.

Run on the phone against `kona serve --fake-camera`, which involves no
webcam at all: the badge said CONNECTING over a black rectangle for long
enough that Chris reported it as broken, and then it went LIVE on its own.
So the reveal path works. It is just slow enough that a person gives up
before it fires, and a person giving up is the failure.

The hardware is separately cleared: `camera-test` opens the real device
with the server's exact settings and gets real pictures.

**The pan and tilt pad appearing under the fake camera is correct, not a
stale build.** `default_control()` in `web/app.py` gives the fake source a
`FakeControl`, which is steerable on purpose so the control surface exists
before the hardware does. See `docs/device-capabilities.md`. A real C270
gets `NoControl` and no pad.

---

## What is proven, with the evidence

**The camera works.** Run at 2026-09-11 on the C270 at index 0, with no
server running:

```
uv run kona camera-test
Opening usb index 0 ...
Opened in 1.7s
10 frames in 2.5s (4.0 fps), 84876 bytes/frame avg, size 1280x720
```

That is decisive. `camera-test` uses `OpenCVSource` with the exact `.env`
settings the server uses, including 1280x720, and it raises on unusable
frames. 85 KB per frame is a photograph; a black frame compresses to a few
KB. So the device, driver, index, resolution and permissions are all good.

**Nothing else is holding the device.** The Windows process list was
checked. The only `python` processes on the machine belong to an unrelated
project (`E:\code\flow`) and to Claude Desktop's `windows-mcp` extension.
There were no orphaned `kona serve` processes. An earlier theory that
zombie servers were holding the camera was wrong and is dead.

**`flow-client` uses the microphone, not the camera.** The C270 has a
built-in microphone, so the USB composite device is partly in use by that
app. On Windows the audio and video endpoints are independent, so this is
unlikely to matter, but it has not been tested. Stopping `flow-client` and
retesting is a cheap way to rule it out.

**Frame rate note.** `camera-test` measured 4.0 fps against a configured 15.
Not obviously a fault, but worth remembering: `KONA_STALE_SECONDS` is 3, so
a camera this slow has less headroom than the settings imply.

---

## Start here: why is the first frame so slow to appear?

This is the highest-value thread, because it reproduces with
`--fake-camera` on the machine itself, with no hardware and no phone.

The image ships hidden. `web/templates/camera.html`:

```html
<img id="cam" class="unavailable" src="/stream.mjpg" alt="Live view of Kona">
```

`app.css` sets `.cam img.unavailable { visibility: hidden; }` over a `.cam`
background of `#0b0e0c`. **A hidden image is a black rectangle that looks
exactly like a dead camera.** The only code path that reveals it is in
`web/static/camera.js`:

```js
if (s.state === 'live' && !streamFailed && img.naturalWidth > 0) set('on', 'LIVE', '');
else if (s.state === 'live') set('stale', 'CONNECTING', 'Waiting for video on this phone…');
```

Three conditions, and `poll()` only re-evaluates every 2000 ms, so every
missed condition costs another two seconds of black. Worth measuring rather
than guessing:

- How long until `/status.json` first reports `live`? The hub starts on the
  first viewer, and `OpenCVSource` took 1.7 s just to open the real device.
- When does `img.naturalWidth` first become non-zero for a
  `multipart/x-mixed-replace` image? It stays 0 until a part has decoded.
  Check whether `visibility: hidden` delays the decode in the browser.
- Does an early `error` event latch `streamFailed` and hold the reveal
  until the next successful `reload()`?

Instrument it, do not reason about it: log a timestamp on the `<img>`
`load` event, on each poll result, and at the moment `unavailable` is
removed. Then the gap is a measurement instead of a theory.

Two design questions follow, and they are worth raising with Chris rather
than deciding alone:

- Should the picture be revealed as soon as frames decode, without waiting
  for a poll cycle to agree? The `load` event already fires on first frame.
- Should the black rectangle say something honest while it waits? The badge
  says CONNECTING, but the large black area says "broken" much louder, and
  the whole character of this project is that the page never implies a
  state it cannot back up.

---

## The split that has not been made, and the command that makes it

Everything now depends on one question: **does the server think it is
live?** `/healthz` answers it without a passcode and without the browser.

With `kona serve` running and the Camera tab open on the phone, in a second
PowerShell window at the repo root:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/healthz
```

### If it says `camera = live`

The camera, the source and the hub are all fine, and the black rectangle is
**browser-side**. That is the more likely branch given the evidence, and the
suspect is specific.

`web/templates/camera.html` ships the image already hidden:

```html
<img id="cam" class="unavailable" src="/stream.mjpg" alt="Live view of Kona">
```

`app.css` gives `.cam` a near-black background (`#0b0e0c`) and
`.cam img.unavailable { visibility: hidden; }`. So a hidden image is not a
missing picture, it is **a black box that looks exactly like a dead camera**.

`web/static/camera.js` reveals it from exactly one place:

```js
if (s.state === 'live' && !streamFailed && img.naturalWidth > 0) set('on', 'LIVE', '');
else if (s.state === 'live') set('stale', 'CONNECTING', 'Waiting for video on this phone…');
```

`img.naturalWidth` is 0 on an MJPEG `<img>` until a frame has actually been
decoded. If it stays 0 on iOS Safari, or if `streamFailed` is latched by an
early `error` event and never cleared, the picture is hidden forever while
the server is perfectly healthy. Read the failure paths around `reload()`,
`pause()` and `resume()` with that in mind.

**The caption under the picture names the branch.** It is the `#cap`
element, the small grey line. "Waiting for video on this phone…" is the
`naturalWidth` path. "No usable picture. Check the lens cover…" is the
server reporting `black_frame`. Ask Chris what it says, or read it yourself
in a browser on the PC at `http://127.0.0.1:8000/camera`.

### If it says `camera = disconnected` with `camera_error = black_frame`

Then the hub sees black frames from a device that `camera-test` gets
pictures from, moments apart. The difference between those two paths is
worth reading closely:

- `camera-test` opens `OpenCVSource` on the **main thread**, reads, closes.
- `camera/hub.py` opens the same source inside a **reader thread** under a
  supervisor thread, and re-opens it on failure with a backoff.

Look at `frame_is_unusable()` in `camera/source.py` (three consecutive flat
frames raise `CameraFrameError`), and at whether the very first frames after
an open are legitimately flat on this device. `camera-test` reads ten frames
and tolerates early misses differently.

---

## What was changed last night, and what it did not cover

Commit `a1a9c28` on `main`. Two settings, both in `camera/hub.py` and wired
through `web/settings.py`:

- `KONA_CAMERA_IDLE_SECONDS`, default **120**, was a hard-coded 5 that
  `create_app` never passed. How long the device stays open after the last
  viewer leaves.
- `KONA_CAMERA_REOPEN_SECONDS`, default **2**, a cooldown between releasing
  a source and opening the next one, whatever caused the release.

**The cooldown is in-process only.** It does nothing about a close in one
process followed by an open in another. So `camera-doctor` (or
`camera-test`) immediately followed by `kona serve` still performs the exact
close-then-open that wedges a USB webcam. If that turns out to matter, the
fix is not more cooldown, it is telling people not to chain those commands,
and saying so in `docs/first-run.md`.

To get the old behaviour back for an A/B, put this in `.env`, restart, and
delete it afterwards:

```
KONA_CAMERA_IDLE_SECONDS=5
KONA_CAMERA_REOPEN_SECONDS=0
```

---

## Do not retry these

Each one was tried and disproved. Repeating them costs an hour.

- **Do not blame 1280x720.** `camera-test` succeeds at exactly that size.
- **Do not blame the hardware or the driver** without new evidence.
  `camera-test` cleared them on 2026-09-11.
- **Do not hunt for orphaned `kona serve` processes.** There were none. The
  `python` processes on this machine belong to `E:\code\flow` and to Claude
  Desktop's `windows-mcp` extension, and killing them would break unrelated
  software.
- **Do not run `camera-doctor` as the first step.** It probes five indexes
  across two backends, blocks for seconds per empty index, and its own
  open-then-close may wedge the device before the server runs. If it is
  needed, `--indexes 1` and a pause afterwards.
- **Do not conclude "wedged USB" from a black picture alone.** The
  distinguishing measurement is pixel standard deviation, not brightness. A
  dark room has a low mean and a spread well above zero; a wedged device
  reads 0.00 for both.

---

## Constraints that fail silently

These have tests pinning them and will not announce themselves in a browser.

- **No inline `<script>` and no `on*=` attributes.** The app sends
  `script-src 'self'`. An inline handler simply will not run.
- **No CDN links.** Leaflet is vendored and byte-pinned by a test.
- **The `prefers-reduced-motion` block must stay last in `app.css`.** A test
  slices the file from that media query to the end.
- **Page zoom is off deliberately**, at Chris's explicit request, knowing it
  is a WCAG 1.4.4 trade. The map is exempt. Do not "fix" either half.
- **No new dependencies without asking.**
- **Never add an unverified field to a Fi GraphQL document.** A rejected
  field fails the whole document.

## Commands

PowerShell, at `C:\Users\harim\kona-tracker`:

```powershell
uv run pytest -q                 # 262 tests; must stay green
uv run ruff check .
uv run ruff format --check .
uv run kona serve                # http://0.0.0.0:8000
uv run kona serve --fake-camera  # no hardware; proves the browser layer alone
uv run kona camera-test          # one open, the server's exact settings
node --test tests/browser_runtime.test.cjs   # camera.js logic; CI does NOT run this
```

`--fake-camera` is the one to work with. It reproduces the slow reveal with
no hardware, on the PC, in a desktop browser with devtools open. Get the
first frame to appear quickly there and the real camera becomes a much
smaller question.

## When it is fixed

A change to logic comes with a test. `tests/test_camera_hub.py` covers the
hub with a scripted source; `tests/browser_runtime.test.cjs` covers
`camera.js` with a fake DOM and is the right home for a `naturalWidth`
regression. CI runs ruff and pytest on ubuntu and windows; it does not run
the Node file. Commit in logical units with why-carrying messages, keep CI
green, and run `/wrap` at the end so the session lands in Otto.
