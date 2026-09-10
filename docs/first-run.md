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

Set `KONA_PASSCODE=` to whatever you and your sister will type (e.g. `4242`),
and put any long random string after `KONA_SECRET=`. Save and close. This
file is private to the machine and is never uploaded.

## 3. Run it (no camera needed, anywhere)

```
uv run kona serve --fake-camera
```

Leave that window open; it is the server. On the same laptop, open a browser
to **http://localhost:8000**. You should see the Kona Tracker login. Enter
the passcode. The Camera tab shows a test pattern; the Activity tab shows
the dial waiting for the collar.

**On your iPhone** (joined to the same network as the laptop, whichever
network that is): find the laptop's address, then open it.

```powershell
# Windows: look for "IPv4 Address" under your Wi-Fi adapter
ipconfig
```

```bash
# Mac
ipconfig getifaddr en0
```

Open `http://<that address>:8000` in Safari. The first time on Windows, a
firewall prompt appears; click **Allow** for private networks. Toggle the
phone's dark mode to see the dark variant. Tap Share > Add to Home Screen
and it behaves like an app.

To stop the server, press Ctrl+C in the terminal.

## 4. When the Tapo C120 arrives (this one needs you at home)

This is the only step that needs the home Wi-Fi: the camera and the machine
running the app must be on the same network.


1. Set it up in the Tapo app on the same Wi-Fi.
2. In the Tapo app: the camera > Settings > **Advanced Settings** >
   **Camera Account**. Create a username and password. This is what the app
   uses; it is not your TP-Link login.
3. In your router, give the camera a fixed IP (DHCP reservation). The Tapo
   app shows the camera's IP under Device Info.
4. Edit `.env`:

   ```
   KONA_CAMERA_SOURCE=rtsp
   KONA_RTSP_URL=rtsp://<camera-ip>:554/stream1
   KONA_RTSP_USER=<camera account user>
   KONA_RTSP_PASSWORD=<camera account password>
   ```

   (`/stream2` is a lighter stream if the picture stutters on the Pi.)
5. Test the camera once, then run for real:

   ```
   uv run kona camera-test
   uv run kona serve
   ```

   `camera-test` prints the frame size and fps, or the exact error with the
   password hidden. Paste that line into the next session if it fails.

## 5. When the Fi collar arrives (anywhere, any machine)

Fi's API is a normal internet service, so this does **not** need the home
network. All it needs is that Kona's collar is set up in the Fi app, plus
internet on whichever machine you run it from.

Add to `.env`:

```
FI_EMAIL=<your Fi app email>
FI_PASSWORD=<your Fi app password>
```

Then run the discovery once:

```
uv run kona probe
```

It logs in, asks Fi's API what it knows about Kona, and writes
`probe-out/summary.md` (private, gitignored, never uploaded on its own).
Read the "Step errors" and "Speculative field hints" sections, then paste
or attach that file in the next session.

**This is the step that unblocks the Activity tab.** Nobody yet knows
whether Fi exposes a sleep-quality score, or barking and scratching counts,
or only raw sleep and step totals. The summary answers that, and the answer
decides what the dial and the numbers underneath it can honestly show.

## Updating later

```
cd kona-tracker
git pull
uv sync
uv run kona serve
```

## If something goes wrong

- `uv: command not found` → reopen the terminal after installing.
- `KONA_PASSCODE is not set` → step 2 was skipped, or `.env` is in the wrong
  folder (it belongs next to `pyproject.toml`).
- Phone can't reach the laptop → both on the same Wi-Fi? Firewall allowed?
  Guest networks often block device-to-device traffic.
- Anything else → copy the terminal text into the next session.
