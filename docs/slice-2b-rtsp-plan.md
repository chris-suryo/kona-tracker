# Slice 2b — RTSP network camera, reconnect, honest "live" (approved 2026-09-10)

## Goal

`KONA_CAMERA_SOURCE=rtsp` points the app at a network camera (leading option:
TP-Link Tapo TC73). If the camera drops, viewers see a "NO SIGNAL" frame and a
status label within ~3 s, the server reconnects with backoff, and video
resumes with no reload. Credentials never appear in logs, errors, status
JSON, or terminal output.

## Why this shape

- **Frozen must never look live.** An MJPEG `<img>` shows the last frame
  forever when frames stop, which looks exactly like a calm dog. The hub now
  streams an embedded "NO SIGNAL" placeholder once per second whenever the
  latest frame is older than `KONA_STALE_SECONDS`, so the picture visibly
  changes even with JavaScript off. `/status.json` and a small script on the
  camera page add the words (Live / Stale N s / Disconnected).
- **Supervisor over disposable readers.** A TCP read inside FFmpeg can block
  forever and a thread stuck in C cannot be killed. So the hub thread is a
  supervisor: one reader thread per connection "generation"; no frame for
  `KONA_HANG_SECONDS` means the reader is abandoned (it releases the camera
  when it eventually returns) and a new generation starts after backoff
  (1 s doubling to 30 s, reset on the first good frame). Reconnecting stops
  when nobody is watching.
- **RTSP through OpenCV's bundled FFmpeg.** No new dependency. TCP transport
  and a socket timeout are set via `OPENCV_FFMPEG_CAPTURE_OPTIONS` before
  the first import; FFmpeg logging is silenced so it never prints a
  connection string.
- **Credentials.** Separate `.env` keys (`KONA_RTSP_USER/PASSWORD`); a URL
  that embeds them is tolerated but split apart. `redact_url()` runs on every
  error string, `repr()`, status field, and CLI line. `Settings.__repr__`
  masks everything.

## Verified here (simulated streams; no RTSP server exists in the sandbox)

- 39 tests: scripted sources covering dropped reads, exceptions mid-stream,
  a hung read that is abandoned and replaced, stale placeholder then real
  frame, status transitions, backoff growth/reset, idle stop, stop() ending
  streams, redaction round-trips with special characters.
- The real OpenCV+FFmpeg *network* path: `RtspSource` opened an in-process
  HTTP MJPEG server by URL and decoded real frames (32x32). Open failures
  against a closed port come back redacted.
- Live uvicorn with a source that dies after 3 s and is refused for 4 s:
  the stream showed live -> disconnected placeholders -> stale -> live, the
  status reported 3 reconnects with a redacted error, and the password
  appeared nowhere in the stream or the log.

## NOT verified (Astro, Windows PC, real Tapo)

RTSP handshake and auth against the camera, H.264 decode, actual fps.
First command: `uv run kona camera-test`.

## Tapo TC73 setup (from TP-Link docs; confirm on the device)

1. In the Tapo app: Advanced Settings > Camera Account: create a username
   and password. This is what RTSP uses, not the TP-Link cloud login.
2. Give the camera a DHCP reservation in the router so its IP is stable.
3. `.env`: `KONA_CAMERA_SOURCE=rtsp`, `KONA_RTSP_URL=rtsp://<ip>:554/stream1`
   (`/stream2` for the lighter SD stream), `KONA_RTSP_USER`, `KONA_RTSP_PASSWORD`.
4. `uv run kona camera-test` -> expect "10 frames in ~1 s, ~1920x1080".
5. `uv run kona serve`; iPhone -> Camera. Unplug the camera for 20 s and
   plug it back: expect Disconnected, then Live, without reloading.

## Known limits (deliberate)

- An abandoned reader thread lingers until FFmpeg's timeout fires; hours of
  flapping could accumulate a few. Bounded by the backoff cap.
- Placeholder is a fixed image; the "Stale N s" number lives in the label.
- Templates/CSS touched only in the status script and two `.dot` classes;
  Claude Design owns the look of those states.
