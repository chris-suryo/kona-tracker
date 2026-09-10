# kona-tracker

Private, passcode-gated, iPhone-first web app for Chris and their sister to
check on Kona (dog). Activity tab from her Fi collar (Whoop later); Camera tab
once the hardware exists.

---
kit: 3e06b156508b881bef26345c0bb7a63c90db4824 · stamped by dos new
---

## Status

- **Slice 1 (in-repo, unverified against Fi):** `kona probe` dumps every Fi
  API field, redacted. See `docs/slice-1-probe-plan.md`. Astro's follow-up
  fixes are in PR #1 (reviewed; one regex fix requested before merge).
- **Slice 2 (in-repo, verified with fake camera only):** `kona serve` = passcode
  gate + live camera (MJPEG) + Activity placeholder. See
  `docs/slice-2-camera-plan.md`.
- **Slice 2b (in-repo, verified with simulated streams):** RTSP network camera
  source (Tapo TC73 is the leading option), reconnect supervisor, "NO SIGNAL"
  placeholder + status label so frozen video never looks live, `kona
  camera-test`. See `docs/slice-2b-rtsp-plan.md`.
- **next:** Astro runs `uv run kona camera-test` then `kona serve` against the
  real camera on the Windows PC and reports; when the collar arrives, the
  probe. Then `/plan` slice 3: Activity hero on confirmed Fi fields, and
  Pi + Tailscale for remote viewing.

## Ownership

| Who | Owns |
|---|---|
| Claude Code (cloud) | web app, camera backend, tests, CI, docs. Cannot see hardware, LAN, or the Fi API. |
| Astro (ChatGPT, local clone) | probe fixes (PR #1); running things on real hardware; reporting results. |
| Claude Design | templates + CSS (`src/kona_tracker/web/templates`, `static/app.css`). |
| Chris | hardware, `.env`, merges. |

Shared only via GitHub. Separate branches; do not edit another owner's area
without a PR.

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

## Commands (PowerShell, repo root)

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

- `api.tryfi.com` is unreachable from claude.ai/code sandboxes (proxy 403).
  Anything touching the real API must be run by Chris in PowerShell.
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
