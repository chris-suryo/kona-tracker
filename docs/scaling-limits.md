# What this design cannot do yet

Written 2026-09-11, the day the camera stopped hanging. Not a punchlist —
punchlist items get done and deleted. This is the standing list of ceilings,
with the measurements behind them, so the next session finds them instead of
re-deriving them.

Two things make it worth keeping. Chris watches over **cellular** most of the
time, which is exactly the path the first limit below bites hardest. And this
may eventually become a real product rather than a two-person app, which is
what the last section is for.

---

## 1. Bandwidth — the one that bites today

**One viewer at the default 1280x720 costs roughly 1.2 GB per hour.**

Measured on the Logitech C270 with `uv run kona camera-test`, 2026-09-11:

```
10 frames in 2.5s (4.0 fps), 84876 bytes/frame avg, size 1280x720
```

84,876 bytes x 4 fps = **~340 KB/s**, about **2.7 Mbit/s**, about
**1.2 GB/hour**, per viewer. An earlier run the same week measured 3.7 fps
and ~88 KB/frame, which lands in the same place.

Three phones on the house Wi-Fi is nothing. **One phone through the
Cloudflare tunnel on cellular is not nothing**, and remote viewing is the
entire point of the tunnel. Nobody has measured what it actually costs on a
carrier connection yet; see "The measurement that settles this" below.

### Why a frame is 85 KB

JPEG quality is hard-coded at **80**, and not in a place anyone would find
it. It is a constructor default on both real sources —
`camera/source.py:228` (`OpenCVSource`) and `camera/source.py:286`
(`RtspSource`) — and **no caller ever passes it**: `web/app.py:138` builds
the source from index, width, height and fps only. There is no environment
variable. Reaching quality at all needs a code change.

Resolution and frame rate *are* configurable and have been all along —
`KONA_CAMERA_WIDTH`, `KONA_CAMERA_HEIGHT`, `KONA_CAMERA_FPS`
(`web/settings.py:213-215`) — but were undocumented until today, so in
practice the lever did not exist. They are in `.env.example` now.

One caution on the resolution lever, learned the hard way: dropping to
640x480 was measured to raise the frame rate about 1.75x. Fewer bytes per
frame, but more frames, so the saving on the wire is **smaller than the
pixel count suggests**. Measure bytes per second, not frame size.

### The measurement that settles this

Tunnel up, Wi-Fi off on the phone, five minutes on the Camera tab, then read
the phone's own data usage for Safari. That number decides whether a quality
knob is urgent or merely tidy. If it contradicts the 1.2 GB/hour estimate
above, **this document is wrong and should be corrected here**, not quietly
softened.

### The fix, when it is wanted

`KONA_CAMERA_QUALITY`, threaded from settings through `app.py:138` into the
source constructors that already accept it. Small, testable, and deliberately
not built today: the ask was to record the limit, not to spend the evening on
it.

---

## 2. About 40 simultaneous viewers, and the pool is shared

`/snapshot.jpg` is a **sync** `def` handler (`web/app.py:406`), so Starlette
runs it in anyio's default worker thread pool. Each poller waiting for a new
frame holds one of those threads for up to `stale_after`, which is 3 seconds
(`camera/hub.py:87`). anyio's default limiter is **40 threads**, verified:

```
anyio.to_thread.current_default_thread_limiter().total_tokens == 40
```

That pool is shared with every other sync endpoint — `/status.json`,
`/activity`, `/avatar.jpg`, `/login`. Past roughly 40 concurrent watchers,
new requests queue behind waiting pollers, and the symptom would be the whole
app going sluggish rather than the camera alone failing.

Irrelevant for a household; it is the first wall a product hits. Worth
recording as the **asymmetry** it is: when the MJPEG path was fenced it got
its own `ThreadPoolExecutor` with `MAX_STREAMS = 4` and a 503 past that
(`camera/hub.py:56,134`). The snapshot path got no equivalent, because
nothing there outlives a single request. The cap is real all the same, just
inherited rather than chosen.

---

## 3. The camera stays open the whole time anyone is watching

Every poll re-stamps the idle clock, so `KONA_CAMERA_IDLE_SECONDS` (120)
effectively only starts counting once **every** viewer's page is hidden. In
practice the webcam LED stays on continuously while the tab is open.

This is deliberate and should stay. Rapid close-and-reopen is precisely how
a USB webcam gets wedged — opens fine, LED on, delivers nothing until it is
physically replugged — which cost most of 2026-09-10 and 09-11. But it is a
behaviour change from the MJPEG era, and someone will eventually notice the
light and ask.

---

## 4. A visible but idle page polls forever

There is no inactivity gate. Backgrounding the page stops it dead — verified
in Chromium: the timer is cleared, the in-flight fetch aborted, the loop
guard set and the epoch bumped, so nothing re-arms — but a phone left awake
on the Camera tab keeps pulling frames, and keeps spending battery and (see
§1) data.

A "still watching?" pause after some minutes of no interaction is the obvious
answer. Not built.

---

## 5. The 4 fps ceiling is unexplained

Roughly 90 ms of fixed cost per frame, source unknown. Two theories were
tested and **both disproved** — do not retry them:

- **Lighting.** A brightly lit room gave an identical 4.0 fps.
- **USB bandwidth.** 640x480 gave only 1.75x for 3x fewer pixels, and
  7.4 MB/s is well inside USB 2.0.

Left unresolved on purpose: the Tapo C120 replaces this webcam, and the
number will change with it. Re-measure then rather than debugging a camera
that is on its way out.

---

## If this becomes a product

Naming these now so they are decisions rather than discoveries. None of them
is work today.

- **One shared encode instead of per-viewer JPEG.** Today every viewer is
  served the same already-encoded frame, which is why three devices work off
  one camera open — but the encode happens once at one quality for everyone.
  Different devices on different networks want different qualities, and that
  means an encode ladder, not a constant.
- **A real video transport.** Frame-at-a-time over HTTP is the right call for
  two people and a webcam, and the wrong one at scale. WebRTC or HLS would
  cut the bandwidth in §1 by roughly an order of magnitude, at the cost of
  every simplicity this app currently enjoys.
- **A relay instead of a home PC on a quick tunnel.** The tunnel URL changes
  on every restart, the PC has to stay awake, and one household's upload is
  the ceiling for everyone watching it.
- **Per-person accounts instead of one shared passcode.** One secret shared
  between two siblings is fine. It does not survive a third party, and it
  cannot be revoked for one person.
- **More than one pet and one household.** Every identifier in the app is
  currently singular — one camera, one collar, one timezone, one home
  position.

## See also

- `docs/remote-access.md` — the tunnel, and the two settings it needs.
- `docs/device-capabilities.md` §2c — the iOS Safari story and the camera
  measurements it came out of.
- `docs/history/camera-black-screen-handoff.md` — why the design is snapshot polling
  rather than MJPEG.
