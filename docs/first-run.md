# First run — seeing the app on your laptop and phone

This is the plain-language version. Ten minutes, one time. After this,
updating is two commands.

## Why the camera runs at home and not on Vercel

The app's job is to show a camera that is in your house. Video goes from
the camera to a computer on your home Wi-Fi, and from there to your phone.
Vercel is a computer in a data center; it cannot see your camera, and its
functions cut off long-running video streams anyway. So *one machine at
home* serves the camera: your laptop or PC now, the Raspberry Pi later.

**Only the camera is tied to home.** Steps 1 to 3 below run on any machine
with internet, sitting anywhere — the app with a test pattern works on a
laptop in a coffee shop. So does the Fi collar probe in step 5, because Fi's
API is a normal internet service. It is step 4, the real camera, that needs
you and the machine on the same Wi-Fi as the camera.

"Clone" just means "download the code to this machine." GitHub is where the
code lives; your machine is where it runs.

## 1. One-time setup

Open a terminal:

- **Windows:** press Start, type `PowerShell`, open it.
- **Mac:** open Terminal (Cmd+Space, type "Terminal").

Install `uv` (it runs Python for you; you never touch Python directly):

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```bash
# Mac Terminal
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Close and reopen the terminal so `uv` is on the path. Then download the code:

```
git clone https://github.com/chris-suryo/kona-tracker.git
cd kona-tracker
uv sync
```

If `git` is missing on Windows, install it from https://git-scm.com/download/win
(defaults are fine) and reopen PowerShell. On Mac, running `git` the first
time offers to install it.

## 2. Set the passcode

Copy the example settings file and put a passcode in it:

```powershell
# Windows
Copy-Item .env.example .env
notepad .env
```

```bash
# Mac
cp .env.example .env
open -e .env
```

Set `KONA_PASSCODE=` to whatever you and your sister will type, and put any
long random string after `KONA_SECRET=`. Save and close. This file is private
to the machine and is never uploaded.

Digits are fine. Use **six or more** — the moment this goes through a tunnel,
the passcode is the only thing between the internet and the camera, and the
app prints a warning under six.

**Changing the passcode later** is the same edit plus a restart. Note that it
does *not* sign anyone out: logins are cookies signed with `KONA_SECRET`, not
the passcode. To force every phone to log in again, change `KONA_SECRET` too.

## 3. Run it (no camera needed, anywhere)

```
uv run kona serve --fake-camera
```

Leave that window open; it is the server. On the same laptop, open a browser
to **http://localhost:8000**. You should see the Kona Tracker login. Enter
the passcode. The Camera tab shows a test pattern; the Activity tab shows
the dial waiting for the collar until you do step 5.

To stop the server, press Ctrl+C in the terminal.

### Getting it onto your phone

Two ways. The tunnel is better unless you are certain you are on your own
home Wi-Fi.

**Option A: a tunnel (works anywhere, including cellular).** The laptop
dials out to Cloudflare, which hands back a public `https://` address. No
account, no domain, no router changes, and it works even on office or guest
Wi-Fi that blocks devices from talking to each other.

Leave `kona serve` running and open a **second** terminal tab:

```bash
brew install cloudflared                       # Mac, one time
cloudflared tunnel --url http://localhost:8000
```

It prints an address like `https://three-random-words.trycloudflare.com`.
Open that on your phone. Send it to your sister and it works on her phone
too, with no app to install.

Two things to know. The address changes every time you restart the tunnel;
a permanent one needs a Cloudflare account and a domain, which is a later
job. And **this puts the app on the public internet**, so the passcode is
now the only thing standing between a stranger and Kona's camera. Use a
real one, not `1234`.

**Option B: the local address (same Wi-Fi only).**

```bash
# Mac; if this prints nothing, try en1
ipconfig getifaddr en0
```

```powershell
# Windows: look for "IPv4 Address" under your Wi-Fi adapter
ipconfig
```

Open `http://<that address>:8000` in Safari. On Windows a firewall prompt
appears the first time; click **Allow** for private networks. If the page
never loads, the network is probably isolating devices from each other,
which is common on office and guest Wi-Fi. Use the tunnel instead.

### Add to Home Screen

With the page open in Safari, tap Share, then **Add to Home Screen**. You
get the paw icon and it opens full-screen with no address bar, like a real
app. This only works properly over `https://`, so use the tunnel rather
than the local address if you want the clean version.

Toggle your phone's dark mode to see the dark theme.

## 4. When the Tapo C120 arrives (this one needs you at home)

This is the only step that needs the home Wi-Fi: the camera and the machine
running the app must be on the same network.


1. Set it up in the Tapo app on the same Wi-Fi.
2. In the Tapo app, turn on **Third-Party Compatibility** (camera >
   Settings > Advanced Settings). Recent firmware refuses the camera
   account entirely without this, and the video will simply never connect.
3. In the same Advanced Settings, open **Camera Account** and create a
   username and password. This is what the app uses; it is not your
   TP-Link login.
4. In your router, give the camera a fixed IP (DHCP reservation). The Tapo
   app shows the camera's IP under Device Info.
5. Edit `.env`:

   ```
   KONA_CAMERA_SOURCE=rtsp
   KONA_RTSP_URL=rtsp://<camera-ip>:554/stream1
   KONA_RTSP_USER=<camera account user>
   KONA_RTSP_PASSWORD=<camera account password>
   ```

   (`/stream2` is a lighter stream if the picture stutters on the Pi.)

   For the switches on the Camera tab -- night vision, privacy mode, the
   status light -- add your TP-Link cloud password too:

   ```
   KONA_TAPO_USER=<the camera account username from step 3>
   KONA_TAPO_PASSWORD=<that camera account's password>
   KONA_TAPO_CLOUD_PASSWORD=<the password you sign in to the Tapo app with>
   ```

   That is a different password from the camera account, and it is the one
   recent firmware wants for the control API. Leave it blank and the
   switches are not shown; the video still works.
6. Test the camera once, then run for real:

   ```
   uv run kona camera-test
   uv run kona serve
   ```

   `camera-test` prints the frame size and fps, or the exact error with the
   password hidden. Paste that line into the next session if it fails.

   **Never run `camera-test` or `camera-doctor` while `kona serve` is
   running.** A USB webcam can be opened by one program at a time; two of
   them contending for it produces black frames that look exactly like a
   wedged device, and a running server keeps the camera for two minutes
   after the last viewer leaves (`KONA_CAMERA_IDLE_SECONDS`). Stop the
   server first. This cost most of a day on 2026-09-11.

## 4b. When the robot is on (needs the home Wi-Fi)

The TurboPi serves its camera on the LAN with no login, and the app reads
it exactly the way it reads the Tapo: from the PC, so the phone never needs
to reach the robot. Two checks, then two lines.

1. From the PC (PowerShell), prove the PC can reach the robot -- this is
   the one link nobody has tested yet:

   ```
   Test-NetConnection 10.0.0.3 -Port 8080
   ```

   `TcpTestSucceeded : True` is the answer. `False` with the robot on means
   the router is keeping the two apart, and no `.env` line will fix that.
2. Reserve `10.0.0.3` for the robot in the router (DHCP reservation), the
   same as the camera in step 4. Without it the address can change on the
   next reboot and the tab goes quiet without saying why.
3. Edit `.env`:

   ```
   KONA_ROBOT_SNAPSHOT_URL=http://10.0.0.3:8080/?action=snapshot
   ```

   Restart `kona serve`. A **Robot** tab appears next to Camera. It says
   **ROBOT OFF** whenever the robot is off or off the Wi-Fi, and the picture
   comes back on its own when it is on again -- no restart. With the URL
   blank there is no tab and nothing else changes.

   Driving is not in this tab yet, on purpose: the robot never stops on its
   own, so the stop-when-the-phone-vanishes watchdog has to be built on the
   robot first. `KONA_ROBOT_CONTROL_URL` and `KONA_ROBOT_TOKEN` are for that
   day.

## 5. When the Fi collar arrives (anywhere, any machine)

Fi's API is a normal internet service, so this does **not** need the home
network. All it needs is that Kona's collar is set up in the Fi app, plus
internet on whichever machine you run it from.

These are **your own Fi app login** — the email and password you use to sign
into the Fi app on your phone. Nobody hands them to you; they exist the moment
Kona's collar is paired. Add them to `.env`:

```
FI_EMAIL=<your Fi app email>
FI_PASSWORD=<your Fi app password>
```

Restart `kona serve` and the Activity tab fills in: last night's sleep in the
dial, naps, steps against her goal, and distance. If Fi cannot be reached the
page says so rather than showing a blank dial as though she slept nothing.

Then run the discovery once. This is separate from the app and answers the
questions the app cannot:

```
uv run kona probe
```

It logs in, asks Fi's API what it knows about Kona, and writes
`probe-out/summary.md` (private, gitignored, never uploaded on its own).
Read the "Step errors" and "Speculative field hints" sections, then paste
or attach that file in the next session.

**Please send that file.** Two things are still unknown, and only real
responses settle them. First, the units: the app assumes durations are
seconds, and shows the raw number instead of a total if a value comes back
outside a plausible 0-24 hours. Second, whether Fi exposes a sleep-quality
score, or barking and scratching counts, or only raw sleep and step totals.
The summary answers both, and the answer decides what else the page can
honestly show.

## Updating later

```
cd kona-tracker
git pull
uv sync
uv run kona serve
```

**On the Windows PC**, Application Control blocks `uv sync` (error 4551,
seen 2026-09-12). Two workarounds, depending on whether the update added a
dependency; the PR or session summary says which:

```powershell
uv run --no-sync kona serve          # nothing new to install
uv sync --no-build-isolation         # a new dependency (e.g. pytapo, 2026-09-13); untested here
```

If the second one is blocked too, paste the error into the next session
rather than working around it; the fix may be a policy exception, not a
command.

## If something goes wrong

- **Video is choppy.** Measured on the C270: at the default 1280x720 the
  app got 3.7 fps and ~88 KB per frame. Dropping to `KONA_CAMERA_WIDTH=640`
  and `KONA_CAMERA_HEIGHT=480` in `.env` trades detail for a much smoother
  picture, which is usually the better deal for watching a dog move around.
- `uv: command not found` → reopen the terminal after installing.
- **Windows: `uv run pytest` gives errors like `PermissionError: [WinError 5]
  Access is denied: ...\AppData\Local\Temp\pytest-of-<you>`.** Hit on the
  home PC on 2026-09-10. Every failing test is one that needs a scratch
  directory; pytest keeps its own under `%LOCALAPPDATA%\Temp` and Windows
  refuses to list it. Deleting the folder did not help, which points at
  Controlled Folder Access (Windows Security > Virus & threat protection >
  Ransomware protection) or a policy rather than stale permissions.

  **The app is not affected.** Nothing under `src/` uses a temp directory, so
  this can only ever break the test run, never `kona serve` or `kona probe`.

  Point pytest somewhere else, once:

  ```powershell
  [Environment]::SetEnvironmentVariable('PYTEST_ADDOPTS', "--basetemp=$env:USERPROFILE\.pytest-tmp", 'User')
  ```

  Reopen PowerShell; `uv run pytest -q` then works normally. Note that pytest
  **wipes whatever `--basetemp` points at** on every run, so give it a folder
  of its own and never a folder you keep things in.
- `KONA_PASSCODE is not set` → step 2 was skipped, or `.env` is in the wrong
  folder (it belongs next to `pyproject.toml`).
- **Camera worked yesterday, black today.** Hit on 2026-09-10/11. Run
  `uv run kona camera-doctor` (server stopped, nothing else using the
  camera). It tries every index against every backend and prints raw pixel
  statistics; the **sd** column is the one that decides. All-zero pixels with
  `sd 0.00` mean a closed shutter, a blocked lens, or a **wedged USB device**
  -- a webcam that another program grabbed and did not release cleanly can
  keep opening while delivering nothing. **Unplugging it and plugging it back
  in cleared it.** No code can fix that from inside; a replug is the fix.
  A genuinely dark room looks different: low mean but `sd` well above zero,
  because a real sensor always has read noise.
- **Camera tab says NO SIGNAL / OFFLINE, but `uv run kona cameras` found it.**
  Something else has the webcam open. A USB camera can be held by one program
  at a time, and `kona cameras` only checks that the device *opens*, not that
  frames arrive. Hit on the home PC 2026-09-10: **Windows Settings › Camera**
  was open, showing its preview, and that alone was enough. Close Settings,
  Teams, Zoom, the Windows Camera app, any browser tab on a call. Then
  `uv run kona camera-test` (server stopped) reads real frames and prints
  either the size and fps or the exact error.
- Phone can't reach the laptop → both on the same Wi-Fi? Firewall allowed?
  Guest networks often block device-to-device traffic.
- Anything else → copy the terminal text into the next session.
