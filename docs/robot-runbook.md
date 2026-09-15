# The robot will not connect. Now what?

`docs/robot-bringup.md` is the one-time setup. This is the everyday one: it
was on yesterday and today the tab says **ROBOT OFF**.

**Run this first.** It checks the layers in order and the first `FAIL` is the
answer:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\robot_check.ps1
```

Add `-Address 10.0.0.42` if the Pi has moved.

---

## Why one message covers four faults

The Robot tab can only say what it observes, which is "no picture arrived".
Underneath that there are four different things, and they need different
fixes. In the order the script checks them:

| Layer | Symptom when it is the one that is down | Fix |
|---|---|---|
| **Network** | Ping fails | The address moved. See below |
| **Camera** (`turbopi`, port 8080) | Ping fine, no picture, driving works | `sudo systemctl restart turbopi` |
| **Gateway** (`turbopi-gateway`, port 9031) | Picture fine, Drive page 404s or times out | `sudo systemctl restart turbopi-gateway` |
| **`TurboPi.py`** underneath the gateway | Everything looks up; `/health` says `turbopi_unreachable` | `sudo systemctl restart turbopi` |

That last one is the nasty one: the gateway stays up and answers cheerfully
while nothing it says can reach the motors, because `TurboPi.py` owns the
port the wheels are actually on.

**A green light on the Pi means it has power. It says nothing about whether
any of these four are running.**

## The address moving is the usual cause

Without a DHCP reservation the router is free to hand the Pi a different
address on any reboot, and then every layer above fails at once for a reason
that has nothing to do with the robot.

```powershell
arp -a | Select-String "10.0.0"
```

or try `http://turbopi.local:8080/?action=snapshot` in a browser — mDNS
usually still finds it.

**Fix it once, properly:** reserve `10.0.0.3` for the robot's MAC in the
router's DHCP settings. Everything else in this document is downstream of
that not being done.

## Turning it on while you are out

**You cannot, with software, and no script here will pretend otherwise.** A
Raspberry Pi with no power draws no power; there is nothing listening to wake.
Wake-on-LAN does not apply either — that needs a network card that stays
energised while the machine is off, and the Pi's does not.

If you want the robot startable from away, the answer is hardware: **a smart
plug on its charger**. Then the sequence is plug on, wait about 45 seconds for
the Pi to boot and both services to come up, then `robot_check.ps1`.

Two things to know before relying on that:

- The robot runs on **two 18650 cells** whose runtime nobody has measured.
  Sitting on the charger is the only state it can be left in indefinitely.
- Driving it with nobody in the room is a different risk from driving it with
  someone watching. The watchdog stops the wheels within half a second of
  commands stopping, and that is a guard against a lost connection — not
  against a robot tipping down a step with nobody there to pick it up.

## The front lights work when nothing else does

The two front RGBs are on the ultrasonic module at **I2C `0x77`**, not on the
serial bus that owns the motors, and the gateway writes them directly. So
`POST /led` answers while `/health` says `turbopi: false` — it is the one
control on the Robot tab that survives the robot's own software being down.

Two consequences worth knowing:

- **Lights on but the robot will not move** is a real and informative state,
  not a contradiction. It says the gateway and the Pi are fine and
  `TurboPi.py` is the thing that died: `sudo systemctl restart turbopi`.
- **`Functions/Avoidance.py` writes these same LEDs**, and `TurboPi.py` turns
  them off at startup. While the obstacle-avoidance demo is running it will
  fight the app for them and win intermittently. A colour is three sequential
  byte writes, so a write interleaved with the demo's can show a wrong colour
  for one frame. Cosmetic, not dangerous.

Current draw is roughly 120 mA at full white [INFERRED by the robot session,
not measured] against motors that draw amps, so there is no ceiling on our
side. If one is ever wanted it belongs on the **sum** of the three channels,
since white is all three lit at once.

## Driving over Tailscale, from away

**Built 2026-09-15, untested on real hardware.** Before that it stuttered, and
that was measured rather than guessed: at a 700 ms round trip the robot session
recorded the watchdog firing **seven times in six seconds** with the stick held
down, because the HTTP client can only send as fast as the round trip allows.

The fix is a WebSocket on the **phone → PC** leg, which is the slow one. The
PC → Pi leg is wired Ethernet at about 1 ms and stays on plain HTTP at 200 ms
against the 500 ms TTL, which is what the robot session asked us to keep; their
own `/ws/drive` optimises a leg that is already fast and is deliberately unused.

**How to tell which one you are on.** The telemetry strip in drive mode has a
**Link** reading: `socket` or `polling`. That is not decoration — this app is
served over `connect-src 'self'`, and whether a given Safari version will open
a `ws:` connection under that policy is a question no test here can answer. If
it says `polling` on your phone but `socket` on a laptop, the CSP is the first
suspect, and the fallback means everything still works meanwhile.

Two things the socket changes that are worth knowing:

- **The server holds the last command and re-sends it** every 200 ms, so a
  frame delayed by LTE jitter lands on a command that is still being refreshed
  instead of a gap. The Pi sees one steady rate whatever the phone's connection
  is doing.
- **That hold expires after 600 ms of silence**, and then the server sends one
  stop of its own. This is a safety number, not a tuning one: a watchdog that
  fires when commands *stop* arriving is defeated by anything that keeps
  sending on the operator's behalf. Worst case, a phone that dies mid-throttle
  leaves the robot moving 600 ms rather than 500 ms.
