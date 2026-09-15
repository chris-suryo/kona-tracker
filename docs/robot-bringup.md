# Bringing the robot up, in order

Everything below assumes the robot is built and its own software is running
(`docs/device-capabilities.md` §1b). This is the procedure for connecting it
to kona-tracker, and the order is the safety property — not bureaucracy.

**The one rule: step 3 is a gate, not a step.** If the watchdog proof does not
pass, nothing after it happens. The robot holds a motor duty until something
tells it otherwise, so without a working watchdog a lost "stop" is a robot
that drives until it hits something.

---

## 0. Get the files onto the Pi

The robot's repo is public, so the Pi can fetch it directly:

```bash
git clone https://github.com/chris-suryo/turbopi ~/turbopi
```

`install_gateway.sh` expects to sit next to `robot_gateway.py` and to run as
the `pi` user. In the repo they are in different directories (`scripts/` and
`gateway/`), so check their `docs/09-gateway.md` for the intended layout
before running it rather than guessing — **that is their side and their call,
not something this doc should invent.**

## 1. Install the gateway

```bash
bash install_gateway.sh
```

It prints the shared secret at the end. Keep it for step 5; it is also stored
at `/etc/turbopi/gateway-token`.

## 2. The patch — required, not optional

```bash
python3 patch_getrunningfunc.py
sudo systemctl restart turbopi
sudo systemctl restart turbopi-gateway
```

Stock robot software has a bug that makes "is a built-in demo running?" fail
every single time, and the guard that stops manual driving from fighting a
demo depends on it. Skip this and the guard silently cannot work.

You do not have to take that on trust: the drive screen says **"The robot
cannot tell whether a built-in demo is running, so that guard is off"** when
the patch has not taken. If you see that line, this step did not happen.

## 3. THE GATE — prove the watchdog, wheels off the ground

```bash
bash gateway_watchdog_proof.sh
```

Put the robot **on a stand** first. It drives forward for about half a second.

The script sends one drive command, sends **no** stop, waits, and then shows
three independent pieces of evidence that the motors stopped anyway. If it
does not pass, **stop here** and send the output back. Everything below
assumes the robot can stop itself.

## 4. Network

From the PC, in PowerShell:

```powershell
Test-NetConnection 192.0.2.3 -Port 8080    # the camera (still owed from the camera phase)
Test-NetConnection 192.0.2.3 -Port 9031    # the gateway
```

`TcpTestSucceeded : True` on both. Then reserve `192.0.2.3` for the robot in
the router (DHCP reservation) — without it the address can change on a reboot
and the tab goes quiet with nothing on screen explaining why.

## 5. `.env`, and not before now

```
KONA_ROBOT_SNAPSHOT_URL=http://192.0.2.3:8080/?action=snapshot
KONA_ROBOT_CONTROL_URL=http://192.0.2.3:9031
KONA_ROBOT_TOKEN=<the secret from step 1>
```

Restart `kona serve`. A **Robot** tab appears, and on it a **Drive** link.
With the control URL and token blank, the Robot tab is a camera and there is
no way to move anything — which is the correct state until step 3 has passed.

## 6. First drive, on the stand

Turn the phone sideways. Push the stick one direction at a time and watch
what the robot actually does. **Nobody has measured whether left is left.**
"Push left, go left" rests on how the mecanum rollers are oriented and "pan
left, look left" on how the servo horn was mounted, and neither has been
checked on this robot. A mirrored axis is a sign flip on the Pi side; found
on a stand it costs nothing, found at the edge of a table it costs a robot.

The speed limiter starts on **Slow** for exactly this reason. Leave it there
until every direction is confirmed.

---

## What the drive screen is telling you

Every line below was read off the gateway's own source, not its summary.

| On screen | What happened | What to do |
|---|---|---|
| **The robot may still be moving. The gateway has not had a stop confirmed.** | The gateway has never had an all-zero acknowledged. The board may still be holding duty | Nothing from the phone. The gateway retries on its own and lands the stop the moment the robot answers. If it persists, the robot's own software is down — power-cycle it |
| **The stop did not reach the robot.** *(+ a reason)* | Our stop request failed | It keeps retrying by itself. The robot's own watchdog also zeroes the motors within half a second of commands stopping |
| **Picture 1.4 s behind** | Frames have stopped arriving while you are steering by them | Stop. You are driving blind. Usually Wi-Fi range or a flat battery |
| **The robot's own software is not answering. Turn it off and on.** | The gateway is up; `TurboPi.py` behind it is not | Power-cycle the robot. Its software owns the motor port, so nothing can stop the wheels while it is down — this is the one gap nothing covers |
| **The robot's gateway has no access token set up.** | No secret file on the Pi | Step 1 did not finish. Re-run the installer |
| **The robot's gateway rejected our token. Check KONA_ROBOT_TOKEN.** | The `.env` value and the Pi's secret file disagree | Copy it again from `/etc/turbopi/gateway-token` |
| **The robot's battery is too low to drive.** | Under 7.0 V | Charge it. Watching still works |
| **A built-in demo is driving the robot.** | A demo owns the motors | Stop the demo. Manual driving is refused until it does |
| **ROBOT OFF** | No picture at all | Normal when it is off. The tab recovers on its own when it comes back |

An unfamiliar word in a message — something like `e17_flux_capacitor` — is a
reason the gateway sent that this app has no sentence for. It is shown raw on
purpose, because a token can be searched for and an invented sentence would
be a guess presented as fact. Send it back and it becomes a one-line fix.
