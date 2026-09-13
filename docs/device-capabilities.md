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

> What a camera *can* do is here. What the app's delivery of it **cannot** do
> — bandwidth per viewer, the concurrent-viewer ceiling, the unexplained
> 4 fps — is in `docs/scaling-limits.md`.

The camera connected today is a **Logitech C270 USB webcam** at index 0.
**Working, verified 2026-09-11**: `kona camera-doctor` read mean 86.96,
max 255, sd 58.54 through the DirectShow backend, and `kona camera-test`
then captured 10 frames at 1280×720 (~3.7 fps, ~88 KB per frame).

An earlier note here said this camera "returns an effectively all-black
image ... that points to the lens cover, an unlit room, or the hardware."
That was written from one failed run and it was wrong. The cause was a
**wedged USB device**: it opened fine and delivered nothing. Unplugging it
and plugging it back in fixed it, with no code change. Treat black frames
as a replug first, a hardware verdict last. `docs/first-run.md` carries the
diagnosis steps.

(The model was previously recorded here as a "C230 HD". That was wrong;
Chris confirmed a **C270** on 2026-09-10, recorded in
`docs/next-session.md`. The string drives no behaviour either way:
capabilities come from `KONA_CAMERA_MODEL`, and any value not in
`BY_MODEL` -- including no value at all -- falls back to the video-only
`USB` set.)

The app detects repeated black frames and shows CHECK CAMERA instead of
calling transport-only activity LIVE. Since 2026-09-11 "black" means all
zero or flat (no sensor noise), so a genuinely dark room -- low mean, noise
present -- is shown as the dark picture it is, not as a broken camera. The
dark-room half of that rule is documented, not yet measured. It has no motors or presets, so the UI
intentionally shows capture/share and no directional controls.

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
| Night vision on / off / auto | **Built** (2026-09-13) | **Built** |
| Privacy mode (lens blind) | **Built** (2026-09-13) | **Built** |
| Alarm / siren | Available | Available |
| LED indicator | **Built** (2026-09-13) | **Built** |
| Motion detection + sensitivity | Available | Available |
| Mic mute, speaker volume | Available | Available |
| SD recording, file download | Available | Available |
| Reboot, time sync | Available | Available |
| **Live two-way talk** | **No** | **No** |

"Available" means the local API exposes it and we have not written the
driver yet. "Built" means it works today. The three switches went in on
2026-09-13 through `pytapo` (`camera/tapo.py`); they need
`KONA_TAPO_PASSWORD`, the TP-Link cloud password, because recent firmware
authenticates the control API that way. Verified against the fake driver
and the route tests; first run against the C120 itself is Chris's.

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
- `timezone` on `Pet` is now selected by the page and assumed to be an IANA
  name; the probe redacts its value, so check `/activity.json`'s `"clock"`
  instead -- `"fi"` means it loaded, `"server"` means it did not (or the PC
  lacks the `tzdata` package). `homeLocation.position` and resting `place`
  are shaped.
- `heatmap`, `packs`, `packFeed`, `activity` on `Pet`.
- `carrier`, `hardwareRevision`, `firmwareUpdate` on `Device`;
  `uncertaintyInfo` on `OngoingActivity`.

### Round 5, queued 2026-09-11: her position while resting

Chris caught the wrong claim in an earlier draft of the punchlist: the Fi
app shows her location whether she is walking or asleep, and our query never
asked for it. `pet_status` selected `OngoingRest { place { id name } }` and
nothing else.

**Sourced, not yet measured:** pytryfi's `FRAGMENT_ONGOING_ACTIVITY_DETAILS`
selects `... on OngoingRest { position { latitude longitude } }`, and its
`setCurrentLocation` reads `activityJSON['position']` for a rest — that is
the field hass-tryfi's `device_tracker` reports. We already use the
`OngoingWalk` half of that same fragment, verified on the 2026-09-10 walk.

The page now asks for it in `pet_whereabouts` — **a document of its own**,
because a rejected field fails the whole document and the verified collar
fields must not go down with a guess. If Fi rejects it the page says
"Location: Fi rejected the query" and draws the saved home pin as before.
The probe sends the identical document, so the next run settles it. It also
asks, one unknown each: `position { date }` on OngoingRest (a `Location`
with a date, or a bare `Position`?), `uncertaintyInfo { __typename }`,
`path` on OngoingWalk, and `lastLocation` / `currentLocation` on `Device`
next to the confirmed `nextLocationUpdateExpectedBy`.

The mock in `tests/conftest.py` answers `KonaWhereabouts` with pytryfi's
shape. That is an assumption, not a measurement, and the tests say so; the
one thing they prove is that a rejection costs exactly the map point.

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

### Stated by Fi's own assistant, 2026-09-11 -- claims, not measurements

Chris asked the "Kona's health" chat inside the Fi app what the numbers
mean. That assistant is trained on Fi's help content, so it knows the
product where the probe knows the schema, which is a genuinely
complementary source. It is also a language model: **every line below is a
hypothesis to verify, not a fact to ship.** One of them already contradicts
something we measured.

**Corroborated, and now safe to say plainly in the UI.**

- *"Fi's daily totals reset at midnight in your dog's local time zone, so
  the day rolls over based on where Kona is, not a fixed global time."*
  This is what we inferred and built to; it also vindicates rendering times
  in Fi's `timezone` on `Pet` rather than the server's clock.
- *"Fi usually recognizes a walk within the first few minutes of consistent
  outdoor movement... A walk ends when the collar detects a pause or stop,
  typically after a few minutes."* Matches the 2-3 minute lag measured on
  the 2026-09-10 walk.
- *"Overnight rest is classified as sleep, typically the longest continuous
  period during usual nighttime hours. Shorter or fragmented rest periods
  during the day are counted as naps."* Matches the SLEEP/NAP split.

**Resolves a mystery this file recorded as open: distance.**

> *"Fi counts distance based on GPS tracking during outdoor movement, not
> just step count from the collar's accelerometer. So if Kona took 3,383
> steps mostly indoors or while the collar wasn't connected to GPS, the
> distance recorded can still show zero."*

That is the explanation for the day with 3,383 steps and zero distance, and
it means the figure was never wrong. Distance is **outdoor GPS distance**,
steps are accelerometer. It has been kept out of the UI pending an
explanation; that block is now lifted, provided it is labelled as outdoor
or walk distance and a zero is never presented as "she did not move".

**Supports the resting position we have asked for but not yet measured.**

> *"Kona's collar updates location when it connects via Bluetooth or Wi-Fi,
> typically syncing every few minutes while at home. The app shows her most
> recent location based on those updates, but it's not a continuous live
> feed like during walks."*

If the app shows a resting location, the API almost certainly carries one,
which is what `pet_whereabouts` asks for. It also explains why `device`
exposes `nextLocationUpdateExpectedBy`: at rest the position is a periodic
check-in, and that field says when the next one is due. Still unmeasured
until the probe runs, but the prior just got considerably stronger.

**New, and it changes UI copy: the step goal moves.**

> *"Kona's daily step goal starts based on her breed, age, and weight...
> Over time, Fi adjusts that goal dynamically based on her recent activity
> patterns... it's not fixed; it evolves with her fitness and routine."*

So "of 9,000" is a moving target. A goal that changes between days is Fi
working as designed, not our bug, and the page should not imply it is fixed.

**Contradicts a measurement, and the measurement wins.**

> *"The data itself is a summary of your dog's movement patterns, including
> steps taken, distance traveled, active minutes, and detected behaviors
> like barking or scratching."*

Probe rounds 1 and 2 asked for exactly these and Fi's own server rejected
them: `behaviorSummary`, `behaviorFeed`, `currentBehaviorSummary`,
`interruptions`, `calories` and `activeMinutes` all came back as unknown
fields **with no "did you mean" suggestion**, which this project treats as
evidence of absence. A validation error from the production API outranks a
support assistant describing a product line.

Three possibilities, and they are worth one targeted probe rather than a
shrug: the assistant is blending in a competitor's feature list; the data
exists but hangs off a type we have never queried; or it is simply wrong.
Until one of those is settled, **nothing about barking, scratching or
active minutes goes near the UI.**

**A lead worth its own probe: the Safe Zone.**

> *"The 'left the safe zone' alert triggers when your dog's Fi collar moves
> outside the boundaries of the Safe Zone you set in the app."*

We already parse the escape flag from `mode`, so the alert is real. But
`safeZones` and `geofences` were both confirmed absent on `Pet`. The likely
reconciliation: a Safe Zone is a **`Place` with a radius**. pytryfi's
`PlaceDetails` fragment selects `id name address position radius`, and our
round-3 probe confirmed `places { id name position }` is accepted. So
`places { __typename id name radius position { latitude longitude } }` is
the query that would prove it, and if the radius is real the map could draw
the safe zone as a circle instead of only reporting the breach after it
happens. Queued for the next probe round.

**Settled: there is no official way in, and there never was.**

> *"Fi doesn't offer a public API, developer program, or webhooks for
> accessing your dog's data."*

This project has carried that as an assumption since the first slice. It is
now Fi's own answer, which changes nothing about the approach and a lot
about how confident we can be in it: the private GraphQL API is the only
path, `kona probe` stays permanent because drift is guaranteed and
unannounced, and no amount of waiting will produce a supported alternative.
A data export was deflected to Fi's Customer Experience team rather than
refused, so that is a real avenue and worth an email, but it is an account
matter and not something the assistant can action.

**The notification list is a feature spec we can already satisfy.**

Asked what alerts Fi can send, it named: leaving or entering a Safe Zone,
meeting or missing the daily step goal, collar low battery or
disconnection, and walk reminders or milestones.

Every one of those is computable from data this app **already fetches**.
The escape flag covers the Safe Zone crossing, `steps` against `stepGoal`
covers the goal, `batteryPercent` and the connection state cover the
collar, and `ongoingActivity` covers walks. So the alerting Fi does is not
something we need API access to receive; it is something we could derive
from the snapshot we already hold, and the outbound heartbeat shows the
shape such a thing would take. Worth remembering that the list also tells
us what Fi's own product team decided is worth interrupting someone for,
which is a reasonable prior for what belongs on the page.

Note the phrase *"activity, behavior, and health info"* appears here too.
That is the second unprompted mention of behaviour data, against a
measured absence. It raises the value of the targeted probe, and lowers
nothing: the field names are still rejected by the server.

**How the assistant behaves, which shapes how to ask it.**

A question phrased as a fault gets deflected rather than answered: asking
why the battery estimate swings between days and hours returned only a
pointer to Fi's Customer Experience team. Questions phrased as "how does X
work" get substantive answers. Worth knowing before spending another
evening on it.

## 2b. Zoom is off on purpose

Chris asked for zoom gone page-wide, was told what it costs, and said it
again: *"On an actual app, you don't do that."* So this is a decision, not
an oversight, and it is written here so nobody quietly "fixes" it later.

**What it costs.** This is a WCAG 1.4.4 failure. Anyone who enlarges text to
read a screen cannot do it here. The app has two readers and its owner chose
that trade for his own app; it is not a pattern to carry to anything with a
wider audience.

**What it takes, because one half is not enough.** Chrome and Android honour
`maximum-scale=1, user-scalable=no` in the viewport meta. iOS Safari has
ignored `user-scalable` since iOS 10, so `app.js` also cancels Safari's own
`gesturestart` / `gesturechange` / `gestureend`, and cancels any `touchmove`
carrying more than one finger, since a two-finger drag is not a gesture
event. Both listeners must be non-passive or `preventDefault` does nothing.

**The map is exempt, deliberately.** Leaflet takes `touch-action: none` on
`.leaflet-container.leaflet-touch-drag.leaflet-touch-zoom` and does its own
pinch, so pinching the map moves the map. `app.js` skips anything inside
`.leaflet-container`; without that exemption the map would freeze at one
zoom level and the location tab would be much less useful.

**Verified in Chromium with iPhone emulation, 2026-09-11:** a synthetic
two-finger `touchmove` and a `gesturestart` are both cancelled over the page
and both left alone over the map, and the one-finger pull-to-refresh still
fires. Tests pin all of it.

**To undo it**, should Chris ever change his mind: drop `maximum-scale=1,
user-scalable=no` from `base.html` and delete the last block of `app.js`.
Two edits, nothing else depends on it.

## 2c. The live picture does not render in iOS Safari

**Measured 2026-09-11 on Chris's iPhone**, with Safari Web Inspector
attached from a Mac over USB, against the real C270 on the LAN. This is the
first time any part of this app was inspected on the device it is built for,
and it overturns an assumption the code was written on.

The Camera tab sits on "Connecting…" forever. At that moment:

| what | reading |
|---|---|
| `document.getElementById('cam').naturalWidth` | `0` |
| `document.getElementById('cam').complete` | `false` |
| the `/stream.mjpg` request | open, loading, never completes |
| Web Inspector's body view for it | "Resource has no content" |
| `/healthz` on the server, same moment | `camera=live` |
| a desktop browser on the same server | shows the live picture |

`naturalWidth: 0` is the browser saying it has never decoded a frame. So the
picture is not hidden by CSS or withheld by the reveal logic. **There is no
image.**

### Corrected the same day: it is intermittent, not absent

The first conclusion written here was that iOS Safari cannot render
`multipart/x-mixed-replace` at all. **That is wrong.** Chris reopened Safari
later and the picture came through. His summary: Safari works sometimes and
sometimes hangs on "Connecting…" forever, Chrome on the phone is steadier
but also not perfect.

Intermittent is a different and more useful fact than broken. It means the
format is supported and something about *holding one connection open for
minutes on a phone* is fragile. Candidates, none yet tested:

- **Connection exhaustion.** An MJPEG stream occupies one connection for as
  long as it lives, and browsers cap concurrent connections per host at
  around six. Every `reload()` in `camera.js` points the `<img>` at a fresh
  `/stream.mjpg?t=…`. If Safari does not promptly tear down the previous
  one, each tab switch, sleep or wake leaks a held connection until nothing
  new can start. This fits the symptom exactly, including that once stuck it
  stays stuck until the page is reloaded.
- **Backgrounding.** iOS suspends and resumes tabs aggressively; a stream
  resumed from suspension may never recover.
- **Network transitions.** Wi-Fi roaming or a radio sleep drops a held
  connection silently, which a short request would simply retry.

**The check that separates the first from the rest:** when the phone is
stuck, open the Network tab in Web Inspector and count pending
`stream.mjpg` entries. Several stacked up means connection exhaustion.

Whatever the precise cause, the structural point holds and is what the fix
rests on: a connection held open for minutes is fragile on a phone, and
short polled requests are not.

**Resolved the same evening, pending the phone.** The cause was the
server, not Safari: abandoned streams saturated the pool their waits ran
on, and a server restart cured it every time. The Camera tab now polls
`/snapshot.jpg` one frame at a time and holds no stream. The build,
the Chromium verification and the iPhone acceptance list are in
`docs/camera-black-screen-handoff.md`.

This matters more than it sounds. Every camera fix before this was verified
in desktop Chrome, a different engine, which is why several rounds of
"verified" work left the phone black. **The Camera tab has, as far as we can
tell, never worked in Safari on an iPhone.** The comment at the top of
`camera.js` assumes Safari supports MJPEG and only stalls after sleep or
wake; that assumption is the thing to distrust.

### The part that does not fit yet

Loading `/snapshot.jpg` directly in Safari on the phone — a single ordinary
JPEG, nothing multipart about it — also failed to render. Safari offered it
as a download, reported as 0 KB, and did the same for `/stream.mjpg`.

A plain JPEG failing is **not** explained by the multipart theory, and it
matters because the proposed fix is to poll that exact endpoint. An empty
download is also what a `401` from the passcode gate would produce, since
`app.py` returns a bodyless 401 for `/snapshot` and `/stream` paths rather
than redirecting. Whether that is what happened is unknown.

**Do not build the snapshot-polling change until this is resolved.** The
check is one line in the Web Inspector console on the phone, on the camera
page where the session cookie is definitely working:

```js
fetch('/snapshot.jpg?t=' + Date.now(), { cache: 'no-store' })
  .then(r => r.status + ' ' + r.headers.get('content-type') + ' ' + r.headers.get('X-Kona-State'))
```

and, to prove it decodes rather than merely arrives:

```js
var i = new Image();
i.onload = function () { console.log('OK', i.naturalWidth); };
i.onerror = function () { console.log('FAIL'); };
i.src = '/snapshot.jpg?t=' + Date.now();
```

`200 image/jpeg live` plus `OK 1280` means the fix is sound. Anything else
means the problem is larger than the streaming format and the plan changes.

### Unresolved: which Chrome worked

Chris reported the image coming through "in Chrome" immediately after
testing on the phone. It is not recorded whether that was Chrome on the
iPhone or the desktop browser already known to work. The difference is not
academic: Chrome on iOS is obliged to use WebKit, so if **iPhone** Chrome
renders the stream, the "WebKit cannot do multipart" conclusion is too
broad and the real cause is narrower. Settle this before writing code.

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

The Activity tab now uses only the confirmed fields above, plus the
sourced-but-unmeasured resting position (Round 5). Its free MVP map uses
Leaflet 1.9.4 and OpenStreetMap's standard raster tiles. On a walk it draws
Fi's live route; at rest it draws the resting position with the time of
Fi's last report; if Fi has stopped answering, the same fix is labelled
"Last seen"; with no fix at all it falls back to the verified
`homeLocation.position`, labelled Home. It never geocodes or invents a
coordinate.
