# Next session — review, merge, and get it onto the phone

Written 2026-09-10 after reviewing ChatGPT's two branches. Read
`docs/history/handoff.md` first for the project; this file is only the immediate
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

## 1. Map: keep it, but it must not depend on a CDN being up — **DONE 2026-09-11**

> Leaflet 1.9.4 now lives in `web/static/leaflet/` (js, css, images,
> license), byte-identical to the npm release: a test pins the same sha256
> values the unpkg SRI attributes carried. `.gitattributes` keeps those
> bytes off Windows autocrlf. Nothing in the templates loads from unpkg.
> The "blank coloured box" failure below therefore cannot happen; the honest
> empty state is what shows when there are no points.

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

## 2. Camera: RESOLVED 2026-09-11 — it was a wedged USB device

`camera-doctor` (added this session, `uv run kona camera-doctor`) reported
mean 86.96 / max 255 / sd 58.54 at index 0 through DirectShow, and
`camera-test` then captured 10 frames at 1280x720. Chris had **unplugged the
camera and plugged it back in** between the failing run and the working one.

Diagnosis: the device wedged after another program held it. It opened
cleanly and delivered nothing. Not code, not hardware, not the resolution
request — my hypothesis that 1280x720 caused it was disproved by
`camera-test` succeeding at exactly that size. Recorded in
`docs/device-capabilities.md` and `docs/first-run.md`; the `sd` column is
what separates a wedged camera (0.00) from a dark room (low mean, sd well
above zero, because a real sensor has read noise).

**Still open from this item:** point 3 below was never checked. The
black-frame threshold `frame_is_unusable` (`frame.mean() <= 0.25`) has not
been tested against a genuinely dim room at night — the room was lit in
every run so far. "CHECK CAMERA" when the truth is "the light is off" is
exactly the confident-wrong output this project refuses. Worth one evening
test with the lights off.

## 2b. Set `secure=True` on the session cookie — do before the public URL

`web/app.py` sets the login cookie with `httponly=True, samesite="lax"` and
**no `secure=True`**. Behind a Cloudflare tunnel the public side is always
HTTPS so it is not exposed in practice, but the same cookie is issued over
plain HTTP on the LAN, and "in practice" is not a security argument.

The catch that makes this more than a one-liner: hard-coding `secure=True`
breaks LAN access over `http://192.168.x.x:8000`, because the browser will
refuse to send the cookie and the login silently never takes. So it needs to
be conditional — a `KONA_PUBLIC` / `KONA_SECURE_COOKIES` setting, defaulting
off, that `docs/remote-access.md` tells you to turn on. That means a
settings key, the app change, and tests for both states.

Flagged in `docs/remote-access.md` Part 0.

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
- ~~Archive the stale `docs/probe-fixes-handoff.md`.~~ **Done 2026-09-11**:
  moved to `docs/history/2026-09-09-probe-fixes-handoff.md` with a
  superseded header. `docs/history/handoff.md` now names itself as current.
- The `?preview=1` sample-data page ChatGPT added deserves a careful look
  against this project's "never show data you do not have" rule. It is
  labelled sample-only; confirm that survives every state.
- The eventual Tapo camera: model not chosen. Third-Party Compatibility must
  be enabled in the Tapo app or nothing connects.

## 6. Remote access — the actual next milestone

`docs/remote-access.md` now exists. **Nothing in it has been run.** It is a
plan written from documentation on a sandbox with no Windows machine, and it
says so at the top. Part 1 (a Cloudflare quick tunnel, ~15 minutes, no
domain needed) is the proving step and should be done before anything in
Part 3 is automated.

The step I am least confident in is 3c, starting the app on boot: a
Scheduled Task running as SYSTEM will probably serve a dead camera, because
Windows gates camera access per-user. The doc proposes at-log-on as the user
instead and says to verify by looking at the camera tab from a phone after a
reboot, not by confirming the process started.
