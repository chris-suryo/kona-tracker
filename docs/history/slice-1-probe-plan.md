# Slice 1 — Fi API probe (approved 2026-09-09)

## Goal

`uv run kona probe` (PowerShell, repo root) logs into Fi once, dumps every
field the API exposes for Kona (schema introspection + real sample responses),
redacts identity/location, and writes `probe-out/summary.md` for review, so
slice 2 designs the sleep hero on confirmed fields rather than guesses.

## Why probe first

v0's hero is "rest/sleep quality", but the only public Fi clients (pytryfi,
hass-tryfi) expose sleep/nap DURATION only: no quality score, no behavior
fields (scratching/licking/barking/eating/drinking). Fi's app shows
"restfulness" and "nighttime interruptions", so richer fields probably exist
server-side. The CLAUDE.md trust ladder (manual -> proven -> automated) says
verify against reality before building on it.

`api.tryfi.com` is blocked from claude.ai/code sandboxes (egress proxy 403),
so the probe can ONLY run on Chris's PC. Cloud sessions build against fixtures.

## Decisions (from /grill)

1. **Hosting**: undecided long-term; Pi not yet bought. Default: run on the
   Windows PC now, move to Pi + Tailscale later; stays an env-var-configured
   web server so cloud remains possible.
2. **Stack**: Python. FastAPI + Jinja + htmx for the web layer (slice 2+),
   kit tooling (uv / pytest / ruff, ubuntu+windows CI). Direct GraphQL client
   over httpx; pytryfi NOT used (last release Dec 2023, GET-based, drags in
   `requests`).
3. **Slice 1 = probe only.** No passcode gate, no dashboard, no HTML.

## What the API is known to expose (from pytryfi source)

- Login: `POST https://api.tryfi.com/auth/login`, form `email` + `password`,
  session cookie, JSON `{userId, sessionId}`.
- GraphQL: `POST /graphql`.
- Rest: `pet(id){ restSummaryFeed(cursor:null, period: DAILY|WEEKLY|MONTHLY,
  limit) { restSummaries { start end data { sleepAmounts { type duration } } } } }`
  with type SLEEP|NAP, duration in seconds.
- Activity: `pet(id){ currentActivitySummary(period) { totalSteps stepGoal
  totalDistance } }`.

## Shape of the code

- `src/kona_tracker/fi/client.py` — `FiClient`: login + graphql; errors keep
  Fi's "Did you mean ...?" hints. Injectable transport for tests.
- `src/kona_tracker/fi/queries.py` — introspection, pets, rest, activity, and
  a speculative-field query whose validation errors are the fallback when
  introspection is disabled.
- `src/kona_tracker/probe/` — `run.py` orchestrates (each step best-effort),
  `redact.py` blanks sensitive keys by name, `scan.py` extracts Pet fields
  and keyword hits (sleep/rest/nap/quality/score/behavior/...).
- `src/kona_tracker/cli.py` — `kona probe [--env-file .env] [--out probe-out]`.
- `tests/` — fixtures + httpx.MockTransport, no live calls.

## Next (slice 2, after the probe has run)

Read `probe-out/summary.md`, commit it as `docs/fi-api-fields.md`, then plan
the passcode gate + Field-styled dashboard with the hero chosen from confirmed
fields (fallback if no quality score: last night's SLEEP duration).
