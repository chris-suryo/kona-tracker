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

That inline fragment is the whole story: **Fi returns position points only
while the dog is on a walk.** Kona asleep on the sofa is an `OngoingRest`
(or whatever Fi calls it), which carries no `positions` at all. So
`positions` is empty, and the only thing left is `home_position` from
`homeLocation { position { latitude longitude } }`.

If *that* is also absent, `map_points` is `[]` — and `activity.html` gates
the map container, the stylesheet and the script on `{% if map_points %}`
(lines 5, 112, 158). Empty list means **no map element is rendered at all**.
Not a blank box, not an error: nothing. Which matches what Chris sees.

**Confirm in ten seconds** — on the phone, while logged in, open
`/activity.json` and look at two keys:

- `"positions": []` and `"home_position": null` → this is A1. Expected.
- `"positions"` has entries, or `home_position` is set → it is **A2**.

### A2. The points exist but Leaflet never loads

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

### What "always up" actually requires

This is a real feature, not a bug fix, and it needs a decision.

Fi gives us a live track **only during a walk**. The rest of the time the
honest answers are "at home" (from `homeLocation`) or "we do not know".
A map that always shows *something* must not imply a live fix it does not
have. Three tiers, in the project's usual discipline:

1. **Walking** — the real track. Already built.
2. **Not walking, `homeLocation` known** — a single pin at home, labelled as
   home and as of when, never styled like a live fix. Needs `home_position`
   to actually come back; verify in `/activity.json` first.
3. **Neither** — a map-shaped panel that says so, the same way the camera
   says NO SIGNAL. Not a blank box.

**And there may be a better field we have never asked for.**
`queries.py:134-136` lists `locationHistory`, `currentLocation` and
`lastLocation` as *speculative* — candidates the probe has never confirmed.
If `lastLocation` exists, tier 2 becomes a real last-known fix with a
timestamp instead of a static home pin, which is much closer to what Chris
is asking for. **Run probe round 4 before designing tier 2.**

---

## B. Turn off pinch-to-zoom

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

## C. Pull-to-refresh

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

### D1. The lockout collapses behind the tunnel — **fix before going public**

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

### D2. Session cookie is not `Secure`

Already written up in `remote-access.md` Part 0 and `next-session.md` §2b.
Needs a settings key rather than a hard-coded `True`, because
`secure=True` breaks LAN access over `http://192.168.x.x:8000` — the browser
silently refuses to send the cookie and the login just never takes.

### D3. No security headers at all

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

1. **Nothing watches the watcher.** If `kona serve` dies at 2am, the page is
   simply unreachable and no one is told. `/healthz` exists and nothing
   polls it. The cheapest honest fix is an external uptime ping against the
   tunnel URL; a Windows service restart policy is the fuller one.
2. **No logs worth reading after the fact.** When Chris says "it was broken
   this morning", there is currently no way to find out what happened.
   Uvicorn's access log goes to a console window that closes.
3. **The camera is one USB webcam in one room.** Already known, but worth
   stating: the wedged-USB failure recurs, and nothing detects it remotely —
   `camera-doctor` must be run at the machine, which is exactly where Chris
   is not when he needs it. A "camera health" line on the settings page,
   reading the same statistics, would close that.
4. **`frame_is_unusable` has never been tested in a dark room.** Threshold
   `mean <= 0.25`. Every run so far was in a lit room. "CHECK CAMERA" when
   the truth is "the light is off at night" is precisely the confident-wrong
   output this project refuses — and night is when a sleeping dog is most
   worth looking at. One evening's test. Carried over from
   `next-session.md` §2.
5. **No timezone handling that has been thought about.** `views.py` uses
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
