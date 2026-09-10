# kona-tracker

Private, passcode-gated, iPhone-first web app for Chris and their sister to
check on Kona (dog). Activity tab from her Fi collar (Whoop later); Camera tab
once the hardware exists.

---
kit: 3e06b156508b881bef26345c0bb7a63c90db4824 · stamped by dos new
---

## Status (2026-09-10, end of chapter 1)

Everything below lives on branch `claude/nice-bohr-6tnfn0`, PR'd to `main`
for Chris to merge. Astro's PR #1 is absorbed (with the regex fix).

- **Slice 1:** `kona probe` dumps every Fi API field, redacted. Unverified
  against Fi (collar not yet here). `docs/slice-1-probe-plan.md`.
- **Slice 2 + 2b:** `kona serve` = passcode gate, live camera (USB or RTSP,
  reconnects, "NO SIGNAL" when stale), Activity placeholder. Verified with
  simulated cameras only. `docs/slice-2-camera-plan.md`, `docs/slice-2b-rtsp-plan.md`.
- **Meadow shell:** Claude Design round 3 implemented in templates/CSS;
  light + dark. Screenshots verified with a fake camera.
- **Hardware:** Tapo C120 ordered (RTSP/ONVIF, fits as-is). Blink Mini 2K+
  and Wyze v4 do NOT work without unofficial bridges. Fi collar arrives
  2026-09-11. Raspberry Pi 5 kit bought; not set up.

**next (chapter 2):** Chris follows `docs/first-run.md`.

*Anywhere, any machine with internet:*
1. Merge PR #2 so `main` stops being an empty scaffold.
2. See the app: `uv run kona serve --fake-camera`, open `localhost:8000`.
3. Once the collar is paired in the Fi app: `FI_*` in `.env`,
   `uv run kona probe`, share `probe-out/summary.md`. This is what unblocks
   slice 3 — it says which Fi fields actually exist.

*At home only (the camera stream originates there):*
4. Tapo C120 on the Wi-Fi + camera account -> `uv run kona camera-test` ->
   `uv run kona serve` -> iPhone on the same Wi-Fi.

Then `/plan` slice 3: Activity hero on the confirmed Fi fields, and
Pi + Tailscale for remote viewing.

## Ownership

| Who | Owns |
|---|---|
| Claude Code (cloud) | code, tests, CI, docs. Cannot see hardware, LAN, or the Fi API. |
| Chris | runs the local steps (`docs/first-run.md`), hardware, `.env`, merges. |
| Astro (ChatGPT) | paused (out of credit). Its PR #1 is absorbed. |
| Claude Design | Meadow direction chosen; further visual passes edit `web/templates` + `static/app.css`. |

Shared only via GitHub. One branch per assistant.

## v0 scope

In: Fi login, rest/sleep as hero metric, Field visual direction (dark mode
primary, single-hue teal ramp, big tabular hero number, hairlines not cards),
one shared passcode.

In (moved up because the hardware came first): Camera tab, live over LAN.

Not in v0: Whoop, behavior metrics (barking/scratching/eating/drinking:
unconfirmed in the API), remote camera access, HTTPS, per-user accounts.

## Stack (shape: web app, minimal stamp; decided by /grill 2026-09-09)

Python 3.11+, uv, typer, httpx. Web: FastAPI + Jinja (htmx not needed yet),
uvicorn, itsdangerous (signed cookie), opencv-python-headless (webcam, lazy
import). Tests: pytest with `httpx.MockTransport` for Fi and a fake camera
source for the web app; no live Fi calls or hardware in CI.
Lint/format: ruff. CI: ubuntu + windows matrix.

Hosting: the camera server must live at home (the stream originates there):
Windows PC now, Raspberry Pi 5 next. Remote access (Tailscale) and where the
rest lives (Chris mentioned Vercel + Supabase to Astro) are still open; the
app is env-var configured only, so nothing locks that in.

## Commands (PowerShell or Mac Terminal, repo root; plain-language walkthrough in `docs/first-run.md`)

```powershell
uv sync                         # install (first run pulls the OpenCV wheel, ~50 MB)
uv run pytest -q                # tests
uv run ruff check . ; uv run ruff format .
Copy-Item .env.example .env     # then fill KONA_PASSCODE, camera keys (and FI_* when the collar arrives)
uv run kona cameras             # usb only: which webcam indexes open -> KONA_CAMERA_INDEX
uv run kona camera-test         # open the configured camera once: size, fps, redacted URL, exact error
uv run kona serve               # http://0.0.0.0:8000 ; allow the Windows Firewall prompt
uv run kona serve --fake-camera # no camera needed; test pattern
uv run kona probe               # Fi API discovery -> probe-out\summary.md
ipconfig                        # IPv4 of the PC; iPhone opens http://<that-ip>:8000
```

`.env` and `probe-out/` are gitignored. Never commit either.

## Locations

- `src/kona_tracker/fi/` — Fi API client + GraphQL documents
- `src/kona_tracker/probe/` — probe orchestration, redaction, schema scan
- `src/kona_tracker/camera/` — sources (USB, RTSP, fake), credential redaction, placeholder frame, the supervisor/reader hub
- `src/kona_tracker/web/` — FastAPI app, passcode auth, settings, templates, CSS
- `src/kona_tracker/cli.py` — `kona probe | serve | cameras | camera-test`; `cli_env.py` reads `.env`
- `tests/` + `tests/fixtures/` — mocked Fi responses; fake camera
- `docs/` — per-slice plans; `fi-api-fields.md` once the probe has run
- `.dos/outbox/` — session artifacts (wrap)

## Facts that constrain design

- **Only the camera is location-bound.** The video originates on the home
  network, so the server that reads it must sit there. The Fi probe and the
  app itself run on any machine with internet, home or not.
- `api.tryfi.com` is an ordinary cloud API, blocked *only* from claude.ai/code
  sandboxes (proxy 403). Chris can run `kona probe` from any laptop with
  internet and the Fi credentials; it does not need the home machine.
- Fi's API is undocumented and unversioned; pytryfi (the reference) has not
  shipped since Dec 2023. Expect drift; the probe is the drift detector.
- Starlette's TestClient runs the ASGI app to completion, so an endless
  MJPEG stream cannot be tested through it; `/stream.mjpg?frames=N` caps it.
- A USB webcam opens once per process; the hub is what lets two phones watch.
- An MJPEG `<img>` freezes on the last frame when frames stop; the hub streams
  a placeholder when stale so "frozen" can never pass for "live".
- RTSP credentials must live inside the URL for OpenCV/FFmpeg; `redact_url()`
  runs on every string that could carry it. Keep it that way.
- No RTSP server exists in the cloud sandbox; the network path is proven via
  an in-process HTTP MJPEG server. Real RTSP auth/decode = Astro's step.
