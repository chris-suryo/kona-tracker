# Frontend history review — 11 September 2026

Frontend work is on `chatgpt/ui-pass`, based on main `3be6863`, in the
`frontend` worktree. Keep backend/camera work in its existing checkout.
This branch is for a PR; Chris merges. No new packages, map service or
production Fi queries were added.

## What is implemented

- Small, steady collar dots; camera badge padding is scoped to the camera.
- Activity says "From her collar"; location says "Collar reported";
  fetch freshness says "Checked Fi". These are different timestamps.
- Quieter sign-out and camera connection indicator, with reduced motion.
- Authenticated `/preview/steps` and `/preview/rest`: fictional Day/Week
  charts, previous/next sample day, selectable hour, readable tables and
  sample sleep/nap intervals. Linked only from the sample Activity page.
- Overview sample totals match the drill-down fixtures. The seven-day sum
  includes an explicitly missing hour and the incomplete current day.
- Samples are frozen at 11 September 2026, 11:00 UTC and explicitly labelled.
  None can become a fallback for missing live readings or enter the Fi cache.

The preview server uses `--fake-camera` with `KONA_CAMERA_MODEL=usb` to
match a fixed camera. Its test-only settings are outside the repository.
The usual unconfigured fake camera intentionally supports simulated PTZ.

## Message for the backend session

Please investigate verified history access without altering the working
production GraphQL documents with guesses. Frontend needs the following
semantic contract, not these literal Fi field names:

1. Step buckets: start/end timestamps with offsets, step count (`null` for
   unknown, zero only when measured), coverage/completeness and source
   resolution. Determine whether values are interval counts or cumulative.
2. Rest: timestamped sleep/nap intervals, plus dated totals in seconds and
   coverage. Preserve unknown classification rather than inventing awake time.
3. Envelope: pet timezone, requested bounds, source-reported-through time
   when available, server fetched-at time, stale/partial status, pagination
   and the earliest available date. If source freshness is unknown, say so.
4. Daily goals: preserve the goal that belonged to each day. Do not apply
   today's adaptive goal retroactively.
5. Fixtures proving midnight/DST boundaries, missing vs zero, late batches,
   duplicates/overlapping pages and partial current days. Exclude data from
   the previous collar according to KONA_FI_DATA_START.

Start with the accepted summary feeds and isolated history probes already
in the repo. Record redacted response structure and units, never credentials,
addresses or raw coordinates in committed fixtures. An accepted query must
be verified on Kona's account before integration. If only daily summaries
are accessible, ship daily charts first and explicitly defer hourly ones.

Do not infer event hours from changes in polled cumulative totals: a batch
can include older activity. A poll series could only be called "received
since last check", not an activity timeline. Likewise, last night's sleep
total does not establish start/end intervals or sleep quality.

Screenshots supplied by Chris show Fi displaying barking, licking, active
time and strain. Rejected speculative field names do not prove product-wide
absence; they prove those query shapes failed. These remain unavailable to
our app until a verified access path is found. Do not fabricate the metrics.

## Map decision

Leaflet is the renderer; the current appearance comes from OpenStreetMap
raster tiles with a dark-mode CSS filter. Recommend evaluating Stadia Maps
Alidade Smooth / Smooth Dark raster tiles with the same vendored Leaflet.
No provider was switched. A switch needs Chris's approval for the external
service, account/plan review, attribution, authentication and a targeted CSP
img-src update. Honour no-referrer rather than weakening it for domain auth;
confirm an appropriate authentication approach before deployment.

References: https://docs.stadiamaps.com/map-styles/alidade-smooth-dark/
and https://docs.stadiamaps.com/authentication/ . Avoid publishing an
unrestricted private API key. Map requests disclose the viewed tile area
to the selected provider, as the existing tile service already does.

## Review and remaining work

Review phone layouts in both themes. The browser preview is not iOS Safari;
real-device verification still belongs to Chris before merge. No camera
transport or shutdown work is included here. Actual history integration,
comparisons, extra periods, alerts, and a new basemap are deferred.

Keep `uv run pytest -q`, `uv run ruff check .`, and
`uv run ruff format --check .` green. Vendored Leaflet bytes, page zoom and
the final reduced-motion block retain their existing contracts.

Local Windows validation: 266 pytest passed; Ruff lint and format checks
passed; 12 Node browser-runtime tests passed. Browser review exercised
hour selection, Day/Week navigation, rest layout, and absence of PTZ in
the fixed-camera preview. Dark theme was visually inspected; light theme
and real iPhone Safari review remain before merge.
