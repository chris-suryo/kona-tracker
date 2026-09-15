# Changelog

Notable changes, newest first. This project follows no release cadence: it runs
continuously on one PC at home and ships when something is ready. The tags mark
states worth being able to return to.

## v0.1.0 — 2026-09-15

The first tagged state. Six days, 293 commits, 61 pull requests, CI green on
Ubuntu and Windows throughout.

### Activity, from a Fi collar

- `kona probe` discovers Fi's undocumented GraphQL API one speculative field at
  a time, reading each validation error to find the next one. Eleven rounds
  against a real collar produced the query set in `fi/queries.py`. Output is
  redacted before it is written.
- Steps against the daily goal with a ring that shows a second lap past 100%,
  sleep and naps as durations rather than decimals, today by the hour, last
  night's span, and a walk log with each route drawn on a map.
- Drag across any chart to read a bucket without a page load. The reading is
  cloned from server-rendered markup rather than rebuilt in JavaScript, so the
  two can never disagree.
- A full-screen live map that polls on its own clock, and a "Start walk" button
  that raises the polling cadence, because Fi takes two to three minutes to
  notice a walk has begun.
- Distances are labelled as outdoor distance. A zero says there was no outdoor
  distance rather than implying the dog did not move.
- Optional SQLite recorder for what each refresh saw. Fi's hourly detail is
  today-only and gone at midnight.

### Camera

- Tapo C120 over RTSP, downscaled server-side after decode so the phone gets a
  sharp frame without the full bitrate. USB webcams also supported.
- The page polls one frame at a time rather than holding an MJPEG stream. The
  reasoning, and the black-screen incident behind it, are in
  `docs/history/camera-black-screen-handoff.md`.
- Pinch and double-tap zoom. Night vision, privacy mode and the status light,
  driven through pytapo, drawn from the camera's answer rather than the press.
- Honest states: a frame is never shown as live unless the server called it
  live, and "stale" says how many seconds.

### Robot

- Hiwonder TurboPi behind a safety gateway on the Pi. The vendor stack holds a
  motor duty indefinitely, so the gateway zeroes the motors when commands stop
  arriving and the browser never chooses that window.
- Landscape drive mode: two joysticks, rotate buttons, a stop that answers 503
  rather than a comforting 200 when it did not land, and an alarm that survives
  rotating the phone upright.
- Drive commands travel over a WebSocket on the phone-to-server leg, which is
  the slow one. A task on the server refreshes the Pi on a steady clock, so
  cellular jitter cannot stutter the robot.
- A camera stick that aims and stays where it is put, front lights reachable
  over I2C while the robot's own software is down, and a legend the first time
  drive mode opens.

### The app itself

- One shared passcode, a signed cookie, and a lockout that counts per visitor
  behind a trusted proxy header.
- A Content-Security-Policy with no inline script or style. Leaflet and
  Bricolage Grotesque are vendored and sha256-pinned; after v0.1.0 no page
  makes a third-party request.
- Light and dark by choice or by phone, applied before first paint.
- The Activity page updates in place: only the sections whose markup changed
  are swapped, so the map keeps its pan and nothing re-animates.
- 629 tests. CI on Ubuntu and Windows, Python 3.11 and 3.12, because the app is
  served from a Windows PC and `%-d` raises there.

### Known limits

- Drive mode's strafe axes, battery headroom under sustained throttle, and
  camera quality over a cellular connection are unmeasured. See
  `docs/robot-measurements.md`.
- Screenshots are captured in Chromium; WebKit is not available in the
  environment that takes them. `docs/screenshots/README.md` lists what a
  capture does and does not represent.
- `docs/scaling-limits.md` holds the measured ceilings, including roughly 40
  simultaneous viewers.
