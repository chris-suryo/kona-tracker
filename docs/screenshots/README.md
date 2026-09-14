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
(`docs/chatgpt-handoff.md` is the brief they go with.)

**The dated directories** (`2026-09-13/`, `2026-09-14/`, …) are the opposite:
a record of one specific change on one specific day, kept so a decision can be
re-examined later. Never overwrite one.

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

## Two things about the capture that are not bugs in the app

- **Maps say "Map unavailable."** The capture machine has no route to the
  tile server. On a phone a map renders there. Say so in the brief, or a
  reviewer will spend a section on it.
- **The camera picture is a synthetic test pattern** from `FakeSource`. The
  frame, the overlays and the controls around it are real and worth judging;
  the image is not.

Playwright must use `waitUntil: 'domcontentloaded'`. With `'load'` every page
hangs 30–60 s waiting on `fonts.googleapis.com`, which is unreachable here —
this cost two timed-out runs before anyone noticed.
