# Production punchlist

Written 2026-09-11, at the end of the first day the app ran on Chris's
phone. Three requests from him, one diagnosis, a security pass, and an
honest list of what this still lacks. `docs/handoff.md` is the project;
this is the queue to production.

---

## A. The map is missing — diagnosed, and it is not the CDN

**Chris:** "The location has to always be up. I always have to have some
sort of map showing where it is. I don't know why I'm not seeing that."

There are two different map failures and they look nothing alike in code.
The one being hit is almost certainly the first.

### A1. There are no points to draw (most likely)

`views.py:100`:

```python
map_positions = positions or ((home_position,) if home_position else ())
```

and `positions` comes from `status.positions`, which `parse.py:265` fills
**only** from `ongoingActivity { ... on OngoingWalk { positions } }`.

That inline fragment is the whole story **for the query we currently
send**: we only ever ask for positions inside `... on OngoingWalk`. Kona asleep on the sofa is an `OngoingRest`, and we ask that fragment for
a place name only -- so `positions` comes back empty, and the only thing left is `home_position` from
`homeLocation { position { latitude longitude } }`.

If *that* is also absent, `map_points` is `[]` — and `activity.html` gates
the map container, the stylesheet and the script on `{% if map_points %}`
(lines 5, 112, 158). Empty list means **no map element is rendered at all**.
Not a blank box, not an error: nothing. Which matches what Chris sees.

**Confirm in ten seconds** — on the phone, while logged in, open
`/activity.json` and look at two keys:

- `"positions": []` and `"home_position": null` → this is A1. Expected.
- `"positions"` has entries, or `home_position` is set → it is **A2**.

### A2. The points exist but Leaflet never loads — **DONE 2026-09-11** (vendored, hash-pinned)

`activity.html` pulls `leaflet.css` and `leaflet.js` from **unpkg.com** with
SRI hashes. If unpkg is slow, blocked, or the hash mismatches, `L` is
undefined, the inline script throws, and the container stays a **blank
coloured box with no explanation** — measured in the sandbox with unpkg
blocked. Already queued in `next-session.md` §1: vendor Leaflet into
`web/static/`.

There is a second reason to vendor it. A render-blocking external stylesheet
that fails to arrive was measured earlier to **kill the cross-document view
transition**. `base.html` already loads Google Fonts; Leaflet's CSS is the
second one.

### CORRECTION 2026-09-11: Fi has her location always. We never asked for it.

> **BUILT 2026-09-11, awaiting the probe.** pytryfi's fragment confirmed the
> prime hypothesis on paper: `... on OngoingRest { position { latitude
> longitude } }` is what the Home Assistant tracker reads. The page now
> sends it as `pet_whereabouts`, a one-field document of its own, so a
> rejection costs the map point and nothing else; the map has a `Resting at
> Home · Last report HH:MM` tier, and `/activity.json` carries
> `rest_position`. The Fi API is unreachable from the cloud sandbox, so the
> field is **unmeasured until Chris runs** `uv run kona probe --out
> probe-out\round5` and reads `whereabouts:kona` in `summary.md`. Details
> in `docs/device-capabilities.md`, "Round 5".

An earlier draft of this file said "Fi returns position points only while
the dog is on a walk." **That is wrong, and Chris caught it.** The Fi app
opens straight to her location whether she is walking or asleep. The data is
obviously there; the limitation is in *our query*, not in Fi.

Look at what `pet_status` (`queries.py:279-282`) actually selects:

```
ongoingActivity { __typename start lastReportTimestamp areaName
  ... on OngoingRest { place { __typename id name } }
  ... on OngoingWalk { distance positions { ... position { latitude longitude } } } }
```

**We ask `OngoingWalk` for positions and we ask `OngoingRest` for a place
name and nothing else.** When she is resting we get the string "Home" and no
coordinates -- not because Fi withheld them, but because the query never
requested any. That is the same class of mistake as the sleep bug: the data
was always there, the selection set was wrong.

**The prime hypothesis, and it is cheap to test:** `OngoingRest` very likely
carries a `position` (or `lastLocation` / `currentLocation`) of its own. Add
it to the fragment and see. If the name is wrong, graphql-js answers with
`Cannot query field "position" on type "OngoingRest". Did you mean ...?` --
and that error is *allowlisted*, so it comes back in full rather than
redacted. This project has used validation errors as the schema
documentation twice now and it has worked both times.

Secondary candidates, already listed as speculative at `queries.py:134-136`
and never confirmed: `currentLocation`, `lastLocation`, `locationHistory` --
and on `device`, which already exposes `nextLocationUpdateExpectedBy`. A
field that tells us when the *next* location update is expected strongly
implies a field holding the *last* one.

Cross-check available: pytryfi and `sbabcock23/hass-tryfi` expose a Home
Assistant `device_tracker` with a live lat/lon that works whether or not the
dog is walking. Whatever field they read is the field we want. Read their
source -- that is what broke the sleep query open.

**This is the highest-value item in this file after D1.** It is not a
"design a fallback" problem, it is a "ask for the right field" problem, and
it is probably one line plus a parser change.

### Only if the field genuinely does not exist

Then, and only then, does the map need tiers that degrade honestly: live
track while walking, last known fix with its timestamp otherwise, and an
explicit "we do not know" panel rather than a blank box -- the same
discipline as the camera's NO SIGNAL. Never render a stale position styled
like a live one.

## B. Turn off pinch-to-zoom — **DONE 2026-09-11, page-wide, as asked**

> First built narrow: `touch-action: manipulation` on every tappable
> control, so a tap never double-tap-zooms. Chris then confirmed he meant
> zoom gone everywhere, after being told it is a WCAG 1.4.4 trade, so the
> viewport meta and a gesture blocker in `app.js` now stop page zoom on
> Android and iOS both. The map keeps its pinch. The decision, its cost and
> the two-edit revert are recorded in `docs/device-capabilities.md` §2b.


**Chris:** "I want to turn off the pinch-to-zoom."

`base.html:5` is currently:

```html
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
```

**Do not add `user-scalable=no`.** Two reasons, and the second is the one
that matters:

1. iOS Safari has ignored `user-scalable=no` since iOS 10. It will not work.
2. It is an accessibility failure (WCAG 1.4.4). Anyone who needs to zoom to
   read this page loses that permanently.

What is almost certainly the actual complaint is **accidental double-tap
zoom** when tapping tabs and buttons — that is the jarring one. The fix is
CSS, scoped to controls, not a global zoom ban:

```css
button, a, .tab, .dial { touch-action: manipulation; }
```

`app.css` already does exactly this in two places (lines 200, 212). The work
is auditing every interactive element for it. **Ask Chris to confirm** it is
double-tap that bothers him before disabling anything broader; if he truly
wants pinch gone page-wide, say plainly that it costs accessibility and let
him decide — it is his app.

Note the map is the one place pinch-zoom must **keep** working. Leaflet is
already initialised with `zoomControl: false, scrollWheelZoom: false` and a
bottom-right zoom control; do not let a global `touch-action` rule reach
inside `#kona-map`.

---

## C. Pull-to-refresh — **DONE 2026-09-11**

> Built in `static/app.js`: pull past 60 px at the top of the Activity page
> (map drags excluded), or come back to the app, and it fetches
> `/activity?fresh=1` -- which makes `FiService` ask Fi *on that request*,
> floored at 30 s so a thumb cannot become a request loop -- and swaps the
> rendered `#activity-body` in. One template renders both the page and the
> refresh, so there is no second copy of the numbers or the stale wording.
> No `location.reload()`. On failure the numbers stay with their time and
> the note says the refresh, not Fi, did not answer. `overscroll-behavior-y:
> contain` stops Safari's own pull-to-reload doubling up; that line is the
> one thing here that wants a real iPhone to confirm.


**Chris:** "I want to be able to scroll to pull down to refresh."

Straightforward, with one trap. iOS Safari has native pull-to-refresh that
reloads the page — but **only when the page is scrolled to the top and the
body is the scroll container.** If any wrapper has `overflow: hidden` or
`height: 100vh`, the gesture never reaches Safari and nothing happens. Check
that first; it may already work and simply be blocked by a layout rule.

For a custom one that works in standalone (Add to Home Screen) mode, where
native pull-to-refresh does not exist:

- `touchstart` / `touchmove` on the scroll container, only when
  `scrollTop === 0`, with a distance threshold around 70px and rubber-band
  resistance so it does not feel twitchy.
- Refresh the **data**, not the document: `fetch('/activity.json')` and
  repaint, so the camera stream is not torn down and re-established.
  A full `location.reload()` drops the MJPEG connection and costs seconds.
- Respect `prefers-reduced-motion` for the spinner — `app.css` already has a
  block for this and a test pins it.
- Make the failure honest. If the fetch fails, say the refresh failed and
  keep the old numbers visible with their timestamp. The page already has
  this exact discipline for stale Fi data; reuse the wording, do not invent
  a second vocabulary for the same situation.

This pairs naturally with the map: both want a "repaint from
`/activity.json` without reloading" path, which does not exist yet.

---

## D. Security pass, 2026-09-11

Read against the threat model that matters now: **a public URL, handed to a
sister, pointing at a live camera inside a house.** On a LAN most of this is
academic. Behind a tunnel it is not.

### D1. The lockout collapses behind the tunnel — **DONE 2026-09-11**

> Built: `KONA_TRUSTED_PROXY_HEADER` (unset by default), `client_key()` in
> `web/auth.py`, `Lockout` no longer grows with strangers, and `kona serve`
> passes `proxy_headers=False` to uvicorn -- whose *default* silently
> rewrites the client address from `X-Forwarded-For` for any 127.0.0.1 peer,
> which is the unconditional trust this item rules out. The header is
> believed only from the tunnel's own peer (`KONA_TRUSTED_PROXY_IPS`,
> loopback by default) -- the session's security review caught that a
> Wi-Fi visitor could otherwise pick a fresh bucket per guess. Tests cover
> both states. What remains is Chris's: set it behind the real tunnel.


`app.py:170`:

```python
key = request.client.host if request.client else "?"
```

Behind a Cloudflare tunnel, `cloudflared` connects to the app over
localhost. **Every visitor on earth arrives as `127.0.0.1`.** So all of them
share one lockout bucket, and the consequences run both ways:

- **Denial of service, trivially.** Any stranger who finds the URL and types
  five wrong passcodes locks out *everyone*, including Chris's sister, on a
  rolling 30-second basis. Held down, the app is permanently unusable.
- The per-attacker rate limit it was written to provide no longer exists.

The fix is to trust a forwarded-IP header **only when explicitly configured
to** (never by default — an unconditionally trusted `X-Forwarded-For` is
worse than none, since anyone can forge it). Cloudflare sets
`CF-Connecting-IP`. So: a `KONA_TRUSTED_PROXY_HEADER` setting, unset by
default, read only when set, falling back to `request.client.host`.

This is the single most important item in this file.

### D2. Session cookie is not `Secure` — **DONE 2026-09-11**

> Built: `KONA_SECURE_COOKIES` (off by default; a typo is a startup error,
> not a silent off), set and cleared with matching attributes, and a startup
> warning when the proxy header is on but this is not. Tests for both states.


Already written up in `remote-access.md` Part 0 and `next-session.md` §2b.
Needs a settings key rather than a hard-coded `True`, because
`secure=True` breaks LAN access over `http://192.168.x.x:8000` — the browser
silently refuses to send the cookie and the login just never takes.

### D3. No security headers at all — **DONE 2026-09-11**

> Built: CSP (`script-src 'self'`, no nonce -- every inline script became a
> file under `/static`, and the map's points travel as a JSON data block),
> `frame-ancestors 'none'` + `X-Frame-Options: DENY`, `Referrer-Policy:
> no-referrer`, `nosniff`, on every response including 401s and static
> files. Verified in a real Chromium with zero CSP violations (see the
> session wrap). No HSTS: the LAN address is http on purpose.


No `Content-Security-Policy`, `X-Frame-Options`, or `Referrer-Policy`
anywhere in `app.py`. For a public page with a camera on it:

- **`X-Frame-Options: DENY`** (or CSP `frame-ancestors 'none'`) — stops the
  page being framed by another site. Cheap, no downside here.
- **`Referrer-Policy: no-referrer`** — the app already accepts that
  OpenStreetMap's tile servers learn roughly where Kona is, a decision
  recorded and not to be re-litigated. It does not need to hand them a
  referrer as well.
- **CSP** is the valuable one and the most work, because the page currently
  uses inline `<script>` for the map and would need a nonce. Worth doing;
  not worth blocking D1 on.

### D4. The passcode is the entire security model

One shared code, no accounts, no per-device revocation. That is the right
call for two people and a dog, and it should stay — but it means:

- `MIN_SAFE_PASSCODE = 6` already warns, and the warning names this exact
  situation. Good.
- **There is no way to revoke one phone.** If a device is lost, the only
  remedy is rotating `KONA_SECRET`, which logs everyone out. Acceptable;
  worth Chris knowing rather than discovering.
- The cookie is `max_age` 30 days and re-issued only at login.

### D5. What held up well

Not everything needs fixing, and a security pass that only lists problems is
dishonest about the code:

- Passcode compared with `hmac.compare_digest` — constant time.
- The gate is **middleware, default-deny**, with an explicit two-item
  `PUBLIC_PATHS`. New routes are protected by default, which is the right
  direction to fail.
- `/stream`, `/snapshot`, `/avatar` correctly return **401 rather than a
  redirect**, because an `<img>` cannot follow a redirect to a login page.
- The avatar proxy caps at 5 MB, allowlists raster content types,
  **excludes SVG with a comment explaining that SVG carries script**, and
  sets `X-Content-Type-Options: nosniff`. That is genuinely careful work.
- `Settings.__repr__` masks every secret, so a stray print or traceback
  cannot leak `.env`.
- The Fi GraphQL error allowlist, and the redaction in `probe/redact.py`.

---

## E. What this still lacks, beyond what was asked

My own read, ordered by what would actually bite first.

1. **DONE 2026-09-11 (the app half):** `/healthz` reports camera state,
   last camera error kind, Fi freshness and reading age -- nothing else, and
   without touching Fi, since it is public. `docs/remote-access.md` 3d says
   where to point a free pinger. *Original:* Nothing watches the watcher. If `kona serve` dies at 2am, the page is
   simply unreachable and no one is told. `/healthz` exists and nothing
   polls it. The cheapest honest fix is an external uptime ping against the
   tunnel URL; a Windows service restart policy is the fuller one.
2. **DONE 2026-09-11:** `KONA_LOG_DIR` writes a rotating `kona.log` with
   uvicorn's access log plus every camera and Fi failure, attached at app
   startup because uvicorn's own logging config would otherwise swallow the
   access lines. *Original:* No logs worth reading after the fact. When Chris says "it was broken
   this morning", there is currently no way to find out what happened.
   Uvicorn's access log goes to a console window that closes.
3. **DONE 2026-09-11 (the remote-health half):** `/settings` now shows the
   camera source, state, last frame age, reconnects and the last problem in
   `camera-doctor`'s own words, from the same hub statistics. *Original:* The camera is one USB webcam in one room. Already known, but worth
   stating: the wedged-USB failure recurs, and nothing detects it remotely —
   `camera-doctor` must be run at the machine, which is exactly where Chris
   is not when he needs it. A "camera health" line on the settings page,
   reading the same statistics, would close that.
4. **CHANGED 2026-09-11, still owed the night test:** `frame_is_unusable`
   now uses the noise rule `_classify` documents -- all-zero or flat (sd
   below 1.0) is unusable; dark-but-noisy is a real, dark picture. The
   wedged signature (mean 0.00 / sd 0.00) is measured; the dark room is
   not, and one lights-off evening is still the verification. *Original:*
   `frame_is_unusable` has never been tested in a dark room. Threshold
   `mean <= 0.25`. Every run so far was in a lit room. "CHECK CAMERA" when
   the truth is "the light is off at night" is precisely the confident-wrong
   output this project refuses — and night is when a sleeping dog is most
   worth looking at. One evening's test. Carried over from
   `next-session.md` §2.
5. **DECIDED AND BUILT 2026-09-11:** times are Kona's. `pet_status` now
   selects Fi's `timezone` (accepted in round 3; its value is redacted by
   the probe so an IANA name is assumed), the page formats every HH:MM in
   it and labels them (`Updated 18:48 CDT`), and `/activity.json` says
   whose clock it used (`"clock": "fi" | "server"`). The fallback is the
   server's clock, unlabelled -- the same thing while the PC is at home.
   **Needs Chris:** Windows has no timezone database, so on the PC this
   only takes effect with the `tzdata` package (`uv add tzdata`); a
   dependency, so it is his call, and until then the JSON will say
   `"server"`. *Original:* No timezone handling that has been thought about. `views.py` uses
   `.astimezone()` — the *server's* local zone. Correct while the PC and the
   phone are in the same house. Wrong the moment Chris is on the road in
   another timezone, which is the entire point of `remote-access.md`. Decide
   deliberately whether times are shown in Kona's timezone (almost certainly
   yes — "last night" means her night) and make that explicit rather than
   incidental.
6. **`?preview=1` sample-data mode** needs auditing against the "never show
   data you do not have" rule in every state. Carried from
   `next-session.md` §5.
7. **The Fi refresh thread has no backoff.** `fi_refresh_seconds` is a flat
   300s. If Fi is down or the password is wrong, it re-asks every five
   minutes forever. Not urgent; worth a bounded backoff before this runs
   unattended for weeks.
