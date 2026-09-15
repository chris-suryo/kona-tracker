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

## Driving over Tailscale, from away

It will stutter, and that is measured rather than guessed. At a 700 ms round
trip the robot session recorded the watchdog firing **seven times in six
seconds** with the stick held down, because the HTTP client can only send as
fast as the round trip allows.

Watching from away is fine. Driving properly from away needs the WebSocket
transport (`GET /ws/drive` already exists on their side; our client does not
use it yet). Until then, drive on the home Wi-Fi.
