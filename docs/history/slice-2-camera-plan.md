# Slice 2 — app shell + live camera on the LAN (approved 2026-09-09)

## Goal

`uv run kona serve` on the Windows PC; an iPhone on the same Wi-Fi opens
`http://<pc-ip>:8000`, enters the shared passcode, taps Camera, sees a live
webcam stream. The Activity tab is a placeholder until the Fi collar arrives.
Same code moves to the Raspberry Pi unchanged.

## Why this shape

- **Priority flipped**: camera hardware arrives before the collar, so the
  Camera tab (originally a v0 placeholder) ships first.
- **MJPEG over FastAPI, pure Python.** One dependency (OpenCV) captures the
  webcam and encodes JPEG; the browser shows it with a plain `<img>`. Works
  in iPhone Safari with no JS codec negotiation, on Windows today and the Pi
  tomorrow. Latency ~200 ms on LAN, no audio. Good enough for "is Kona okay".
- **Not chosen (yet)**: go2rtc/WebRTC. Better over cellular and adds audio,
  but needs two extra binaries on Windows. That is the upgrade path for the
  remote-access slice.
- **One capture thread, many viewers.** A USB webcam opens once; the hub
  keeps the latest frame and every viewer reads it at its own pace. The
  thread starts on the first viewer and stops a few seconds after the last
  leaves, so the webcam LED goes off when nobody is watching.
- **Passcode gate**: `KONA_PASSCODE` compared in constant time; signed cookie
  (`KONA_SECRET`, itsdangerous) for 30 days; 5 failures per IP -> 30 s
  cooldown. Stream/snapshot routes answer 401 instead of redirecting because
  an `<img>` cannot follow a login page.
- **Fake camera** (`--fake-camera`): a deterministic test pattern so the app
  can be exercised with no hardware, in tests, CI, and cloud sessions.

## Ownership (this slice)

- Claude Code: everything under `src/kona_tracker/web/` and `camera/`, the
  `serve`/`cameras` CLI commands, tests, docs. Did NOT touch `fi/` or
  `probe/` (Astro's PR #1 area).
- Astro (local): PR #1 probe fixes; running `kona serve` on real hardware.
- Claude Design: replaces `web/templates/*.html` and `web/static/app.css`;
  Python does not change.
- Chris: hardware, `.env`, merges.

## Known limits (deliberate)

- LAN only, plain HTTP: the passcode is unencrypted on home Wi-Fi. Fine for
  v0; HTTPS/Tailscale is the remote-access slice.
- Windows Firewall prompts on first run; allow on private networks.
- Verified in the sandbox with the fake camera and a live uvicorn + curl
  run (login, gate, snapshot, 20 frames in 2 s). NOT yet verified with a
  real webcam: that is Chris's/Astro's step.
