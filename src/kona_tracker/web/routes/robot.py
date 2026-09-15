"""The robot: its tab, drive mode, the HTTP drive routes, the WebSocket
drive transport and its pump, and the front lights.

Everything that moves a physical object is in this file, and it all goes
through `robot_or_404()` and `robot_reply()`. The three mutable sets the
WebSocket needs are factory locals on purpose: module level would share
them across every app built in one test process, and per-request would
not be shared at all.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Form, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from kona_tracker.robot.gateway import (
    DRIVE_HOLD_MS,
    DRIVE_INTERVAL_MS,
    DRIVE_TTL_MS,
    RobotError,
    RobotFault,
    RobotGateway,
    RobotRefused,
    RobotUnreachable,
)
from kona_tracker.web.auth import COOKIE_NAME
from kona_tracker.web.deps import AppDeps
from kona_tracker.web.views import robot_refusal

# The same logger name as app.py: one log, whichever file a line came from.
log = logging.getLogger("kona_tracker.web")


def make_robot_router(deps: AppDeps) -> APIRouter:
    router = APIRouter()
    settings, templates, auth, robot_hub, robot = (
        deps.settings,
        deps.templates,
        deps.auth,
        deps.robot_hub,
        deps.robot,
    )

    @router.get("/robot", response_class=HTMLResponse)
    def robot_page(request: Request):
        """The robot's camera, and in a later phase its controls. 404 with
        no robot configured: the header has no tab for it either, so the
        page cannot be reached by accident, only by typing the URL."""
        if robot_hub is None:
            raise HTTPException(status_code=404, detail="no robot configured")
        return templates.TemplateResponse(
            request,
            "robot.html",
            {"tab": "robot", "robot_name": settings.robot_name, "drive": robot is not None},
        )

    def robot_or_404() -> RobotGateway:
        """The gateway, or a 404 -- which is what "no robot to drive" is.

        There is no third state. A page that could reach these routes while
        the gateway is unconfigured would be a set of controls that 500 on
        every press, which is the dead button `capabilities.py` exists to
        prevent, on the one surface where a dead button is dangerous.
        """
        if robot is None:
            raise HTTPException(status_code=404, detail="no robot gateway is configured")
        return robot

    def robot_reply(what: str, call: Callable[[], dict[str, Any]]):
        """The single exit for every robot route: four failures, four answers.

        `/control/move` and `/control/preset` have no arm like this and would
        answer a driver failure with a 500 and a traceback-derived body. For a
        network-backed driver that is both a leak and a lie -- the page cannot
        tell "the robot said no" from "the robot is gone", and those need
        different words and different behaviour from the operator.

        Nothing here sends a stop on failure. The gateway's watchdog zeroes
        the motors half a second after commands stop arriving, which is the
        whole reason it exists; a second failing call would only delay the
        truth reaching the screen. A refusal must *especially* not stop, since
        `demo_running` means a demo is driving and a stop would kill it.
        """
        try:
            return call()
        except RobotRefused as e:
            return JSONResponse(
                {"error": robot_refusal(e.reason), "reason": e.reason}, status_code=409
            )
        except RobotUnreachable as e:
            return JSONResponse(
                {"error": robot_refusal(str(e)), "reason": "unreachable"}, status_code=503
            )
        except RobotFault as e:
            return JSONResponse(
                {"error": robot_refusal(str(e)), "reason": "fault"}, status_code=502
            )
        except Exception as e:
            # Unexamined by definition, so its text is not shown: only the
            # class name, to the log on Chris's PC, the way Heartbeat does it.
            log.warning("robot %s failed: %s", what, type(e).__name__)
            return JSONResponse(
                {"error": "The robot gateway failed unexpectedly.", "reason": "fault"},
                status_code=502,
            )

    @router.get("/drive", response_class=HTMLResponse)
    def drive_page(request: Request):
        """Landscape drive mode. Its own page rather than a section of the
        Robot tab: driving wants the whole screen and both thumbs, and iOS
        Safari cannot be asked to rotate, so the layout asks instead."""
        robot_or_404()
        return templates.TemplateResponse(
            request,
            "drive.html",
            {
                "tab": None,
                "robot_name": settings.robot_name,
                "drive_interval_ms": DRIVE_INTERVAL_MS,
                # Stated on the HUD ("let go and it stops within 0.5 s"),
                # never sent back: the page must not choose its own dead-man
                # window, and does not -- test_the_browser_never_chooses_the_ttl.
                "drive_ttl_ms": DRIVE_TTL_MS,
            },
        )

    @router.get("/robot/telemetry")
    def robot_telemetry():
        """Polled at 1 Hz while driving. Passed through as the gateway sends
        it: this app does not get to decide what the battery reads."""
        gateway = robot_or_404()
        return robot_reply("telemetry", gateway.telemetry)

    @router.post("/robot/drive")
    def robot_drive(vx: float = Form(0.0), vy: float = Form(0.0), omega: float = Form(0.0)):
        """One body velocity, held by the gateway for its TTL and no longer.

        The TTL is not a parameter here and must never become one: it is the
        length of the operator's own dead-man switch.
        """
        gateway = robot_or_404()
        return robot_reply("drive", lambda: gateway.drive(vx, vy, omega))

    @router.post("/robot/stop")
    def robot_stop():
        """The one call that must always be attempted. It answers 503 when
        the robot is silent rather than a comforting 200, because a stop that
        did not land is the most dangerous state this app can be in."""
        gateway = robot_or_404()
        return robot_reply("stop", gateway.stop)

    @router.post("/robot/look")
    def robot_look(pan_deg: float = Form(0.0), tilt_deg: float = Form(0.0)):
        gateway = robot_or_404()
        return robot_reply("look", lambda: gateway.look_at(pan_deg, tilt_deg))

    # -- driving over one connection ---------------------------------------
    #
    # **Why this exists.** The robot is on the home LAN; a phone on LTE
    # reaches it through Tailscale to the PC and then over wired Ethernet to
    # the Pi. So the slow leg is phone -> PC, around 700 ms round trip, and
    # the PC -> Pi leg is about 1 ms. Over HTTP the page could only send as
    # fast as that round trip allowed: `drive.js` holds a `sending` flag so
    # commands cannot pile up, which capped it near 1.5 commands a second
    # against a 500 ms TTL. The robot session measured the consequence --
    # the gateway watchdog firing seven times in six seconds with the stick
    # held down. That is the stutter Chris felt.
    #
    # A WebSocket removes the round trip from the send path: frames go out
    # back to back and arrive in a stream. The PC -> Pi leg stays plain HTTP
    # at 200 ms against the 500 ms TTL, which is correct for a 1 ms link and
    # is what the robot session asked us to keep. Their own `/ws/drive` is
    # left alone and unused; it would optimise the leg that is already fast.
    #
    # **The pump is the other half.** Frames from the phone set the current
    # command; a task on this side pushes it to the Pi on a steady clock. So
    # LTE jitter cannot stutter the robot -- a late frame lands on a command
    # that is still being refreshed -- and the Pi sees one rate no matter what
    # the phone's connection is doing.
    #
    # **Which makes the hold window a safety decision, not a tuning one.**
    # Repeating the last command forever would defeat the gateway's watchdog,
    # which only fires when commands *stop* arriving. So the pump stops
    # repeating and sends a stop after DRIVE_HOLD_MS of silence from the
    # phone. Worst case the robot moves that long after the phone dies,
    # against 500 ms before; the gateway's watchdog still backs it up.
    drive_sockets: list[WebSocket] = []
    #: Sockets closed because a newer drive page took over. They must not
    #: send a stop on the way out; see the teardown below. The sockets
    #: themselves rather than their `id()`s: a collected object's id can be
    #: reused, and a stale entry here would silently suppress a real stop.
    superseded: set[WebSocket] = set()
    #: Strong references to the tasks a closing connection leaves behind --
    #: evicting a superseded socket, and the final stop. asyncio holds only
    #: a weak reference, so a task nobody keeps can be collected mid-await
    #: and never finish: a documented footgun, and on the stop path a
    #: safety one.
    evictions: set[asyncio.Task] = set()

    @router.websocket("/robot/ws/drive")
    async def robot_drive_socket(socket: WebSocket):
        # The `gate` middleware is an HTTP middleware and does NOT run for a
        # WebSocket handshake. Checking the cookie here is not belt and
        # braces: without it this is the one unauthenticated route in the
        # app, and it is the one that moves a physical object.
        if not auth.valid_cookie(socket.cookies.get(COOKIE_NAME)):
            await socket.close(code=1008)
            return
        if robot is None:
            await socket.close(code=1008)
            return
        await socket.accept()

        # The Pi's RPC server handles one request at a time. Two drive pages
        # open at once would interleave two streams of commands into it and
        # fight over the robot, so the newest connection takes over and the
        # older one is told to fall back to HTTP rather than silently
        # half-working.
        async def evict(old: WebSocket) -> None:
            with suppress(Exception):
                await old.close(code=1000)

        for old in list(drive_sockets):
            drive_sockets.remove(old)
            # Marked before it is closed: its own teardown stops the robot,
            # and without this flag that stop would land on the page that
            # just took over -- a stutter with no cause visible anywhere.
            # The robot is not left unguarded by skipping it, because the
            # socket replacing it is about to start driving.
            superseded.add(old)
            # Scheduled, not awaited. Awaiting another socket's close from
            # inside this one's setup makes a fresh drive page wait on a peer
            # that may be half-gone -- the case this eviction exists for is
            # precisely a page that stopped behaving. It also deadlocked the
            # Windows CI runner, where the old socket's close could not
            # complete until this handler yielded.
            task = asyncio.create_task(evict(old))
            evictions.add(task)
            task.add_done_callback(evictions.discard)
        drive_sockets.append(socket)

        gateway = robot
        command = {"vx": 0.0, "vy": 0.0, "omega": 0.0}
        last_frame = time.monotonic()
        holding = False
        running = True

        async def say(payload: dict[str, Any]) -> None:
            with suppress(Exception):
                await socket.send_text(json.dumps(payload))

        async def pump() -> None:
            """Push the current command to the Pi on a steady clock."""
            nonlocal holding
            stopped = True
            while running:
                await asyncio.sleep(DRIVE_INTERVAL_MS / 1000.0)
                # A superseded connection does nothing further to the robot.
                # Its close is scheduled rather than awaited, so this pump can
                # outlive the takeover by a tick or two -- long enough, under
                # load, to reach its own hold expiry below and send a stop
                # that lands on the page which replaced it. The teardown flag
                # alone did not cover this: that guards the stop at the end,
                # and this is a stop in the middle.
                if socket in superseded:
                    return
                silent = (time.monotonic() - last_frame) * 1000.0
                if silent > DRIVE_HOLD_MS:
                    # The phone has gone quiet. Let go once, then stay quiet:
                    # re-sending a stop every 200 ms would be noise on a
                    # single-threaded RPC server, and the gateway's watchdog
                    # has already zeroed the motors by now anyway.
                    if not stopped:
                        stopped = True
                        holding = False
                        with suppress(RobotError):
                            await run_in_threadpool(gateway.stop)
                    continue
                if not holding:
                    stopped = True
                    continue
                stopped = False
                try:
                    await run_in_threadpool(
                        gateway.drive, command["vx"], command["vy"], command["omega"]
                    )
                except RobotRefused as e:
                    holding = False
                    await say({"ok": False, "error": robot_refusal(e.reason), "reason": e.reason})
                except RobotUnreachable as e:
                    holding = False
                    await say(
                        {"ok": False, "error": robot_refusal(str(e)), "reason": "unreachable"}
                    )
                except RobotError as e:
                    holding = False
                    await say({"ok": False, "error": robot_refusal(str(e)), "reason": "fault"})
                except Exception as e:
                    holding = False
                    log.warning("robot ws drive failed: %s", type(e).__name__)
                    await say(
                        {
                            "ok": False,
                            "error": "The robot gateway failed unexpectedly.",
                            "reason": "fault",
                        }
                    )

        pumping = asyncio.create_task(pump())
        try:
            while True:
                raw = await socket.receive_text()
                last_frame = time.monotonic()
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(frame, dict):
                    continue
                if frame.get("stop"):
                    # Straight through, ahead of the pump's next tick. The
                    # page also sends its own HTTP stop, which is the one it
                    # can watch land; this is only about getting the wheels
                    # to zero as soon as the bytes arrive.
                    holding = False
                    with suppress(RobotError):
                        await run_in_threadpool(gateway.stop)
                    await say({"ok": True, "stopped": True})
                    continue
                try:
                    command = {
                        "vx": float(frame.get("vx", 0.0)),
                        "vy": float(frame.get("vy", 0.0)),
                        "omega": float(frame.get("omega", 0.0)),
                    }
                except (TypeError, ValueError):
                    continue
                holding = True
        except WebSocketDisconnect:
            pass
        except Exception as e:  # a torn connection, mid-frame
            log.info("robot drive socket ended: %s", type(e).__name__)
        finally:
            running = False
            pumping.cancel()
            with suppress(Exception, asyncio.CancelledError):
                await pumping
            if socket in drive_sockets:
                drive_sockets.remove(socket)
            # The page is gone and cannot be told. `stop_quietly` logs a
            # failure rather than raising, which is right here: there is
            # nobody left to shout at, and the gateway's watchdog is the
            # backstop if even this does not land.
            #
            # Unless another drive page took this one's place, in which case
            # stopping would interrupt whoever is driving now.
            took_over = socket in superseded
            superseded.discard(socket)
            if not took_over:
                # Scheduled, NOT awaited, and this is a safety fix rather than
                # a tidy-up. Starlette cancels this handler's task when the
                # socket closes, so by the time control reaches here the task
                # is often already cancelling -- and an `await` in that state
                # raises CancelledError *immediately*, before the call is
                # made. The stop simply never happened. It showed up as
                # `test_closing_the_page_stops_the_robot` failing on one CI
                # run in three with a ten-second deadline, which is not a
                # slow runner: the stop was never going to arrive.
                #
                # A task of its own is not cancelled with us, so it runs. The
                # gateway's own watchdog still zeroes the motors half a second
                # after commands cease -- that is the backstop, and it was
                # doing the work this line was supposed to be doing.
                task = asyncio.create_task(run_in_threadpool(gateway.stop_quietly))
                evictions.add(task)
                task.add_done_callback(evictions.discard)

    @router.get("/robot/led")
    def robot_led():
        """What colour the gateway was last asked for. Four nulls means it
        has not been asked since it started, which is not the same as off."""
        gateway = robot_or_404()
        return robot_reply("led", gateway.led)

    @router.post("/robot/led")
    def robot_set_led(
        on: bool = Form(False),
        r: int = Form(0),
        g: int = Form(0),
        b: int = Form(0),
    ):
        """The front lights. The one robot control that is not about moving.

        Deliberately reachable while the robot's own software is down. The
        gateway writes these over I2C rather than through the RPC server that
        owns the motors, so they answer when `/health` says `turbopi: false`
        -- and a person looking at a dark house with a robot that will not
        drive can still see where it is.
        """
        gateway = robot_or_404()
        return robot_reply("led", lambda: gateway.set_led(on, r, g, b))

    return router
