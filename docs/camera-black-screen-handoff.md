# The black camera: handoff to a local session, 2026-09-11

Written for a Claude Code or Codex session running **on Chris's Windows PC**,
in `C:\Users\harim\kona-tracker`. A cloud session cannot finish this: it
cannot run PowerShell, cannot open the camera, and cannot look at the phone.
That limitation, not the bug, is what has made this slow.

Read `CLAUDE.md` first. It governs. Then this.

---

## The one-line summary

**The hardware is fine and the app shows black anyway.** `camera-test`
opens the same device with the same settings the server uses and gets real
pictures. `kona serve` shows a black rectangle. The fault is above the
camera source, in the hub or in the browser, and it has not been narrowed
past that.

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

`--fake-camera` deserves special mention: if the fake test pattern also
shows as a black rectangle, the bug is entirely in the browser and the real
camera is irrelevant. **That is the single cheapest experiment available and
it should probably be run first.**

## When it is fixed

A change to logic comes with a test. `tests/test_camera_hub.py` covers the
hub with a scripted source; `tests/browser_runtime.test.cjs` covers
`camera.js` with a fake DOM and is the right home for a `naturalWidth`
regression. CI runs ruff and pytest on ubuntu and windows; it does not run
the Node file. Commit in logical units with why-carrying messages, keep CI
green, and run `/wrap` at the end so the session lands in Otto.
