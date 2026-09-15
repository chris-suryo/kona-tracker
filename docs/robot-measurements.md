# Three measurements only you can take

Written 2026-09-15, after the robot session answered our questions and left
three things open that need the actual robot in the actual room. Each one
below unblocks a decision somebody is currently guessing at.

Do them in this order. The first is a safety check and the other two both
want a charged pack, so do the charging while you do number one.

---

## 1. Does she strafe, or does she turn? (10 minutes, on a stand)

**Why it matters.** Pure `vy` — pushing the stick straight left or right —
is the *only* axis nobody has verified. The robot session's reasoning, which
is worth knowing because it tells you what you do **not** need to re-test:

> Rotation does not depend on roller orientation. Pure `omega` is
> differential drive — left wheels one way, right wheels the other — and that
> produces the same rotation whatever angle the rollers sit at. Same argument
> covers `vx`: all four wheels turning together is forward regardless of
> rollers. **`vy` is the only axis where roller orientation can bite.**

So forward and rotate are settled. Sideways is not, and a mirrored strafe
found at the edge of a step costs a robot.

**Most of it can be checked without her moving at all.** Put her on a box so
all four wheels are off the ground, open drive mode, leave the speed on the
lower setting, and push the stick **straight left**. Watch the wheels:

```
Correct (vy = +1, stick left):

    front-left  BACKWARD        front-right FORWARD
    rear-left   FORWARD         rear-right  BACKWARD
```

**Diagonals match, adjacent wheels oppose.** That is the pattern.

- **If you see that** → the mapping is right. Go to the floor test below.
- **If you see the left pair going one way and the right pair the other** →
  that is rotation, not strafe. Stop. That is a bug on the robot session's
  side, not ours, and it is a one-line fix once you tell them. Send them what
  you saw.

**Then the floor test, and only then.** Middle of a room, nothing to fall off,
speed on the lower setting, one short press left and one short press right.
You are checking one thing: does the body stay square and slide sideways, or
does it swing? If it slides the wrong way — left press, moves right — that is
also a one-line sign flip on their side, and nothing we built changes.

**Write down what you saw for each of the four:** stick left, stick right,
and the wheel pattern for each. That is what they need.

### While you are on the stand: the new look stick

Drive mode now has a **second joystick** on the right — the one you asked for
twice. It aims the camera and nothing else: it does not stop the robot when
you let go, and the camera stays where you point it (double-tap the centre dot
to level it). Two things to check while she is safely on a box:

- **Push it up. Does the camera look up?** Screen-up maps to tilt-up in our
  code, but the gateway's sign convention for tilt has never been checked on
  hardware. If it is inverted, that is one minus sign on our side, not theirs.
- **Push it right. Does the camera pan right?** Same question for pan.

Either being backwards is a two-minute fix; both being right means the whole
control is done.

---

## 2. Can `MAX_DUTY` go above 55? (10 minutes, needs a full charge)

**Why it matters.** Full throttle felt slow to you. Their Pi runs
`TURBOPI_MIN_DUTY=25` / `TURBOPI_MAX_DUTY=55` on a scale where 100 is the
documented top, so your full stick is asking for a little over half of what
the motors can do.

**Nobody knows whether 55 is the right number**, and the robot session said so
plainly rather than inventing a justification:

> Straight answer: **not thermal, not gearbox, not stall current, not
> brownout.** I have no data on any of those. The reasoning was only that
> Hiwonder's own scale is 0–100 and their demos cruise at 40–45. [...] I am
> not going to replace one guess with a more confident-sounding one.

**The failure they are actually worried about is not the motors, it is the
Pi.** Under load the 18650 pack sags; the expansion board regulates it to 5 V
for the Pi; if it cannot hold 5 V the Pi dies uncleanly, and that is the
SD-card-corruption case. So the number to watch is the battery voltage while
the motors are working.

**How to take it.** Charge the pack fully. Open drive mode — the telemetry
strip shows **Battery** live. Then drive sustained full throttle on carpet
(carpet, not hard floor: carpet is the higher load) for a good 20–30 seconds,
turns included, and watch that number while the wheels are actually loaded.

Write down:

- the resting voltage on a full pack, before you start
- the **lowest** number you see while driving hard
- whether the picture or the telemetry ever stutters or drops out

**Reading it.** The gateway refuses to drive below 7.0 V. If a *full* pack
already dips toward 7.0 under load, then 55 is not conservative, it is at the
limit, and raising it moves the brownout closer rather than making her faster.
If it barely moves, there is headroom and they can raise it.

Either way, their proposal is the good one and it needs this number first:

> I can derate the ceiling with battery voltage — full `MAX_DUTY` on a healthy
> pack, sliding down to something conservative as it approaches the refusal
> threshold — and report the value in force in `/telemetry` so your UI can
> show it.

We already read `min_duty`/`max_duty` from telemetry and never hardcode them,
so that lands in the drive page with no change on our side.

---

## 3. The camera, one variable at a time (20 minutes)

**Your premise and mine were both wrong**, and usefully so. There is no
mjpg-streamer and nothing is "launched with" a resolution: the stream is
`MjpgServer.py`, a Python `ThreadingHTTPServer` inside `TurboPi.py`, JPEG
encoding **every frame with OpenCV in Python**. What the source says today:

| | |
|---|---|
| Served resolution | **640×480**, by downscale |
| Frame rate ceiling | **20 fps**, from a hardcoded `time.sleep(0.05)` |
| Measured | 18.9 fps |
| JPEG quality | 70 on the stream, 100 on `?action=snapshot` |

Two findings that matter more than the resolution question:

1. **The capture resolution is never set.** `camera_open()` sets FOURCC, FPS
   and saturation and never `CAP_PROP_FRAME_WIDTH`/`HEIGHT`, so the camera
   runs at its default and every frame is then resized down to 640×480.
   Asking for 720p output *without* also asking the device for it would
   upscale: more CPU, no more detail.
2. **That downscale uses `INTER_NEAREST`** — the cheapest and worst filter,
   which point-samples and aliases visibly. `INTER_AREA` is the correct filter
   for shrinking and costs very little more. **This is a free quality win at
   the same resolution and the same bandwidth**, and it is probably a real
   part of why the picture looks bad.

They have written two scripts for this: `gateway/measure_camera.sh` and
`gateway/patch_camera_quality.py` (with `--filter area`, `--width/--height`,
and a verified `--revert`).

**Run them in this order, one variable at a time, and send them the table:**

1. Measure as-is.
2. `--filter area`, measure again. **Look at the picture here** — if this
   alone fixes it, stop; it costs nothing.
3. Only if you still want more detail: 720p, measure again.
4. Pick.

**One thing to be honest with yourself about while doing this.** My own
prediction is that raising the resolution will make the lag *worse*, not
better, and the arithmetic is not close: the 20 fps ceiling is a hardcoded
sleep, so 720p cannot buy frame rate, only cost it — 2.25× the pixels to
encode in Python and push over Wi-Fi.

**So the measurement that actually settles your complaint is a different
one, and it is thirty seconds:** drive her once on the **home Wi-Fi**, not
through Tailscale, and tell me whether the video is still terrible. On LTE
each frame costs a full round trip, so at 700 ms you are capped near 1.4 fps
no matter how good the camera is — the sensor would not be the problem. If
it is fine on Wi-Fi and bad on LTE, the fix is in the transport and touching
the camera is wasted effort.

---

## What to send back

For 1 and 2, the raw observations — what the wheels did, what the voltage
read. For 3, their script's table plus your own opinion of the picture,
which is the part no script measures. And the Wi-Fi-versus-LTE answer, which
decides whether there is a camera problem at all.
