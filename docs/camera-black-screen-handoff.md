# The camera on the phone: where this stands, 2026-09-11

This file started as a handoff for a black camera. Two separate bugs have
been found and one of them is fixed. It is now the record of the whole
thread. The platform facts live in `docs/device-capabilities.md` §2c; this
is the story and the open decision.

---

## Bug 1: the slow reveal. Fixed and merged.

**Symptom:** the Camera tab showed a black rectangle with CONNECTING for
around two seconds before the picture appeared, in any browser.

**Root cause, measured on `--fake-camera` rather than reasoned about:** the
first frame decoded at 69 ms and the server reported `live` at 40 ms, but
the reveal decision lived only inside `poll()`, which runs every 2000 ms. So
the picture stayed hidden until the 2054 ms tick. All three reveal
conditions were true at 69 ms. The bottleneck was purely the poll cadence.

**Fix:** the `<img>` `load` handler now performs the same reveal check,
gated on the last `/status.json` having reported `live`, so a decoded
NO SIGNAL placeholder is never shown as a live picture. Re-measured at
27 ms. A CSS-only "Connecting…" overlay makes the remaining wait read as
working rather than dead, and correctly drops out on a hard failure so the
badge's own CHECK CAMERA or OFFLINE words stand.

On `main` as `7c93f17` and `7f53325`. CI green on both runners, 262 pytest,
12/12 in the Node browser harness including two new regressions.

**This was a real bug and it was worth fixing. It was never what Chris was
seeing on his phone.**

## Bug 2: the picture does not render in iOS Safari. Open.

**Symptom:** on the iPhone the Camera tab sits on "Connecting…"
indefinitely. The webcam LED stays on. `/healthz` reports `camera=live`
throughout. A desktop browser pointed at the same server at the same moment
shows the live picture.

**Measured with Safari Web Inspector attached from a Mac:**
`img.naturalWidth` is `0`, `img.complete` is `false`, and the
`/stream.mjpg` request stays open forever without completing.

`naturalWidth: 0` means no frame has ever decoded. The picture is not hidden
and it is not late. There is none.

**But it is intermittent, not absent.** The first theory written here was
that Safari cannot render `multipart/x-mixed-replace` at all; Chris then
reopened Safari and the picture came through. His words: Safari works
sometimes and sometimes hangs on Connecting forever; Chrome on the phone is
steadier but still not perfect.

So the format is supported and the fragility is in **holding one connection
open for minutes on a phone**. The leading candidate is connection
exhaustion: a stream occupies one of roughly six per-host connections for
its whole life, and every `reload()` starts a fresh one, so a tab switch or
a sleep that does not tear down the old stream leaks a slot until nothing
can start. Once stuck it stays stuck, which matches the symptom.

Full evidence table, the alternatives, and the one check that separates them
are in `docs/device-capabilities.md` §2c. Read that before acting.

## Bug 2, diagnosed: the server accumulates abandoned streams

Four observations from Chris's iPhone, in sequence, settle it.

1. **Restarting `kona serve` fixes it instantly.** The picture appears
   immediately on a phone that had been stuck on "Connecting…".
2. **One tab switch breaks it again.** Camera, then Activity, then back to
   Camera, and it hangs. A single round trip is enough.
3. **It recovers on its own.** Opening the page in Chrome and returning to
   Safari brings Safari back, as does simply waiting.
4. **The server is healthy the entire time.** `/status.json` during a hang:
   `state: live`, `last_frame_age: 0.04`, `reconnects: 0`. Status polls
   answer normally; only `/stream.mjpg` delivers nothing.

A server restart curing it is the decisive one. **This is our bug, not
Safari's.** Safari is merely worse at tearing down a held connection than
Chrome is, which is why Chrome looks steadier.

### The mechanism

When a viewer goes away without a clean close — a force-closed iOS app, a
navigation, a page frozen into Safari's back/forward cache — the server does
not learn it. The `mjpeg()` generator stays alive writing frames into a
socket nobody reads.

Each of those waits on `loop.run_in_executor(None, ...)` in
`camera/hub.py`, which is **asyncio's default executor**, sized at roughly
`min(32, cpu_count + 4)`. Starlette's sync endpoints such as `/status.json`
run in **anyio's** threadpool instead, which defaults to 40. Two separate
pools, and only the stream one gets saturated.

That is exactly the reported signature: a live server, status polls
answering fine, and video that never arrives. It also explains the
self-healing. Frames written to a dead socket eventually fail, the generator
exits, a thread frees, and the next stream gets through.

Suspected aggravators on iOS, neither confirmed: Safari's back/forward cache
keeps a navigated-away page alive with its connection, and the app's
cross-document view transitions (`@view-transition { navigation: auto; }`)
hold the outgoing document during the animation. Both delay teardown, and
both are absent on desktop Chrome.

## Bug 2, fixed: built and verified in Chromium, not yet on the phone

Branch `claude/camera-snapshot-polling`, four commits, on top of `main`.
**Nothing here has run on an iPhone.** The acceptance list at the end of
this section is Chris's, and until it passes the honest status is "built".

**What changed.** The Camera tab no longer points an `<img>` at
`/stream.mjpg`. `camera.js` fetches `/snapshot.jpg?after=<seq>` one
request at a time; the server holds each request until a frame newer than
`seq` exists (at most `KONA_STALE_SECONDS`), so it is one request per
frame and self-pacing, and nothing outlives a request. Each response
carries `X-Kona-State`, `X-Kona-Seq`, `X-Kona-Error` and
`X-Kona-Frame-Age`, so the page reads the truth about a frame from the
same response as its pixels and no longer polls `/status.json` at all. A
frame is assigned to the `<img>` as an object URL only when the server
called it live; the placeholder is never shown as a picture. The CSP
`img-src` gains `blob:` for that, and `docs/chatgpt-handoff.md` now lists
it among the constraints that fail silently.

The MJPEG endpoint stays for curl and a desktop but is fenced: its waits
run on a hub-owned pool of `MAX_STREAMS` threads instead of asyncio's
shared default executor, a fifth concurrent stream gets a 503 naming
`/snapshot.jpg`, and `/status.json` reports `streams` and `viewers`.

**Three things a review caught before they shipped**, each with a test
that fails without it:

- Seq restarts at 0 with the process. A phone open across a `kona serve`
  restart would send `after=4000`, wait the whole timeout, and receive a
  placeholder labelled live, forever. `after_seq` is clamped to the current
  seq. Verified in Chromium: server killed under the page, OFFLINE, server
  back, LIVE again 821 ms later with no reload.
- The passcode gate answers a bodyless 401 for `/snapshot`, never a
  redirect, so cookie expiry needed its own branch to reach the login page
  rather than OFFLINE forever.
- Object URLs are revoked when the next frame is assigned, never on the
  `load` event, because a frame replaced before it decodes never fires
  `load` and a load-keyed revoke leaks on a phone left running overnight.

**Verified in the sandbox**, real Chromium at phone width against
`kona serve --fake-camera` (screenshots `camera-polling-*.png`):

| check | result |
|---|---|
| picture appears, badge LIVE, `<img>` src is `blob:` | yes |
| 3 s of polling | 45 requests, `after=` 0,1,2,3… consecutive, 1 in flight, 0 slow, 0 failed |
| server killed under the page | OFFLINE within a second |
| server restarted | LIVE 821 ms later, no reload |
| page hidden / shown | PAUSED / LIVE |
| CSP violations in the console | 0 |

`uv run pytest -q` 274 passed. `node --test tests/browser_runtime.test.cjs`
13 passed (CI does not run it). Ruff clean.

**Coupling to know about:** the client's abort deadline is 10 s and must
exceed `KONA_STALE_SECONDS` (default 3). Setting that to 10 or more would
make every poll on a quiet camera look like a failure. Documented in the
`camera.js` header rather than made a setting nobody has changed.

### Acceptance on the iPhone, Safari home-screen app AND Chrome

Server on the PC, watcher optional. "Fixed" means all eight without
touching the server.

1. Cold open: picture within about 2 s, "Connecting…" during the wait.
2. Camera → Activity → Camera, five times. Picture every time.
3. Lock the phone 30 s, unlock. Picture returns.
4. Force-close the app, reopen. Picture returns.
5. Restart `kona serve` with the page open. Picture returns by itself.
6. Ten-minute soak. Still live; `/status.json` shows `streams: 0` and
   `viewers` bouncing 0/1; nothing pending in Web Inspector.
7. Phone and a desktop browser at once. Both live; `opens` unchanged.
8. Tunnel on cellular, Wi-Fi off. Picture, lower rate, never stuck.

## The plan, as built

Three parts, in order of what actually gets a reliable picture on the phone.

**1. Poll `/snapshot.jpg` instead of holding an MJPEG stream.** Confirmed
viable: `fetch('/snapshot.jpg')` on Chris's iPhone Safari returned
`200 image/jpeg` with `X-Kona-State: live`. Two to three frames a second,
swapping the image, using the existing state header to decide live against
NO SIGNAL so the honesty rules are untouched. A short request cannot become
a zombie: it completes, frees its thread and its connection slot, and a
failure is retried 300 ms later. Every failure chased today, on both sides,
is one that polling does not have. The badge, the overlay, the capture
button and the reduced-motion rules all keep working as they do.

**2. Stop abandoned streams from accumulating.** Worth doing even if MJPEG
only ever serves desktop: give the stream waits a dedicated bounded pool
rather than the shared default executor, and drop a viewer that has not
taken a frame within a timeout, so a dead socket cannot hold a slot
indefinitely.

**3. Report viewers in `/status.json`.** It reports `readers` but not
connected viewers. Four zombies would have been visible in that JSON and
this would have been a ten-minute diagnosis. Approved by Chris.

Open decisions: whether the MJPEG path stays for desktop or is deleted, and
the poll rate. Recommendation is adaptive — fire the next request when the
previous picture decodes — and, eventually, one path rather than two for a
two-person household. The frame-rate section below removes the objection
that polling loses smoothness: this camera delivers 4 fps either way.

### Where it stood before the build, 2026-09-11 afternoon

Kept as the record of the decision. At this point nothing was built and
Chris chose to stop: the app worked on the phone in Chrome, Safari hung
after a tab switch, and the home-screen icon was stuck with Safari because
iOS lets no other engine install one. The build above followed the same
evening, after the plan was reviewed and approved.

## The frame rate ceiling: measured, and left alone

Three runs of `kona camera-test` on the C270, server stopped each time:

| resolution | light | fps | bytes/frame |
|---|---|---|---|
| 1280x720 | room | 4.0 | 84,876 |
| 640x480 | room | 7.0 | 34,541 |
| 1280x720 | bright | 4.0 | 81,764 |

**Two theories were proposed and both are wrong.** Lighting is not it: a
bright room gave exactly the same 4.0 fps. Nor is it simple USB saturation:
at 4 fps, 720p uncompressed is about 7.4 MB/s, comfortably under what USB
2.0 carries. Cutting to a third of the pixels bought only 1.75 times the
frames, not three, so pixel count is not the dominant cost either.

Fitting the two resolutions suggests roughly **90 ms of fixed cost per
frame** on top of pixel-proportional work, which caps the whole path near
11 fps before any pixels are touched. Candidates not investigated: the
DirectShow backend's per-read overhead, the camera negotiating a low native
rate, or our own per-frame work in `read_jpeg`.

**Deliberately left unresolved.** Four frames a second is adequate for
watching a dog sleep, the C270 is a temporary stand-in for the Tapo, and
Chris had spent a day on this camera already. Recorded so nobody re-derives
it. Do not propose the MJPG FOURCC change on the bandwidth argument: the
measurements above do not support it.

It also settles the design question that prompted the measurement. At 4 fps
there is no meaningful difference between holding a stream open and polling
snapshots, so the frame-rate objection to polling does not apply to this
hardware.

## What has been ruled out, with evidence

Do not re-litigate any of these.

- **The hardware.** `kona camera-test` opens the real C270 with the server's
  exact settings and returns ten frames at 1280x720 averaging 85 KB. A black
  frame compresses to a few KB.
- **The hub and the server.** One clean open, `opens=1, reconnects=0`, and
  108 seconds of continuous streaming with zero dropouts, verified on the
  real camera.
- **The network, the passcode and the LAN path.** A desktop browser on the
  same server shows the picture, and the phone's own `/status.json` polls
  succeed the whole time it is stuck.
- **Orphaned processes.** Checked. The `python` processes on that machine
  belong to an unrelated project and to Claude Desktop's extension.
- **The reveal logic.** Fixed, measured, and not the cause on the phone.

Earlier black pictures on the desktop were a genuinely wedged C270, cleared
by a physical replug. That failure is real, recurs, and is separate from
this one. The app reports it honestly as CHECK CAMERA.

## The decision waiting on Chris

If the theory holds, the fix is not a patch to `camera.js`. It is replacing
the streaming format.

**Proposal: poll `/snapshot.jpg` two or three times a second and swap the
image, instead of holding an MJPEG stream open.** The endpoint already
exists and already carries an honest `X-Kona-State` header.

- **Costs:** more bandwidth, more requests, a slightly choppier picture.
- **Buys:** it works on the only device that matters, it survives sleep,
  wake and Wi-Fi blips without bespoke recovery code, and it behaves the
  same through a tunnel and later with the Tapo.

For a phone-first app whose whole purpose is looking at a dog on an iPhone,
that trade is not close. Reliability outranks elegance here.

Two sub-decisions go with it, both Chris's:

1. Keep the MJPEG path for desktop, or delete it? Maintaining two streaming
   paths for one household is hard to justify, but deleting working code
   should be deliberate rather than incidental.
2. What frame rate? Two per second is plenty for a sleeping dog and keeps
   the load trivial.

**The intermittency strengthens this rather than weakening it.** If Safari
could never show the picture, polling would be a workaround for one
browser's gap. Because it shows the picture and then loses it, the problem
is the held connection itself, and every candidate cause — exhausted
connection slots, backgrounding, a Wi-Fi roam — is something a short
request retries automatically and a long-lived stream cannot.

**Before any of this is built**, confirm a single JPEG renders on that
phone, using the console checks in `device-capabilities.md` §2c. The whole
proposal rests on it. The one direct observation of `/snapshot.jpg` there
was an empty download, most likely an artifact of typing the URL rather
than a real failure, but it has not been confirmed either way.

## Lessons this thread has already paid for

- **Verify on the target device, not a convenient one.** Every camera fix
  was validated in desktop Chrome. The app is for an iPhone. Three rounds of
  honest, careful, measured verification all missed the actual problem
  because they ran on the wrong engine.
- **A cloud session cannot debug hardware or a phone.** Commands written for
  a platform that cannot be run are untested commands, and several were
  simply wrong. The local session plus Web Inspector found in minutes what
  hours of remote reasoning did not.
- **Diagnose before killing.** A confident theory about orphaned `kona
  serve` processes produced a kill list that was entirely other software,
  including Claude Desktop's own extension. Listing command lines first is
  what prevented it.
- **`camera-doctor` and `camera-test` must never run against a live
  server.** Two owners of one USB device is itself a cause of black frames,
  and the 120 second idle hold means a running server keeps the camera long
  after the last viewer leaves. This belongs in `first-run.md`.
