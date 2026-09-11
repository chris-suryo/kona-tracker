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

## The plan, awaiting approval

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

### Where it was stopped, 2026-09-11

Nothing above is built. The state Chris is leaving it in, deliberately:

- **The app works on the phone in Chrome.** That is a real workaround, not a
  compromise, and it is what to use meanwhile.
- **Safari hangs after a tab switch**, recovers on a wait, a server restart,
  or a detour through another browser.
- **The home-screen icon is stuck with Safari.** iOS only lets Safari
  install a web app to the home screen, so the workaround and the
  home-screen shortcut are mutually exclusive until this is fixed. Worth
  knowing before wondering why the icon still misbehaves.

This is an honest stopping point, not a finished one. The app is usable
every day via Chrome; the fix is specified and waiting for a session with a
browser and a phone.

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
