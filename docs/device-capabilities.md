# What the hardware can actually do

Written 2026-09-10, before the UI redesign, so nobody designs another
control the hardware cannot perform. The first design round drew pan
controls and a large "hold to talk" button; neither works on the camera we
bought. Everything below is either verified against a source or explicitly
marked unverified.

Sources: [pytapo](https://github.com/JurajNyiri/pytapo) and the
[Home Assistant Tapo integration](https://github.com/JurajNyiri/HomeAssistant-Tapo-Control)
built on it, which lists the C120 among supported models;
[pyatv](https://pyatv.dev/) for Apple TV.

---

## 1. Tapo C120 camera

Control speaks the camera's **local HTTPS API** using the same camera-account
credentials we already collect for the video stream. No cloud, no extra
secret to manage.

| Control | Status on the C120 |
|---|---|
| Live video (RTSP) | **Built.** `/stream1` HD, `/stream2` SD. |
| Still snapshot | **Built.** `/snapshot.jpg`. |
| Night vision on / off / auto | **Confirmed available.** Not built. |
| Privacy mode (lens blind) | **Confirmed available.** Not built. |
| Alarm / siren | **Confirmed available.** Not built. |
| LED indicator on/off | **Confirmed available.** Not built. |
| Motion detection mode + sensitivity | **Confirmed available.** Not built. |
| Microphone mute, speaker volume | **Confirmed available.** Not built. |
| SD-card recording, file download | **Confirmed available.** Not built. |
| Reboot, time sync | **Confirmed available.** Not built. |
| **Live two-way talk** | **Unverified.** Mute and volume are exposed; a live talk channel is not. Do not put a talk button in the UI until someone proves it end to end. |
| **Pan / tilt / presets / auto-track** | **Impossible.** The C120 is a fixed camera. These exist only on pan-tilt models such as the C210 and C225. |

### Setup gotcha

Recent firmware requires **Third-Party Compatibility** to be switched on in
the Tapo app before the camera account works at all. Both RTSP and the
control API fail without it. This is in `docs/first-run.md` step 4.

---

## 2. Fi collar

**Still unknown.** Nobody has run `kona probe` against a real account yet.
Whether Fi exposes a sleep-quality score, or only raw sleep and step
totals, decides what the Activity tab can honestly show. The probe writes
`probe-out/summary.md`; that file is the input to the Activity design and
nothing on that tab should be designed before it exists.

---

## 3. Apple TV and general home automation

**Technically possible.** pyatv is mature, covers power, remote navigation,
app launching, now-playing and AirPlay, is pure Python, and works over the
local network. It would run on the same home server as this app with no
architectural change.

**Recommended anyway: don't build it here.**

This app is a focused thing for two people about one dog. Apple TV control
and general home automation is a different product, and Home Assistant
already solves it, runs on the same Raspberry Pi, and ships integrations
for both this exact camera and Apple TV. Rebuilding that inside a dog app
costs months and makes it worse at its actual job.

The line that makes sense:

- **Camera control belongs here.** It is about watching Kona, it reuses
  credentials we already have, and it is a handful of switches.
- **Everything else belongs in Home Assistant.**

If one surface is wanted later, this app can read a few Home Assistant
entities over its REST API and show them on a tab. That is a cheap bridge,
not a rebuild, and the door stays open either way.

---

## 4. What this means for the redesign

Camera controls that **may** appear in the UI, because the hardware does
them:

- night vision (on / off / auto)
- privacy mode
- alarm
- LED indicator
- motion detection toggle and sensitivity
- speaker volume, microphone mute
- snapshot (already working)

Controls that **must not** appear:

- pan, tilt, zoom, presets, auto-track — the camera is fixed
- hold-to-talk — unproven; earn it with a working prototype first

Still undecided, pending the probe: everything on the Activity tab.
