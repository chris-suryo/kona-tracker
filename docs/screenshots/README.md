# Screenshots

Two kinds of directory live here.

**`current-ui/` is the audit set.** It is a complete capture of every page in
both themes at the current build, and it is **regenerated and overwritten**
rather than added to.

It was first built when this repository was private, when screenshots were the
only evidence that could travel with a question. The repo went public on
2026-09-14 and the set stayed, because the original reason was never the whole
reason: **reading a template is not seeing what it renders.** A reviewer can
now read `app.css` and still not know that the collar battery clips off the
right edge at 390 px. Source answers "what did we write"; the capture answers
"what does a phone draw". An audit wants both.
(`docs/history/chatgpt-handoff.md` is the brief they go with.)

**The dated directories under `history/`** (`history/2026-09-13/`, …) are the
opposite: a record of one specific change on one specific day, kept so a
decision can be re-examined later. Never overwrite one.

## Regenerating `current-ui/`

Two files do it, and neither is imported by the app:

```bash
uv run python scripts/audit_server.py &          # port 8140
NODE_PATH=/opt/node22/lib/node_modules node scripts/audit_shots.js
```

`audit_server.py` builds the **real** app — the real templates, stylesheet and
JavaScript — with a stub Fi service, a fake camera, and a stub robot gateway
reporting a healthy robot. Nothing is mocked above the data layer, so what you
see is what a phone would draw.

It takes about ten minutes. Most of that is the map pages waiting out a tile
server the sandbox cannot reach.

The Python half runs anywhere the app runs, Windows included. The capture half
needs Node and Playwright's Chromium, which are **not** project dependencies
and are not worth installing on the Windows PC — the cloud session has them,
so ask it to regenerate the set rather than setting up a browser stack to take
pictures of your own phone's app.

## Marking up the UI from a phone

For a round of nitpicks, `scripts/contact_sheet.js` turns the audit set into
one sheet per page -- light and dark side by side, with a lettered-and-numbered
100 px grid over both, the page name burned in -- under
`docs/screenshots/contact/` (gitignored: generated on demand, not a record).

```bash
NODE_PATH=/opt/node22/lib/node_modules node scripts/contact_sheet.js
```

Open a sheet on the phone and either circle things in Markup and send the
image back, or just say the grid reference: *"steps, light, C4, too much gap
under the ring."* A grid cell maps to a selector in a minute; a description
of a screenshot does not. This exists because the alternative that was asked
about -- an image model annotating the UI -- describes pictures and does not
reliably draw on them.

## The overflow check

`scripts/check_overflow.js` runs against the same server and measures whether
any page scrolls sideways at 320, 375, 390 or 430 px. It exists because "the
text isn't aligning right" turned out once to be literal -- the Activity
header ran to 410 px on a 390 px screen and clipped the battery -- and nothing
in the test suite can see that. pytest renders HTML without laying it out; the
Node harness stubs the DOM. Only a browser measures.

```bash
NODE_PATH=/opt/node22/lib/node_modules node scripts/check_overflow.js
```

Not a CI gate: CI has no browser, for the same reason the Node harness is not
one either.

## What in a capture is not the app

- **The camera picture is a synthetic test pattern** from `FakeSource`. The
  frame, the overlays and the controls around it are real and worth judging;
  the image is not.
- **The maps are flat colour.** The capture machine has no route to a tile
  server, so `audit_shots.js` fulfils every basemap request with a 1×1 tile —
  light or dark, so a screenshot still says which basemap the page asked for.
  Drive-mode shots dated before 2026-09-15 show "Map unavailable" instead:
  the landscape context was the one that had been missed.
- **The data is fixtures.** A frozen snapshot, a green square in place of
  Kona's photo, four synthetic walks on one hand-drawn route, and states that
  never occur — the collar is never stale, the robot is never low on battery.
- **The engine is Chromium, not Safari.** WebKit cannot be installed in this
  environment. A capture can show that a layout works and that the copy is
  right; it cannot show how the app feels on the phone.
- **`env(safe-area-inset-*)` is 0 here and about 59 px on the phone.** Every
  screenshot in this set has its header that much closer to the top edge than
  the real thing. A capture limit, not a layout bug.

Since 2026-09-15 the capture is taken at the iPhone 14 Pro's metrics — 393
wide, the screen's full 852 height because this app is opened from the home
screen and has no browser toolbar, `isMobile` and `hasTouch` so hover queries
resolve the way the phone resolves them.

Playwright uses `waitUntil: 'domcontentloaded'`. It used to have to: with
`'load'` every page hung 30–60 s on the webfont host, which cost two
timed-out runs before anyone noticed. The font is vendored now
(`src/kona_tracker/web/static/fonts/`, declared by `@font-face` at the top of
`app.css`), so that hang is gone — but the setting stays, because these pages
poll and stream by design and `'load'` waits on work that is not meant to
finish.

The capture now waits on `document.fonts.ready` and **throws** if Bricolage
Grotesque did not load. The failure it replaces was silent: every screenshot
in this directory taken before 2026-09-15 was rendered in the fallback font
while the phone rendered the real one, and nothing in the set said so.
