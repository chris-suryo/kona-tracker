# Meadow polish and reliability review — 2026-09-11

## Branch and ownership

Chris approved the four-area visual/copy pass, then explicitly approved
continuing the backend audit and hardening on the same branch. This branch,
`codex/meadow-health-polish`, starts at `11d439a` on
`claude/elegant-sagan-tit1xp`. Its PR targets that branch so the review shows
only this pass. Chris merges; no deployment or production restart was performed.
Merge this PR into Claude's branch, then review/merge the combined branch into
`main`. If Claude's branch merges first, retarget this PR to `main` and verify
the diff before merging. Do not cherry-pick the same changes twice.

## What changed

- Settings camera status has a dedicated dot, avoiding the video badge's
  global `.live` styling. Long historical problems read below their label.
- Empty-map copy is shorter; saved Home pins explicitly say they are not
  Kona's reported position. Stale maps carry their own qualification.
- Location headings wrap their timestamps on narrow screens.
- Refresh text stays stationary while a CSS indicator turns; reduced-motion
  disables it. Automatic refresh is visible below the header.
- Camera black-frame advice now mentions reconnecting USB, matching the
  documented diagnosis. A requested reconnect no longer claims it succeeded.

CSP, vendored Leaflet bytes, page/map zoom rules and dependencies are unchanged.
The reduced-motion block remains last. No Fi query documents were changed.
The initial visual commit did not change camera lifecycle; the approved
hardening continuation below does.

## Current continuation for Claude

Chris asked to keep the work consolidated and continue hardening, including
the previously proposed shutdown fix. Keep using this branch/PR; do not apply
the initial audit's proposals a second time. These are now implemented:

- **Shutdown:** the real CLI passes `timeout_graceful_shutdown=5`. Uvicorn
  cancels remaining responses after the grace period, then runs lifespan
  cleanup. This is a response-drain budget, not a promise that all cleanup
  finishes in exactly five seconds. A subprocess regression test holds an
  actual HTTP MJPEG stream open, asks the server to stop, and verifies both
process exit and camera release. It exercises the CLI configuration.
- **Camera hub:** no obsolete or stale frame is returned to a new viewer as
  LIVE. Abandoned readers cannot overwrite current errors/frames. A viewer
  arriving during idle shutdown starts a replacement supervisor. At most two
  camera reader threads may be outstanding, including blocked open/close
  calls. Once full, recovery waits for a reader to return and reports
  `reader_limit`, rather than spawning threads forever. Status adds `readers`.
  Shutdown gives cooperative readers a shared one-second release budget after
  stopping the supervisor; stuck readers cannot block cleanup indefinitely.
- **Browser camera:** starts CONNECTING; serial status polls have a five-second
  deadline. Invalid/failed responses hide the old image and report OFFLINE.
  Successful recovery reconnects the video. Hidden/page-hidden pages abort
  polling, cancel retry timers and release the stream; return resumes it.
  Historical errors no longer override a current CONNECTING state. An idle
  hub while the page is visible prompts a stream reconnect.
- **Capture:** ten-second request deadline; requires `X-Kona-State: live`
  before constructing a shareable photo. The NO SIGNAL placeholder cannot
  be shared as a current picture of Kona. Sharing itself is not timed out.
- **Activity:** twenty-second refresh deadline unlocks retry after a hung
  request. Cancelled/multitouch pulls do not trigger requests. Sample preview
  never installs refresh handlers, so wake-up cannot swap it to live data.
  Failed refresh changes the current-status labels to last-reported wording.
  Old Leaflet instances are explicitly removed before replacing the markup.
- **Fi cache:** simultaneous cold-cache visitors share one refresh. Unexpected
  exceptions expose their type, not arbitrary strings that may contain private
  data. Retained routes carry local `positions_carried` provenance (also in
  `/activity.json`) so a later walk without points cannot promote an old route
  to Current walk. No GraphQL fields or requests were added.
- **Health/heartbeat:** pending, unavailable, partial, stale and healthy Fi
  readings are distinguished; `/healthz` remains a read-only cache peek.
  Heartbeat non-2xx responses count as failures, and exception messages cannot
  leak the secret ping URL. Its purpose remains process reachability, not a
  camera-quality alarm.

The browser regression harness is `tests/browser_runtime.test.cjs`, using only
Node's built-in test/VM modules. Run it with an existing Node installation:
`node --test tests/browser_runtime.test.cjs` (PowerShell). No npm packages,
build step or production runtime requirement were introduced. Python pytest
and Ruff remain the required CI checks; the browser harness is an additional
local check, not silently required by `uv run pytest`.

Real Chromium verification: fake camera LIVE → stop the test server → OFFLINE
with old image hidden → restart the test server → LIVE on the same page,
without reloading. All servers used for these checks were localhost-only,
sample/fake-only and separate from Chris's running app.

### Remaining limits and next hardware check

This is a focused runtime audit, not a claim that every backend path or the
physical device is now proven. In particular:

- A blocked native driver cannot be killed by Python threads. The cap bounds
  resource growth but does not repair it; replug/restart may remain necessary.
  Worker-process isolation is a future architectural change, not implemented.
- MJPEG `<img>` does not expose a per-frame progress callback. A successful
  status poll plus a decoded image cannot prove Safari is receiving every new
  frame, especially if another viewer keeps the hub live. Server-loss and
  visibility recovery are tested; silent Safari decoder freezes remain open.
- Fi requests have per-request network timeouts; a complete multi-query refresh
  can exceed the browser's twenty-second deadline. The server can finish and
  populate the cache after the browser has honestly reported refresh failure.
- Fi's ordinary five-minute polling/backoff policy and the deployment host,
  sleep configuration and tunnel were audited by reading, not changed.
- Recheck on the physical phone: Camera → Activity → refresh → Camera, both
  quickly and after more than five seconds; background/restore; Ctrl+C while
  viewing; then a lights-off test. Verify the webcam LED goes off after the last
  viewer leaves. Run camera-doctor/test only with other camera owners closed.

The existing deprecation warnings in FastAPI/Starlette test support are not
fixed here because doing so would require dependency changes.

Local final validation: **234 pytest tests passed**, Ruff lint and format
checks passed, and **10 browser-logic tests passed**. The Python tests include
real TCP shutdown with a fake source, permanently hung readers, the idle-return
race, stale-frame rejection, Fi cold-load concurrency and route provenance,
heartbeat HTTP rejection/privacy, and health states. GitHub's Ubuntu/Windows
results for the pushed commit are recorded in the PR checks.

## Original audit findings (history; implementation status above supersedes proposals)

Chris reports: after restarting, going to Activity and refreshing can leave
the camera black; its LED remains on. Ctrl+C prints "Waiting for connections
to close" even after he closes the phone app, sometimes with a delay.

1. **Shutdown ordering is a real code issue.** `cli.serve` supplies no
   `timeout_graceful_shutdown` to Uvicorn (default `None`). Uvicorn waits for
   responses before lifespan shutdown, but `hub.stop()` runs in lifespan
   shutdown and MJPEG responses are intentionally endless. A five-second
   graceful-shutdown budget is proposed separately for Chris's approval.
   Test against an open stream, including Windows; don't assume a unit test
   of `hub.stop()` exercises the server's ordering.
2. **A hung reader can survive reconnect.** The supervisor abandons threads
   blocked inside the driver and starts new ones. It cannot force the old
   reader to release the USB device. Repeated permanent hangs can accumulate
   blocked threads. A bounded worker-process design is a possible later fix,
   requiring an explicit plan and failure-injection tests. Do not paper over
   this with faster retries or concurrent `VideoCapture.release()` calls.
3. **Browser health is not picture health.** `camera.js` polls hub status,
   not whether Safari is displaying new frames. Polls have no deadline and
   can overlap; an unresponsive server can leave an old LIVE label on screen.
   Add bounded, non-overlapping polling and an honest unavailable state in a
   separate reliability pass. Validate Safari sleep/wake and network loss.
4. **Activity doesn't directly stop the camera.** Navigating away removes a
   viewer; after five idle seconds the hub releases the device. Returning
   opens it again. Exercise Camera → Activity → refresh → Camera both before
   and after that idle delay on real USB hardware. A fake source cannot prove
   the USB driver survives reopen.
5. **Known hardware symptom, not a new diagnosis.** Earlier real measurements
   found all-zero frames from a wedged C270; unplugging/replugging cleared it.
   LED on only establishes that capture is open. A genuinely dark-room test
   is still owed. Avoid declaring this new report conclusively the same fault.

Recommended order: bounded shutdown; browser failure/recovery; repeatable USB
reopen test; then decide whether capture process isolation is necessary.
Keep only one production server using the camera. Stop the server and close
other camera apps before running `uv run kona camera-test` in PowerShell.
If USB returns black frames, unplug/replug and repeat. Do not collect or paste
credentials, full process command lines, or raw Fi location data into a PR.

## Map direction

Leaflet is the renderer; the current appearance comes from OpenStreetMap
raster tiles plus `brightness(.72) saturate(.7) contrast(1.08)` in dark mode.
That merely dims the daytime map. It is not a designed dark basemap.

A purpose-designed dark raster layer can use the same vendored Leaflet.
CARTO Dark Matter is a candidate, but current CARTO documentation requires an
API key and attribution. Confirm service terms/limits and Chris's approval
before adding its host to CSP or changing requests. No provider was added.

- https://leafletjs.com/reference.html#tilelayer
- https://carto.com/basemaps/apikey/
- https://carto.com/legal/basemap-terms/

## Validation and limits

The visual pass is reviewed locally with synthetic data and a fake camera,
including phone-width light/dark settings, empty and saved-location states,
resting location and refresh indicator. This is Chromium review, not physical
iPhone/Safari or real USB verification. Check CI on Ubuntu and Windows before
merge; final local check results are recorded in the PR.

An isolated Windows/Python 3.14 shutdown experiment with an open fake MJPEG
stream reproduced waiting; after client close it also reached an eight-second
timeout in Uvicorn's server wait, with a Windows connection-reset exception.
Treat this as evidence to test shutdown across runtimes, not proof that the
five-second setting cures every USB or Windows driver problem.
