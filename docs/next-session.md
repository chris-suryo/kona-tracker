# Next session — review, merge, and get it onto the phone

Written 2026-09-10 after reviewing ChatGPT's two branches. Read
`docs/handoff.md` first for the project; this file is only the immediate
queue. Decisions in here were made by Chris and are not open questions.

## What is waiting

Two branches, neither merged. **`chatgpt/map-camera-pass` contains
`chatgpt/ui-pass`** (it includes both of its commits), so merging the
second alone is enough.

Verified on `chatgpt/map-camera-pass` in a sandbox:

- `uv run pytest -q` -> **165 passed**
- `uv run ruff check .` -> clean
- `uv run ruff format --check .` -> **3 files need reformatting**. Run
  `uv run ruff format .` as the first commit so the diff stays honest.

The redesign is good and answers "is Kona OK?" at a glance: a "Right now /
Resting / On charger" header with battery, steps against goal with a
progress ring, naps and last night paired, location, then the weekly
baseline. Keep that hierarchy.

It went well beyond the templates-and-CSS scope it was given -- Python,
camera, settings, a new template, new tests. That is fine, and it is why
this is a real review rather than a rubber stamp.

## 1. Map: keep it, but it must not depend on a CDN being up

**Decided: keep the map.** Two things to fix before merge.

- **Vendor Leaflet.** `activity.html` loads `leaflet.css` and `leaflet.js`
  from `unpkg.com`. CLAUDE.md says no new dependencies without asking, and
  a CDN is one. Copy Leaflet 1.9.4's css and js into `web/static/` and load
  them from there. Check the license header stays in the file.
- **Add a real unavailable state.** Measured in the sandbox with unpkg
  blocked: the map renders as a **blank coloured box with no explanation**.
  It must say something honest instead -- the same discipline as NO SIGNAL
  on the camera. Her location as text (Home, or walking with distance and
  last fix time) is already in the context, so the fallback has real content
  to show.

Related, worth checking while in there: `base.html` already loads Google
Fonts, and a render-blocking external stylesheet that fails to arrive was
measured earlier to **kill the cross-document view transition** (the
incoming page declines it). Leaflet's stylesheet was a second one. Vendoring
it removes one of the two.

**Accepted and not to be re-litigated:** OpenStreetMap's tile servers see
roughly where Kona is whenever the page opens. Chris knows and accepts this
for a two-person private app. Keep the attribution. Do not add prefetching,
offline tiles, or a proxy.

## 2. Camera: treat black frames as a regression, not a new fact

`docs/handoff.md` on `chatgpt/map-camera-pass` says the camera is a
**Logitech C230** returning black frames. **Both halves are wrong.**
Chris confirms it is a **Logitech C270**, and it **worked earlier the same
day** -- there is a screenshot of live video on the Camera tab, and the
capability model correctly drew no pan/tilt pad for it. Fix the model name
in the docs.

So this is a regression with a known-good starting point. Diagnose in this
order:

1. Something else grabbed the camera. This already happened once: Windows
   Settings > Camera was open and that alone was enough. Close Settings,
   Teams, Zoom, browser tabs on a call. `uv run kona camera-test` with the
   server stopped is the command that actually reads frames.
2. A physical lens cover or shutter.
3. **The new black-frame check itself.** `camera/source.py::frame_is_unusable`
   returns True when `frame.mean() <= 0.25` on a 0-255 scale. That is
   essentially pure black, so it should be safe -- but this camera watches a
   dog in a room at night. Confirm a genuinely dim room does not trip it,
   because "CHECK CAMERA" when the truth is "the light is off" is exactly
   the kind of confident wrong output this project refuses.

The black-frame detection is good work regardless: a transport-live stream
of all-zero pixels is not a live picture, and the app should not call it
one.

## 3. Port 8000 vs 8100

`kona serve` defaults to **8000** (`cli.py`), and nothing in the repo
mentions 8100. If 8000 appears taken it is almost certainly a `kona serve`
left running from an earlier terminal. On Windows:

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen |
  Select-Object -ExpandProperty OwningProcess |
  ForEach-Object { Get-Process -Id $_ }
```

Stop that process, or run on another port deliberately with
`uv run kona serve --port 8100`. Either is fine -- just pick one and use the
same number on the phone.

## 4. Then: end to end on the phone

The actual goal. In order: merge, `uv run kona serve`, log in on the PC,
then `ipconfig` -> `http://<IPv4>:8000` on the iPhone, same Wi-Fi. Camera
tab showing real video, Activity tab showing real Fi data, her photo in the
header. Add to Home Screen over a Cloudflare tunnel if a clean full-screen
launch is wanted.

## 5. Still open, lower priority

- Probe round 4: `uv run kona probe --out probe-out\round4`. The allowlist
  fix means required-argument messages now name the arguments for
  `overnightRestSummary` and the three history feeds.
- `docs/probe-fixes-handoff.md` is from 2026-09-09 and is stale -- it says
  the collar has not arrived. It already misled one assistant into using it
  as the current handoff. Archive it under a dated name.
- The `?preview=1` sample-data page ChatGPT added deserves a careful look
  against this project's "never show data you do not have" rule. It is
  labelled sample-only; confirm that survives every state.
- The eventual Tapo camera: model not chosen. Third-Party Compatibility must
  be enabled in the Tapo app or nothing connects.
