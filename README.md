# kona-tracker

A private, passcode-gated, iPhone-first web app so Chris and his sister can
check on Kona, a one-year-old Labrador. Two tabs: **Activity**, from her Fi
collar (steps, sleep, today by the hour, last night's span, a walk log
with each route on a map), and **Camera**, live video from a Tapo C120 in
the house with pinch-to-zoom and the camera's own switches (night vision,
privacy mode, status light).

Python: FastAPI, Jinja templates, plain CSS and plain JavaScript. No build
step, no JavaScript framework, no npm. The camera is read with OpenCV over
RTSP and its switches driven with pytapo. It runs on a machine at home because
the video originates there. It is for two people and one dog; it is not a
product.

## Where things stand

`PROJECT.md` is the current state of the project and the queue -- read that,
not this, to find out what is done and what is next. `CLAUDE.md` is the set
of working rules every session follows.

## Run it in five minutes, no hardware needed

Needs [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```
git clone https://github.com/chris-suryo/kona-tracker.git
cd kona-tracker
uv sync
cp .env.example .env        # set KONA_PASSCODE and KONA_SECRET
uv run kona serve --fake-camera
```

Open http://localhost:8000 and enter the passcode. The Camera tab shows a
test pattern; the Activity tab waits for a collar. `docs/first-run.md` is the
plain-language version of this, including the real camera, the collar, and
getting it onto a phone.

## Commands

| Command | What it does |
|---|---|
| `uv run kona serve` | The app. `--fake-camera` for a test pattern, `--port`, `--host`. |
| `uv run --no-sync kona serve` | The same, on a machine where Application Control blocks `uv sync` (Chris's Windows PC). Runs what is already installed. |
| `uv run kona probe --out probe-out\round12` | Ask Fi's API what it knows, redacted, into `summary.md`. The only way to learn what the collar exposes; Fi has no public API. One folder per round; eleven have run. |
| `uv run kona cameras` | Which USB camera indexes open. |
| `uv run kona camera-test` | Open the configured camera once and report size, fps, bytes per frame. **Stop `kona serve` first**: two programs on one webcam produce black frames that look like a wedged device. |
| `uv run kona camera-doctor` | Raw pixel statistics per index and backend, for a camera that opens but shows nothing. |

Every setting is an environment variable read from `.env`; `.env.example`
documents each one and the reasoning behind its default.

## Pages

| Path | What it shows |
|---|---|
| `/activity` | Steps, rest, last night, where she is, walks today. Re-fetches once a minute while open; pull down for now. |
| `/steps` | Today's steps by the hour (`?hour=` picks one). |
| `/rest` | Today's sleep and naps by the hour, then one bar per day since the collar came online. |
| `/walks/<id>` | One walk: distance, pace, the route on the map. |
| `/camera` | The picture. Pinch or double-tap to zoom. Night vision, privacy and the status light when the camera answers. |
| `/settings` | Camera health, collar battery, sign out. |
| `/activity.json`, `/status.json`, `/healthz` | The same facts as JSON, for a script or a watchdog. |

## Reaching it from outside the house

`docs/remote-access.md`. Short version: a Cloudflare tunnel to hand someone a
link, Tailscale for yourself, and the two `.env` settings that differ between
them -- one of which silently breaks login if it is wrong.

## Development

```
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
```

CI runs exactly those three on Ubuntu and Windows and must stay green on
every push. Tests live beside the code they cover; a change to logic comes
with a test. `tests/browser_runtime.test.cjs` exercises the page scripts
under Node and is run by hand (`node tests/browser_runtime.test.cjs`), not
by CI.

Things that will silently break if changed without reading first -- the
Content-Security-Policy that forbids inline scripts, the vendored and
byte-pinned Leaflet, page zoom being off on purpose -- are listed in
`docs/history/chatgpt-handoff.md`, each with the reason.

## The docs, and which one to trust

| File | What it is |
|---|---|
| `PROJECT.md` | **Current.** Status, hard-won facts, the queue. |
| `docs/history/production-punchlist.md` | The queue with the reasoning behind every item. |
| `docs/scaling-limits.md` | The ceilings this design has, with the measurements behind each. |
| `docs/device-capabilities.md` | What the hardware can actually do, measured. Cameras and the collar. |
| `docs/data-brief.md` | What Fi's API returns and what the page may therefore claim. |
| `docs/remote-access.md` | Tunnel, Tailscale, keeping the PC awake, what breaks. |
| `docs/first-run.md` | Setting it up, in plain language. |
| `docs/history/camera-black-screen-handoff.md` | Why the camera polls one frame at a time instead of streaming. |
| `docs/history/chatgpt-handoff.md` | The brief for a visiting assistant. |
| `docs/history/handoff.md` | The 2026-09-10 handoff. Dated; `PROJECT.md` supersedes it. |
| `docs/history/` | Records of past days, not instructions. |

## Privacy

`.env` holds a Fi password, a passcode, a session secret and an optional map
key. `probe-out/` holds what Fi's API said about the dog. Both are gitignored
and neither is ever committed. The probe redacts emails, session ids,
locations, addresses and hardware ids before writing anything.
