# Meadow polish and reliability review — 2026-09-11

## Branch and ownership

Chris approved the four-area visual/copy pass. This branch,
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
The reduced-motion block remains last. No Fi queries or camera lifecycle changes
are part of the visual pass.

## Reliability findings: separate follow-up

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
