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
| **Tailscale** | Free | Solid, but every viewer must install it and be added to your network. Your sister would need an account. |
| **Cloudflare Tunnel** | Free | The app makes an *outbound* connection; nothing is opened inbound. Viewers get a normal HTTPS URL. **This is the pick.** |

Cloudflare Tunnel wins because your sister just gets a link. The passcode
gate is what protects it, which is why Part 2 exists and is not optional.

---

## Part 0 — the gap to close first

**The session cookie is not marked `Secure`.** In
`src/kona_tracker/web/app.py` the login handler sets `httponly=True` and
`samesite="lax"` but no `secure=True`. Behind a Cloudflare tunnel the public
side is always HTTPS so in practice it is not exposed, but the same cookie is
also issued over plain HTTP on your LAN, and "in practice" is not a security
argument. It is a one-line change plus a test, and it should be made before
the URL goes to anyone.

Deliberately not fixed in the same pass that wrote this doc: it is a code
change with a test, not a doc edit. It is the first item in
`docs/next-session.md`.

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

### 3b. Keep the PC awake

**PowerShell as Administrator:**

```powershell
powercfg /change standby-timeout-ac 0     # never sleep on mains power
powercfg /change hibernate-timeout-ac 0   # never hibernate
powercfg /change monitor-timeout-ac 10    # screen off after 10 min is fine
```

The screen turning off is harmless. Sleep is not: a sleeping PC drops the
tunnel and the camera. Verify with `powercfg /query` rather than trusting
that the setting took — Windows power plans have a habit of being overridden
by the active plan.

### 3c. Start the app on boot

**This is the step I am least confident in, and the reason to do it last.**

The obvious approach — a Scheduled Task running as `SYSTEM` at startup — is
likely to break the camera. Windows gates camera access behind per-user
privacy settings (the same Settings ▸ Camera switch that already stole the
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
Register-ScheduledTask -TaskName "kona-tracker" -Action $action -Trigger $trigger
```

Then **reboot and check the camera tab from your phone**, not just that the
process is running. Confirming the task started is not confirming the camera
works. If the tab shows CHECK CAMERA after a reboot but works when you run
`uv run kona serve` by hand, the log-on-session theory is wrong and it needs
rethinking — say so rather than papering over it.

`cloudflared` gets the same treatment, or `cloudflared service install` if
the service account turns out to be fine for it (it has no camera to lose).

---

## When it breaks

- **Tunnel URL loads, app does not.** The tunnel is up and the app is down.
  Check the `kona serve` window; check the PC did not sleep.
- **Everyone logged out after a reboot.** `KONA_SECRET` is unset. Part 2,
  step 2.
- **Works on Wi-Fi, not on cellular.** You tested the LAN address, not the
  tunnel. Turn Wi-Fi off on the phone and use the `https://` URL.
- **Camera black after a reboot.** Two candidates and they need separating:
  the wedged-USB problem (`docs/first-run.md`, "worked yesterday, black
  today" — replug fixes it) or the log-on-session problem in 3c. Run
  `uv run kona camera-doctor` from a normal desktop PowerShell; if it reads
  usable there but the served page does not, it is 3c.
