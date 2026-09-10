# What the hardware can actually do

Written 2026-09-10, before the UI redesign, so nobody designs a control the
hardware cannot perform. The first design round drew pan controls and a
large "hold to talk" button. One of those is buildable on the right camera;
the other is not buildable on any Tapo. Everything below is either verified
against a source or explicitly marked unverified.

Sources: [pytapo](https://github.com/JurajNyiri/pytapo) and the
[Home Assistant Tapo integration](https://github.com/JurajNyiri/HomeAssistant-Tapo-Control)
built on it, which lists supported models;
[TP-Link's ONVIF FAQ](https://www.tapo.com/us/faq/724/) for the profile
level; [pyatv](https://pyatv.dev/) for Apple TV.

---

## 1. Camera models

Abilities are **data**, not assumptions in a template. `KONA_CAMERA_MODEL`
picks the set; `src/kona_tracker/camera/capabilities.py` holds it. A model
we do not recognise gets video only, because showing too few controls beats
offering one that silently fails.

| Control | C120 (fixed) | C210 / C220 / C225 (pan-tilt) |
|---|---|---|
| Live video (RTSP) | **Built** | **Built** |
| Still snapshot | **Built** | **Built** |
| Pan / tilt | **Impossible** — no motors | **Available**, not yet driven |
| Presets | **Impossible** | **Available**, not yet driven |
| Night vision on / off / auto | Available | Available |
| Privacy mode (lens blind) | Available | Available |
| Alarm / siren | Available | Available |
| LED indicator | Available | Available |
| Motion detection + sensitivity | Available | Available |
| Mic mute, speaker volume | Available | Available |
| SD recording, file download | Available | Available |
| Reboot, time sync | Available | Available |
| **Live two-way talk** | **No** | **No** |

"Available" means the local API exposes it and we have not written the
driver yet. "Built" means it works today.

### Why two-way talk is off on every Tapo

TP-Link implements **ONVIF Profile S**. The audio backchannel that carries
your voice to the camera is **Profile T**. Talking to Kona works in the
Tapo app over their proprietary protocol; it does not work through
standards, so it cannot work through ours.

Getting it would mean a different class of camera (Dahua, Hikvision, some
Reolink) *and* replacing our whole video path with go2rtc and WebRTC.
Deliberately dropped. `Capabilities.talk` is `False` everywhere and a test
pins it, so it cannot be switched on hopefully — only by someone who proved
it against real hardware.

### The plan across two cameras

The C120 already ordered is not wasted: fixed cameras make good second
angles. A C225 added later becomes the one you steer. The app renders each
correctly from the same code, so both can be plugged in and compared.

### Setup gotcha

Recent firmware requires **Third-Party Compatibility** switched on in the
Tapo app before the camera account works at all. Both RTSP and the control
API fail without it. It is step 2 in `docs/first-run.md`.

---

## 2. Fi collar

Kona's collar was paired on 2026-09-10 and `kona probe` has now run against
the real API. Everything below is either measured or explicitly marked
unverified.

### Confirmed present

| Data | Status |
|---|---|
| Steps today, and step goal | **Working.** 3,383 of 28,000 on the first run |
| Steps this week / month | **Working** (`currentActivitySummary`, three periods) |
| Sleep and nap duration | **Working**, daily / weekly / monthly. **Units are seconds**: weekly SLEEP 27,202 = 7.6 h, NAP 38,382 = 10.7 h |
| Her photo, breed, birthday, weight | **Confirmed** in the profile body. Born 2025-08-15; photo dated 2026-09-07 |
| Collar battery | **Confirmed**: `device.info.batteryPercent` (57), `max77658Info.timeToEmptyS` (≈4.3 d). Not on `Pet` or `Device` directly — both rejected |
| On charger vs out | **Confirmed**: `lastConnectionState.__typename` is `ConnectedToBase` (with a base id) or `ConnectedToCellular { signalStrengthPercent }` |
| LED colour / on-off, lost-dog mode | **Confirmed** readable: `ledColor`, `operationParams.ledEnabled`, `.mode` |
| Resting vs walking | **Confirmed**: `ongoingActivity.__typename` is `OngoingRest` or `OngoingWalk` |

### Data before 2026-09-10 is not Kona

Chris had an earlier Fi collar that did not fit and sat unworn. Fi attaches
data to the *pet*, not the device, so the history carries that collar's
readings: "resting since 7 Sep 18:51", 2.4 h of "sleep" on the 9th, 7.6 h
across the week. That is a collar in a drawer. The new collar went on
2026-09-10; treat only readings from then as hers. Any week or month view
must not be designed around the earlier numbers.

### How Fi's days work — measured, and it changed the design

The daily rest window runs **midnight to midnight in the owner's timezone**
(`04:00Z` boundaries = Eastern). The newest window is **today, in progress**,
and its SLEEP is 0 until tonight. Last night's sleep lives in the window that
ended this morning.

The first implementation fetched one window and would have shown **0 h** under
"Last night" — formatted honestly, and wrong. `pet_rest` now fetches two and
`parse.split_windows` picks the most recent *completed* day for the hero and
the in-progress one for naps-so-far-today. A collar paired today, with no
completed night yet, says "first full night still to come" rather than 0.

### Confirmed ABSENT — do not design for these

The speculative probe query asks for field names we hoped existed and reads
the validation errors. Fi's server suggests a near match when there is one —
it answered `currentBehaviorSummary` with *"Did you mean
currentActivitySummary?"* — so a rejection **with no suggestion** is real
evidence of absence, not just a wrong guess.

- `sleepQuality`, `restQuality`, `restScore`, `sleepScore` — **no sleep
  quality score of any kind exists on `Pet`.**
- `behaviorSummary`, `behaviorFeed`, `currentBehaviorSummary`,
  `interruptions` — **no barking, scratching, licking, eating or drinking
  counts.**

These had been open questions since the project started. They are closed.
Nothing in the UI may assume a 0-100 score or a behaviour count.

### Not trustworthy yet

`totalDistance` returned **0 for the day against 3,383 steps**, and 93 for
the week — and did not move on the second run while steps rose to 3,538.
Whatever the unit is, it is not tracking steps. Now near-certain: it only
accrues on walks. `ongoingActivity` has been `OngoingRest` since 2026-09-07
18:51 — no walk has been logged since the collar went on — and distance is
~0 to match. It is **off the page** (weekly steps took its tile) and stays in
`/activity.json` marked raw until a real walk confirms the unit.

Introspection is **disabled** on the production API, so the schema cannot be
dumped. Field names come from asking and reading the errors.

### The bug that hid sleep, and the lesson

`RestSummary.data` is an abstract type; `sleepAmounts` lives on the concrete
implementation. Our fragment selected it directly, so Fi rejected the whole
query — steps arrived, sleep did not. The fix is an inline fragment:

```graphql
data { __typename ... on ConcreteRestSummaryData { sleepAmounts { type duration } } }
```

Two things made this expensive, both worth remembering:

1. **The mock answered a malformed query.** `tests/conftest.py` routed on
   operation name alone, so 102 passing tests validated the *parser* and
   never the *query*. The mock now rejects a rest query missing the inline
   fragment, exactly as the server does.
2. **The error allowlist ate the answer.** Fi almost certainly replied *"Did
   you mean to use an inline fragment on ConcreteRestSummaryData?"* and we
   kept only "GraphQL error". `FiGraphQLError` now preserves the whole
   graphql-js validation family, which names schema identifiers only.

### Named by Fi, not yet queried (round 3)

Every one of these came from a "did you mean" on 2026-09-10, so they exist;
their shapes do not. Each needs a subfield guess and another correction.

- `overnightRestSummary` on `Pet` — Fi's own "last night". Should replace
  the previous-completed-window heuristic once its shape is known.
- `restFeed`, `activityFeed`, `stepFeed` — history feeds.
- `OngoingRest { place }` — where she is resting. `homeLocation`, `places`,
  `timezone` on `Pet`.
- `heatmap`, `packs`, `packFeed`, `activity` on `Pet`.
- `carrier`, `hardwareRevision`, `firmwareUpdate` on `Device`;
  `uncertaintyInfo` on `OngoingActivity`.

### Confirmed absent, second round

On `Device`: `battery*`, `charging`, `firmware*`, `signalStrength`,
`temperature`, `serialNumber` (battery is inside `info`; signal is on the
cellular connection state). On `ActivitySummary`: `activeMinutes`,
`calories`, `walks`, `distanceMeters` — `totalDistance` is the only distance.
On `RestSummary`: `quality`, `score`, `restfulness`, `interruptions`,
`wakeUps` — **no sleep quality at any level.** On `Pet`: `heartRate` (Fi
offered `heatmap`), `health*`, `locationHistory`, `geofences`, `goals`.

### Sourced but unverified

Taken from [pytryfi](https://github.com/sbabcock23/pytryfi)'s `const.py` —
the library behind the Home Assistant integration — and added to the probe,
not to the page:

- **`photos`** on `BasePetProfile` — Kona's picture from the Fi app, so the
  avatar need not be a hand-copied jpg.
- `ongoingActivity`: `areaName`, `lastReportTimestamp`, live walk distance
  and GPS positions with an error radius.
- `lastConnectionState`: charging-base state, `signalStrengthPercent`.
- `operationParams`: lost-dog `mode`, `ledEnabled`, LED colour.
- breed, weight, birthday, `homeCityState`.

The probe fetches these; the next `summary.md` says which are real. Until
then they stay out of the UI.

## 3. Apple TV and general home automation

**Technically possible.** pyatv is mature, covers power, remote navigation,
app launching, now-playing and AirPlay, is pure Python, and works over the
local network. It would run on the same home server with no architectural
change.

**Recommended anyway: don't build it here.** This app is a focused thing
for two people about one dog. Home Assistant already solves home
automation, runs on the same Raspberry Pi, and ships integrations for both
this camera and Apple TV. Rebuilding that inside a dog app costs months and
makes it worse at its actual job.

The line: **camera control belongs here** because it is about watching
Kona. Everything else belongs in Home Assistant. If one surface is wanted
later, this app can read a few Home Assistant entities over its REST API —
a cheap bridge, not a rebuild.

Chris has parked this for a separate project.

---

## 4. What this means for the redesign

Controls that **may** appear, gated on the connected camera's capabilities:

- pan and tilt, plus presets — **pan-tilt models only**
- night vision (on / off / auto)
- privacy mode
- alarm
- LED indicator
- motion detection toggle and sensitivity
- speaker volume, microphone mute
- snapshot (already working)

Controls that **must not** appear:

- hold-to-talk — impossible on Tapo, on any model
- pan/tilt on a fixed camera — the page must ask, never assume

Still undecided, pending the probe: everything on the Activity tab.
