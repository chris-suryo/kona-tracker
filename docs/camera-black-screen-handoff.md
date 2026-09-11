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
