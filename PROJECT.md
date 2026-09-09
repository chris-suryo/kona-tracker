# kona-tracker

Private, passcode-gated, iPhone-first web app for Chris and their sister to
check on Kona (dog). Activity tab from her Fi collar (Whoop later); Camera tab
once the hardware exists.

---
kit: 3e06b156508b881bef26345c0bb7a63c90db4824 · stamped by dos new
---

## Status

- **Slice 1 (done in-repo, unverified against Fi):** `kona probe` CLI that
  logs into Fi and dumps every API field, redacted. See
  `docs/slice-1-probe-plan.md`.
- **next:** Chris runs the probe locally (below) and commits
  `probe-out/summary.md` as `docs/fi-api-fields.md`. Then `/plan` slice 2:
  passcode gate + dashboard hero on confirmed fields.

## v0 scope

In: Fi login, rest/sleep as hero metric, Field visual direction (dark mode
primary, single-hue teal ramp, big tabular hero number, hairlines not cards),
one shared passcode.

Not in v0: Camera tab (placeholder only), Whoop, behavior metrics
(barking/scratching/eating/drinking: unconfirmed in the API), remote camera
access, per-user accounts.

## Stack (shape: web app, minimal stamp; decided by /grill 2026-09-09)

Python 3.11+, uv, typer, httpx. Web layer (slice 2+): FastAPI + Jinja + htmx.
Tests: pytest with `httpx.MockTransport` fixtures; no live Fi calls in CI.
Lint/format: ruff. CI: ubuntu + windows matrix.

Hosting: undecided. Runs on the Windows PC now; Raspberry Pi + Tailscale when
hardware arrives; cloud possible later (env-var config only, no host lock-in).

## Commands (PowerShell, repo root)

```powershell
uv sync                         # install
uv run pytest -q                # tests
uv run ruff check . ; uv run ruff format .
Copy-Item .env.example .env     # then fill FI_EMAIL / FI_PASSWORD
uv run kona probe               # writes probe-out\summary.md (+ json dumps)
```

`.env` and `probe-out/` are gitignored. Never commit either.

## Locations

- `src/kona_tracker/fi/` — Fi API client + GraphQL documents
- `src/kona_tracker/probe/` — probe orchestration, redaction, schema scan
- `src/kona_tracker/cli.py` — `kona` entry point
- `tests/` + `tests/fixtures/` — mocked Fi responses
- `docs/` — per-slice plans; `fi-api-fields.md` once the probe has run
- `.dos/outbox/` — session artifacts (wrap)

## Facts that constrain design

- `api.tryfi.com` is unreachable from claude.ai/code sandboxes (proxy 403).
  Anything touching the real API must be run by Chris in PowerShell.
- Fi's API is undocumented and unversioned; pytryfi (the reference) has not
  shipped since Dec 2023. Expect drift; the probe is the drift detector.
