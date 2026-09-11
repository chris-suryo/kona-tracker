# Frontend history review — 11 September 2026

Frontend work is on `chatgpt/ui-pass`, originally based on main `3be6863`, in the
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

## Latest refinement and pickup

PR #7: https://github.com/chris-suryo/kona-tracker/pull/7 (draft, Chris merges).
The branch now includes main through `f266de8`, including snapshot camera
polling and bounded MJPEG waits from PRs #8/#9. The import-only conflict in
web/app.py was resolved by retaining HTTPException and Query. The frontend
did not redesign that camera transport.

Chris approved the initial visuals and requested less text, a smaller
minutes figure alongside hours, weekly rest averages, and smoother refresh.
Implemented in `0b4fb3d`, followed by main integration `bc4d534`:

- Shared duration markup makes trailing minutes smaller; minutes-only
  durations retain their primary size.
- Weekly rest leads with a daily average over five complete fixture days,
  excluding today and the day with a missing reading. It is not a clinical
  "normal" or a baseline. Average sleep/nap breakdown accompanies it.
- Removed repeated explanatory copy; "View readings" contains the exact
  plotted values and the missing/zero legend. Sample banners stay explicit.
- Refresh follows the pull without transition lag, settles near its release
  position, shows a brief result and fades/slides away. Timer cancellation
  prevents an old dismissal from hiding a new gesture. Reduced motion remains.

Validation after integrating main: 279 pytest passed; Ruff check and format
check clean; 14 Node runtime tests passed. The latest visual inspection was
blocked by automatic approval review reporting the account usage limit.
Do not describe these latest refinements as visually verified on iPhone.
`dos wrap --help` was blocked by Windows Application Control; this document
records the session instead. No alternate execution was attempted.

Next session: fetch `chatgpt/ui-pass`, read this file plus CLAUDE.md and
PROJECT.md, inspect PR #7 against current main, and retain any later backend
merges. Finish phone/light/dark/reduced-motion checks before Chris merges.
The production-safe polish can ship with sample-only history routes; actual
history must wait for verified data. Keep "View readings" driven by the same
data as charts when integrating. The map provider decision is still open.

## Final navigation pass

SUPERSEDED by the simplification below: Chris reviewed the added homepage
charts and approved removing them from the overview.

## Approved simplification (current design)

Latest approved adjustment supersedes the ordering in the paragraph below:
Steps first, naps/sleep second, Location third, then freshness. Restored a
larger steps number/ring and more section spacing. Removed the separate
"From her collar" status block; activity start, walking distance and
connection now sit inside Location. "420 m walked · Started ..." distinguishes
the start from the collar report time. Detailed charts remain one tap away.

Activity now orders collar status, compact location/map, tappable Steps,
tappable Rest, then freshness. Hourly charts and weekly totals are removed
from the overview; sample history remains in its detail routes. Steps/Rest
use subtle chevrons rather than a separate View day button. Live summaries
remain non-interactive until verified history is implemented. Sample banner
is one line; entering Settings from it explicitly says preview has ended.
Settings now says "Test camera" and "Preview sample data".

Map investigation found the global no-referrer policy conflicts with OSM's
browser Referer requirement (https://operations.osmfoundation.org/policies/tiles/).
Tile images now opt into referrerPolicy=origin, revealing only the site
origin; other requests retain no-referrer. No provider/CDN was added.
The browser visibly rendered normal map tiles after this change. A tileerror
fallback hides the map and states the background is unavailable. HTTP-200
images containing error text cannot reliably be detected by this handler.
The browser was available again: simplified dark layout and map were visually
checked. Real iPhone, light theme and pull gesture QA still remain.

Chris asked for more visual context on the homepage and fewer exploration
links. Sample Activity now includes compact hourly Steps and Rest charts
using the exact detail-page buckets. Tapping the steps total/ring or its
"View day" pill opens Steps. Tapping either compact chart opens its detail.
"View readings" and "View intervals" are pill disclosures. Detail pages
return to Activity via the existing back link; cross-links between Steps
and Rest were removed. All of this remains sample-only until real feeds
are verified. No basemap changes were made.

Final navigation validation: 280 pytest passed; Ruff lint and format checks
clean. The local preview was restarted from the integrated branch at
http://127.0.0.1:8765/activity?preview=1 with fixed fake-camera capabilities.
Latest browser visual verification remains outstanding after the previously
reported usage-limit rejection; no alternate browser access was attempted.

Suggested Claude pickup prompt:

> Continue kona-tracker from branch chatgpt/ui-pass, draft PR #7. Read
> CLAUDE.md, PROJECT.md and docs/frontend-history-handoff.md first. The branch
> includes main through f266de8 plus the frontend history prototype and
> approved polish. Fetch current main and inspect newer merges before
> changing anything. Preserve the camera snapshot polling implementation.
> Finish visual QA on iPhone in both themes, especially the clickable steps
> hero, homepage hourly charts, duration hierarchy, weekly averages and pull
> refresh. Samples must never masquerade as live data. Next, integrate only
> verified history data using the contract in the handoff; daily summaries
> first if hourly buckets/intervals remain unavailable. No new dependencies,
> inline executable scripts, CDN assets or Leaflet-byte changes. Keep the
> reduced-motion block last, preserve deliberate zoom behavior, and keep
> pytest/Ruff green. Chris reviews and merges; do not merge automatically.
