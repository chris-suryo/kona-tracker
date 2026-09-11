# Watching Kona from the road

How the app gets from "works on my Wi-Fi" to "works from anywhere."

> **Nothing in this file has been run.** Every other doc in `docs/` records
> something that was executed and observed. This one is a plan written from
> documentation, on a Linux sandbox with no Windows machine and no Cloudflare
> account attached. Treat each command as a proposal to verify, not a
> transcript. Where I am unsure, it says so. Correct this file as you go —
> the first person to actually run it owns making it true.

The trust ladder applies: **manual, then proven, then automated.** Do Part 1
today. Do not do Part 3 until Part 1 has survived a night.

---

## The shape of it

`uv run kona serve` binds `0.0.0.0:8000`, so anything on your Wi-Fi can
reach it. The internet cannot: your router does not forward that port, and
it should not. Three ways across that line:

| | What it costs | Why not |
|---|---|---|
| **Port forwarding** | Free | Opens a port on your home router to the whole internet, permanently, pointed at a webcam. No. |
| **Tailscale** | Free | Solid, but every viewer must install it and be added to your network. Your sister would need an account. **That objection is about handing someone else a link — for watching your own dog on your own phone it is the simpler option. See "Tailscale, for yourself" below.** |
| **Cloudflare Tunnel** | Free | The app makes an *outbound* connection; nothing is opened inbound. Viewers get a normal HTTPS URL. **This is the pick.** |

Cloudflare Tunnel wins because your sister just gets a link. The passcode
gate is what protects it, which is why Part 2 exists and is not optional.

**What it costs in data.** The tunnel carries the video, so watching over
cellular spends cellular data: roughly 340 KB/s, about 1.2 GB an hour, per
viewer at the default 1280x720. Nobody has measured it on a real carrier
connection yet. `docs/scaling-limits.md` §1 has the numbers and the two
knobs that exist today.

---

## Tailscale, for yourself

The table above picks Cloudflare because your sister gets a plain link. When
the viewer is *you*, that reason evaporates and Tailscale is the better tool:
nothing in the path but your own devices, and **the address never changes**.

Reach for it when it is one person on their own phone, or when the quick
tunnel is down and you need something working now -- which is exactly what
happened on 2026-09-11, an hour before dinner.

### 1. Three lines in `.env`

```
KONA_SECURE_COOKIES=false
KONA_TRUSTED_PROXY_HEADER=
KONA_KEEP_AWAKE=true
```

**The first one is not optional.** Tailscale serves plain
`http://100.x.y.z:8000`, and a browser will not send a Secure cookie over
http. Leave it `true` and the symptom is a correct passcode bouncing straight
back to the login screen, with nothing in the log and nothing on screen to
tell you why.

The second goes blank because there is no Cloudflare in front of you any
more. The third keeps the PC awake while you are out; without it the machine
sleeps and there is nothing to watch.

### 2. Restart `kona serve`

Settings are read **once, at startup**. Editing `.env` under a running server
changes nothing, and the failure is invisible -- it behaves exactly like the
old settings because it *is* the old settings. Ctrl+C and start it again.

### 3. Find the address, once

```powershell
tailscale ip -4
```

A `100.x.y.z` address. Unlike the quick tunnel's random hostname, this one is
stable -- write it down and it keeps working.

### 4. On the phone

Install Tailscale, sign in to the **same account**, and make sure the VPN
toggle is on. Then turn Wi-Fi **off** and open:

```
http://100.x.y.z:8000
```

Wi-Fi off is the point. On Wi-Fi you are testing your LAN, not the tunnel.

### 5. If the page never loads

Windows Firewall, almost always: it treats the Tailscale interface as its own
network, so allowing the app on your LAN does not cover it. **PowerShell as
Administrator:**

```powershell
New-NetFirewallRule -DisplayName "kona-tracker 8000" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

### 6. Switching back to Cloudflare

**Set `KONA_SECURE_COOKIES=true` again before you use a tunnel**, and restart.
Forget, and the session cookie travels a public HTTPS URL without the Secure
flag -- the one setting here whose wrong value is a security problem rather
than an inconvenience.

---

## Part 0 — two settings the tunnel needs (built 2026-09-11)

Both live in `.env`, both are **off by default**, and both are wrong to turn
on for a plain LAN. Turn them on together when the app gets its HTTPS URL.

**`KONA_TRUSTED_PROXY_HEADER=CF-Connecting-IP`.** `cloudflared` connects to
the app over localhost, so without this every visitor on earth arrives as
`127.0.0.1` and shares one login lockout: five wrong guesses from a stranger
would lock you and your sister out too. With it, the lockout counts per
visitor address, read from the header Cloudflare sets. It is deliberately
not `X-Forwarded-For`: anyone can send that header and pick their own
bucket. `kona serve` also tells uvicorn *not* to honour forwarded headers on
its own, so this setting is the only path. And the header is believed only
when the request comes from the tunnel's own address
(`KONA_TRUSTED_PROXY_IPS`, loopback by default): port 8000 stays open on
the Wi-Fi next to the tunnel, and a visitor there who sends a fresh
`CF-Connecting-IP` per guess must not get a fresh lockout bucket per guess.
The security review of 2026-09-11 caught exactly that gap.

**`KONA_SECURE_COOKIES=true`.** Marks the session cookie `Secure` so it only
travels over HTTPS. Do not set this while you still open
`http://192.168.x.x:8000` on the LAN -- the browser silently refuses to send
a Secure cookie over http and the login just never takes. The app warns on
startup if the proxy header is set and this is not.

Nothing here has been run against a real tunnel yet; the tests cover both
states of each setting, not Cloudflare's behaviour. Part 1 is where that
gets proven.

---

## Part 1 — prove it manually (15 minutes, do this first)

This gives you a working public URL today with no domain and no account.
The URL is random and **changes every restart**, which is exactly why this
is the proving step and not the finished setup.

**PowerShell, on the Windows PC:**

```powershell
winget install --id Cloudflare.cloudflared
```

Reopen PowerShell so the new `cloudflared` is on your PATH. Then, in one
window, start the app:

```powershell
cd C:\Users\harim\kona-tracker
uv run kona serve
```

In a **second** PowerShell window:

```powershell
cloudflared tunnel --url http://localhost:8000
```

It prints a banner with a URL like `https://random-words-here.trycloudflare.com`.
Open that on your phone **over cellular, with Wi-Fi off** — that is the only
test that proves it left your house. You should get the passcode screen.

If that works, you have remote access. Everything below is making it
permanent and less ugly.

---

## Part 2 — make it safe to hand out

The moment the app has a public URL, the threat model changes. On your own
Wi-Fi, the passcode keeps out nobody who matters. On the internet it is the
*only* thing between a stranger and a live camera in your house.

1. **Lengthen the passcode.** `load_settings` already warns below 6
   characters and names this exact situation. A 4-digit code is 10,000
   guesses. Use a phrase — `kona-sleeps-sideways` is easier to text your
   sister than `8812` is to defend.
2. **Set `KONA_SECRET`.** If it is unset the app generates one per run and
   prints that it did. Every restart logs everyone out. On an always-on box
   that restarts on reboot, that means re-entering the passcode on every
   phone after every Windows update.

   ```powershell
   # PowerShell: generate one and paste it into .env as KONA_SECRET=...
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
3. **Know what the lockout does and does not do.** `lockout_attempts=5`,
   `lockout_seconds=30` — five wrong tries, then a 30-second pause. That
   defeats a human guessing. It does not defeat a patient script, because
   the pause is short and the counter is per-key in memory. It is a speed
   bump, not a lock. The passcode length is the real control.
4. **Never commit `.env`.** It now holds a Fi password, a passcode and a
   session secret. It is gitignored; keep it that way.

**Unverified and worth checking:** whether a Cloudflare quick tunnel leaves
the URL discoverable. I do not know whether `*.trycloudflare.com` hostnames
are enumerable or appear in certificate transparency logs in a way that
invites drive-by scanning. Assume the URL is not a secret and let the
passcode do the work.

---

## Part 3 — make it permanent

Only after Part 1 has worked and Part 2 is done.

### 3a. A named tunnel with a stable URL

This is the part that needs **a domain name on Cloudflare** (a cheap `.com`
moved to Cloudflare's free DNS, or one bought through them). Without a
domain you are stuck with the random quick-tunnel URL, which is usable but
changes on every restart.

```powershell
cloudflared tunnel login          # opens a browser; pick your domain
cloudflared tunnel create kona    # prints a tunnel UUID and writes a .json credential
cloudflared tunnel route dns kona kona.yourdomain.com
```

Then a config file at `C:\Users\harim\.cloudflared\config.yml`:

```yaml
tunnel: kona
credentials-file: C:\Users\harim\.cloudflared\<TUNNEL-UUID>.json

ingress:
  - hostname: kona.yourdomain.com
    service: http://localhost:8000
  - service: http_status:404
```

Test it in the foreground before installing it as a service:

```powershell
cloudflared tunnel run kona
```

**Unverified:** the exact `credentials-file` path format on Windows, and
whether `cloudflared service install` picks up a per-user config from
`%USERPROFILE%\.cloudflared\` or wants it elsewhere. Check the banner output.

### 3b. Keep the PC awake, without paying for it around the clock

The old advice here was `powercfg /change standby-timeout-ac 0`: never
sleep, ever. That works and it is the wrong tool. It is a setting you forget
you made, and an idle desktop left awake all year is real money.

Rough figures. Rates and machines vary, so treat these as the shape of the
problem rather than your bill; measure with a plug meter if you want the
real number. Assumes electricity at 17 cents per kWh and the screen asleep.

| Host, awake all year | Watts, idle | Per year | Per month |
|---|---|---|---|
| Desktop PC | 70 | 613 kWh, about $104 | about $8.70 |
| Laptop, lid closed | 20 | 175 kWh, about $30 | about $2.50 |
| Raspberry Pi 5 with the webcam | 5 | 44 kWh, about $7 | under $1 |

So the Pi is not just tidier, it is roughly a tenth the running cost of the
desktop. That is the argument for moving once it is unboxed.

**Until then, do not switch sleep off.** Set `KONA_KEEP_AWAKE=true` in
`.env` instead. The app then asks Windows to hold off sleep *while it is
running*, and releases the hold the moment it stops, so:

- Sleep stays enabled in your power plan. Nothing is permanently changed.
- The machine is only awake for the hours you are actually serving Kona.
  Stop the app when you are home and the PC sleeps like it always did.
- The **screen still sleeps**, which is most of the idle draw. The app never
  asks for the display.
- If the request is refused, or you are not on Windows, `kona serve` says so
  on startup rather than leaving you believing the page will be reachable.

The one thing to still set by hand is the lid, if this ends up on a laptop,
because closing it sleeps the machine whatever a running program asks for:

```powershell
# PowerShell as Administrator. 0 = do nothing when the lid closes, on mains.
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0
powercfg /setactive SCHEME_CURRENT
```

Verify with `powercfg /query` rather than trusting that it took: Windows
power plans have a habit of being overridden by the active plan.

**Unverified:** none of this has been run on Chris's PC. The keep-awake code
path is Windows-only and the sandbox that wrote it is Linux, so the tests
cover the refusal path, not the success path. First person to run it owns
making this true.

### 3c. Start the app on boot

**This is the step I am least confident in, and the reason to do it last.**

The obvious approach — a Scheduled Task running as `SYSTEM` at startup — is
likely to break the camera. Windows gates camera access behind per-user
privacy settings (the same Settings > Camera switch that already stole the
webcam from us once), and a service-account session is not a desktop
session. A task that runs, reports success, and serves a dead camera tab is
the worst possible outcome.

The safer shape, to try first: set the PC to log in automatically to your
user, and run the task **at log on as that user**, not at startup as SYSTEM.

```powershell
# PowerShell as Administrator. Adjust the uv path if `where.exe uv` differs.
$action  = New-ScheduledTaskAction -Execute "$env:USERPROFILE\.local\bin\uv.exe" `
           -Argument "run kona serve" -WorkingDirectory "C:\Users\harim\kona-tracker"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
           -ExecutionTimeLimit ([TimeSpan]::Zero) `
           -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
           -MultipleInstances IgnoreNew `
           -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
           -StartWhenAvailable
Register-ScheduledTask -TaskName "kona-tracker" -Action $action -Trigger $trigger `
           -Settings $settings
```

Three of those settings are not decoration, and leaving any of them out
produces a task that looks fine and is not:

1. **`-ExecutionTimeLimit ([TimeSpan]::Zero)`.** Scheduled tasks default to
   being killed after three days. Without this the app dies every 72 hours
   and you would be hunting a phantom.
2. **`-RestartCount` / `-RestartInterval`.** Otherwise a crash is permanent
   until the next log-on. Three restarts a minute apart is a speed bump, not
   a supervisor; 3d is what tells you it ran out of retries.
3. **`-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries`.** On a laptop,
   the default is to refuse to start and to stop when unplugged.

Then **reboot and check the camera tab from your phone**, not just that the
task started. Confirming the task started is not confirming the camera
works. If the tab shows CHECK CAMERA after a reboot but works when you run
`uv run kona serve` by hand, the log-on-session theory is wrong and it needs
rethinking — say so rather than papering over it.

`cloudflared` gets the same treatment, or `cloudflared service install` if
the service account turns out to be fine for it (it has no camera to lose).

**Unverified:** every command in this section. The settings names come from
`New-ScheduledTaskSettingsSet`'s documented parameters, not from a run on a
real machine. If PowerShell rejects `-RestartCount`, drop that pair and rely
on 3d to tell you when it is down.

### 3d. Something has to watch it (built 2026-09-11, not yet pointed at a tunnel)

If `kona serve` dies at 2am the page is simply unreachable and nobody is
told. `/healthz` is public and answers without touching Fi or the camera:

```json
{"status": "ok", "camera": "idle", "camera_error": null, "fi": "ok", "fi_age_s": 212}
```

`camera` is `idle` whenever nobody is watching (the webcam is released
after `KONA_CAMERA_IDLE_SECONDS`, two minutes by default) -- that is normal; `disconnected` with a
`camera_error` of `open`, `hung` or `black_frame` is the wedged-USB
signature and means a replug. `fi` is `stale` when Fi has stopped
answering; `fi_age_s` says how old the numbers on the page are.

There are two shapes of this, and today only one of them can work.

**A push, which works right now.** Set `KONA_HEARTBEAT_URL` to a ping URL
from healthchecks.io's free tier. The app pings it every five minutes, and
the service emails you when the pings *stop*. That is the only way to hear
about the failures that silence the machine itself: sleep, crash, power cut,
a dropped connection. Nothing running on the PC can report those, because
the PC is what died.

It works today because it needs no inbound reachability and no fixed
address, so the quick tunnel's URL changing on every restart does not
matter. Set it up in about two minutes:

1. Make a free healthchecks.io account and add a check named `kona`.
2. Set its period to 5 minutes and its grace to 5 minutes.
3. Copy the ping URL into `.env` as `KONA_HEARTBEAT_URL=`.
4. Restart `kona serve`. The first ping goes out immediately, so the check
   should turn green while you are still looking at it. If it does not,
   the reason is in the log, not on the page.

The ping body carries the same summary `/healthz` serves, so the check's
event log shows what the app was doing each time. A wedged camera does
**not** fail the heartbeat, on purpose: that alarm already exists on
`/settings`, and folding it in here would turn one clear alarm into a flappy
one you end up muting.

**A poll, once there is a domain.** Point UptimeRobot or Better Stack at
`https://kona.yourdomain.com/healthz`, alerting on anything but HTTP 200.
This adds what the push cannot see: whether your sister can actually reach
the app from outside. Worth having in addition, not instead. It is pointless
before a named tunnel, since there is no stable URL to give it.

Set `KONA_LOG_DIR=C:\Users\harim\kona-tracker\logs` in `.env` so the
access log and every camera or Fi failure land in a rotating `kona.log`
that survives the PowerShell window closing. On Windows a rotation can
fail with a PermissionError while another program (an editor, a tail) holds
the file open; that is printed, not fatal.

---

## When it breaks

- **Tunnel URL loads, app does not.** The tunnel is up and the app is down.
  Check the `kona serve` window; check the PC did not sleep.
- **Everyone logged out after a reboot.** `KONA_SECRET` is unset. Part 2,
  step 2.
- **Works on Wi-Fi, not on cellular.** You tested the LAN address, not the
  tunnel. Turn Wi-Fi off on the phone and use the `https://` URL.
- **The right passcode bounces back to the login screen, no error anywhere.**
  `KONA_SECURE_COOKIES=true` while you are on an http address -- the LAN or
  Tailscale. The browser silently refuses to send a Secure cookie over http,
  so the session never takes. Set it false, restart, and see "Tailscale, for
  yourself" above.
- **`cloudflared` times out: `Post "https://api.trycloudflare.com/tunnel":
  context deadline exceeded`.** Hit on 2026-09-11 after the same machine had
  run a tunnel successfully a few hours earlier. What was established: DNS
  resolved (A and AAAA), and `curl` reached the host over **both** IPv4 and
  IPv6, returning 405 each time -- so the network path was fine and
  `cloudflared` alone was hanging. An IPv6 theory was tested and disproved.
  A downgrade from 2026.9.0 to 2026.8.3 was attempted and **failed with MSI
  exit 1603**, so the binary never changed: the version-regression theory is
  **untested, not disproven**, though a community report against 2026.9.0
  exists. Rate limiting on a busy IP is the other candidate; the cheap way to
  split them is to retry from a phone hotspot, which changes the public IP and
  nothing else. **No cause was ever established.** The evening was rescued by
  switching to Tailscale, not by fixing this.
- **It works on cellular but eats data.** Expected, not a fault. See
  `docs/scaling-limits.md` §1; `KONA_CAMERA_WIDTH`/`HEIGHT` in `.env` are
  the levers that exist without a code change.
- **Camera black after a reboot.** Two candidates and they need separating:
  the wedged-USB problem (`docs/first-run.md`, "worked yesterday, black
  today" — replug fixes it) or the log-on-session problem in 3c. Run
  `uv run kona camera-doctor` from a normal desktop PowerShell; if it reads
  usable there but the served page does not, it is 3c.
