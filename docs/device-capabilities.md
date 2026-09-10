# What the hardware can actually do

Written 2026-09-10, before the UI redesign, so nobody designs a control the
hardware cannot perform. The first design round drew pan controls and a
large "hold to talk" button. One of those is buildable on the right camera;
the other is not buildable on any Tapo. Everything below is either verified
against a source or explicitly marked unverified.

Sources: [pytapo](https://github.com/JurajNyiri/pytapo) and the
[Home Assistant Tapo integration](https://github.com/JurajNyiri/HomeAssistant-Tapo-Control)
built on it, which lists supported models;
[TP-Link's ONVIF FAQ](https://www.tapo.com/us/faq/724/) for the profile
level; [pyatv](https://pyatv.dev/) for Apple TV.

---

## 1. Camera models

Abilities are **data**, not assumptions in a template. `KONA_CAMERA_MODEL`
picks the set; `src/kona_tracker/camera/capabilities.py` holds it. A model
we do not recognise gets video only, because showing too few controls beats
offering one that silently fails.

| Control | C120 (fixed) | C210 / C220 / C225 (pan-tilt) |
|---|---|---|
| Live video (RTSP) | **Built** | **Built** |
| Still snapshot | **Built** | **Built** |
| Pan / tilt | **Impossible** — no motors | **Available**, not yet driven |
| Presets | **Impossible** | **Available**, not yet driven |
| Night vision on / off / auto | Available | Available |
| Privacy mode (lens blind) | Available | Available |
| Alarm / siren | Available | Available |
| LED indicator | Available | Available |
| Motion detection + sensitivity | Available | Available |
| Mic mute, speaker volume | Available | Available |
| SD recording, file download | Available | Available |
| Reboot, time sync | Available | Available |
| **Live two-way talk** | **No** | **No** |

"Available" means the local API exposes it and we have not written the
driver yet. "Built" means it works today.

### Why two-way talk is off on every Tapo

TP-Link implements **ONVIF Profile S**. The audio backchannel that carries
your voice to the camera is **Profile T**. Talking to Kona works in the
Tapo app over their proprietary protocol; it does not work through
standards, so it cannot work through ours.

Getting it would mean a different class of camera (Dahua, Hikvision, some
Reolink) *and* replacing our whole video path with go2rtc and WebRTC.
Deliberately dropped. `Capabilities.talk` is `False` everywhere and a test
pins it, so it cannot be switched on hopefully — only by someone who proved
it against real hardware.

### The plan across two cameras

The C120 already ordered is not wasted: fixed cameras make good second
angles. A C225 added later becomes the one you steer. The app renders each
correctly from the same code, so both can be plugged in and compared.

### Setup gotcha

Recent firmware requires **Third-Party Compatibility** switched on in the
Tapo app before the camera account works at all. Both RTSP and the control
API fail without it. It is step 2 in `docs/first-run.md`.

---

## 2. Fi collar

**Built on shapes, not on evidence.** The Activity tab reads sleep, naps,
steps, step goal and distance, and those queries are exercised end to end
against `httpx.MockTransport` — but no real Fi response has ever been seen.
The fixtures come from pytryfi's source, not from Kona's collar.

Two things are unresolved until somebody runs `kona probe` for real:

- **Units.** Durations are assumed to be seconds. `hours_from_duration()`
  returns `None` outside 0-24 hours, so a unit change shows the raw figure
  marked raw rather than a confident wrong total. Distance is printed raw
  and labelled raw, because nothing says it is metres.
- **Sleep quality and behaviours.** A quality score, and barking,
  scratching, eating and drinking counts, remain unconfirmed. Nothing on
  the page may assume one exists.

The probe writes `probe-out/summary.md`, which answers both.

---

## 3. Apple TV and general home automation

**Technically possible.** pyatv is mature, covers power, remote navigation,
app launching, now-playing and AirPlay, is pure Python, and works over the
local network. It would run on the same home server with no architectural
change.

**Recommended anyway: don't build it here.** This app is a focused thing
for two people about one dog. Home Assistant already solves home
automation, runs on the same Raspberry Pi, and ships integrations for both
this camera and Apple TV. Rebuilding that inside a dog app costs months and
makes it worse at its actual job.

The line: **camera control belongs here** because it is about watching
Kona. Everything else belongs in Home Assistant. If one surface is wanted
later, this app can read a few Home Assistant entities over its REST API —
a cheap bridge, not a rebuild.

Chris has parked this for a separate project.

---

## 4. What this means for the redesign

Controls that **may** appear, gated on the connected camera's capabilities:

- pan and tilt, plus presets — **pan-tilt models only**
- night vision (on / off / auto)
- privacy mode
- alarm
- LED indicator
- motion detection toggle and sensitivity
- speaker volume, microphone mute
- snapshot (already working)

Controls that **must not** appear:

- hold-to-talk — impossible on Tapo, on any model
- pan/tilt on a fixed camera — the page must ask, never assume

Still undecided, pending the probe: everything on the Activity tab.
