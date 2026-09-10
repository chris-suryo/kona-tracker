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

The camera connected today is a **Logitech C230 HD USB webcam** at index 0.
Windows and OpenCV both open it, but it currently returns an effectively
all-black image at both 640×480 and 1280×720, even after an exposure test.
That points to the lens cover/orientation, an unlit room, or the hardware —
not the web layout. The app detects repeated black frames and shows CHECK
CAMERA instead of calling transport-only activity LIVE. Once the device
returns a visible frame, it supplies live video and still JPEGs. It has no
motors or presets, so the UI intentionally shows capture/share and no
directional controls.

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

### The likely next camera

A Tapo is still a reasonable always-on replacement for the temporary USB
webcam. Pick its capability row only after the exact model is in hand. The
app renders controls from the connected driver, so even a pan/tilt model
does not advertise motion until a real driver can move it.

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

**Distance is metres, and only walks count. Verified on a real walk,
2026-09-10 20:53-20:57.** `OngoingWalk.distance` read 285.8; `totalDistance`
for the day read 286 and the week 379 (= the earlier 93 + 286). 286 m in
4 min 38 s is walking pace. A day with thousands of steps and 0 here is a
day with no walk, which is a true statement rather than a broken field. It is
in `/activity.json` as `distance_m` / `week_distance_m`; whether it gets a
tile back is the design's call.

### What a walk looks like, measured

Fi detects the walk with a **2-3 minute lag**: a probe at 20:55 still said
`OngoingRest`; one at 20:57 said `OngoingWalk` started 20:53:00. During it:
`ConnectedToCellular` with `signalStrengthPercent` 71 falling to 29 as they
moved off; a `cell` block in `device.info`; `gnssLiveTrackingEnabled: true`;
`positions` at one per second with `errorRadius` from 65 m (cold fix) down
to 4-7 m. Steps rose 3,579 → 5,795 across the walk.

**Escape and walk are independent flags.** The walkers had no phone with the
Fi app, so `operationParams.mode` went `NORMAL` → `POST_ESCAPE_NOTIFICATION`
— and stayed there while the walk was detected. `CollarStatus.escaped`
carries it; the page must be able to show it, because it is exactly the
state a worried owner wants to know about.

**`timeToEmptyS` is a live power estimate, not a battery fact.** 368,634 s
(4.3 d) on the charger; 43,987 s (12 h) on cellular + GPS; 105,969 s a few
minutes later. Battery *percent* is stable (57 → 56.5). Percent is the
number for the page; "days left" is deliberately not exposed to templates.

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

### Round 3 results, 2026-09-10

Asked for the fields Fi had named. What came back:

- **`overnightRestSummary` exists and is its own type**, `OvernightRestSummary`
  — not a `RestSummary`. `start`, `end` and `data` were all rejected, and
  `data` drew *"did you mean `date`?"*. It also takes a **required argument**.
  This is Fi's own "last night" and should replace the
  previous-completed-window heuristic once its shape is known.
- **`restFeed` and `stepFeed` take `cursor`, not `limit`.**
  **`activityFeed` takes `limit`, not `cursor`.** All three still want a
  required argument. History is real; the pagination differs per feed.
- **`OngoingRest { place { id name } }` is accepted.** So is
  `homeLocation { position { latitude longitude } }`, `places { id name
  position { latitude longitude } }` and `timezone`. These are verified
  shapes. `homeLocation.position` is the privacy-safe source for drawing the
  Home map; the saved place's street-address-shaped name stays server-side.
- `heatmap`, `activity`, `packs` and one of the `device` extras each need a
  required argument.

### The redaction and allowlist fixes this round proved out

The `cell`, `wifi*`, `iccid`, `eid` and `credentialPackHash` blanking all
worked, and the 749-point GPS track collapsed to four lines. Two follow-ups
the same run exposed:

1. **The allowlist was rejecting every required-argument message.**
   graphql-js's `ProvidedRequiredArgumentsRule` names the field alone —
   `Field "restFeed" argument "cursor" ...` — not `Type.field`. The pattern
   demanded the coordinate form, and its test used a shape invented rather
   than observed, so it passed while every real message was redacted for two
   rounds. Same failure mode as the mock that answered any query: tested
   against an assumption instead of reality.
2. **The skeleton used a Unicode ellipsis.** Windows PowerShell 5.1's
   `Get-Content` reads `summary.md` as the ANSI codepage, so it arrived as
   mojibake. It is ASCII `"..."` now.

Mildly over-redacted, and left that way: `rcellMohm` (matches `cell`) and the
`wifiScanCount`-style counters. They are diagnostics nobody needs.

### Named by Fi, still unshaped

Every one of these came from a "did you mean" on 2026-09-10, so they exist;
their shapes do not. Each needs a subfield guess and another correction.

- `overnightRestSummary` on `Pet` — Fi's own "last night". Should replace
  the previous-completed-window heuristic once its shape is known.
- `restFeed`, `activityFeed`, `stepFeed` — history feeds.
- `timezone` on `Pet`; `homeLocation.position` and resting `place` are now shaped.
- `heatmap`, `packs`, `packFeed`, `activity` on `Pet`.
- `carrier`, `hardwareRevision`, `firmwareUpdate` on `Device`;
  `uncertaintyInfo` on `OngoingActivity`.

### The redaction gap the walk exposed

Once on cellular, `device.info` carried the home Wi-Fi SSID, the modem
IMEI, SIM ICCIDs, the eUICC EID and the serving cell id (which geolocates to
a tower). None matched the redactor's key list, and they reached
`summary.md` — a file that gets pasted into chats. The key families are now
blanked (`ssid`, `wifi`, `imei`, `iccid`, `imsi`, `eid`, `cell`,
`credential`), whole blocks where nothing the page needs lives inside. What
was already pasted cannot be un-pasted; it is identifiers, not credentials.

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
- capture/share on fixed USB cameras (working; save-to-device fallback when
  Web Share is unavailable)

Controls that **must not** appear:

- hold-to-talk — impossible on Tapo, on any model
- pan/tilt on a fixed camera — the page must ask, never assume

The Activity tab now uses only the confirmed fields above. Its free MVP map
uses Leaflet 1.9.4 and OpenStreetMap's standard raster tiles. At rest it uses
the verified `homeLocation.position`; on a walk it switches to Fi's live
route, then preserves and labels the last fix. It never geocodes or invents
a coordinate.
