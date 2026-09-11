"""A dead-man's switch: the app says "still here" to something outside it.

The gap this closes is the one nothing inside the house can close. If the PC
sleeps, loses power, loses its network, or `kona serve` dies at 2am, then by
definition nothing on that machine is able to tell anyone. Only the *absence*
of a signal can carry that news, and only something off the premises can
notice the absence.

Why a push and not a poll. The obvious shape is an uptime service polling
`/healthz` through the tunnel, and that is worth having once there is a
domain. It cannot work today: a Cloudflare quick tunnel hands out a fresh
random URL on every restart, so there is no stable address to poll. A push
needs no inbound reachability and no fixed hostname, so it works right now,
and it keeps working after the domain arrives.

What it does and does not claim:

- It says the process is alive and can reach the internet. That covers
  sleep, crash, reboot, power cut and a dropped connection, which is the
  whole list of things that have no other alarm.
- It does **not** fail on a wedged camera or a quiet Fi. Those already have
  honest signals on `/settings` and `/healthz`, and folding them in here
  would turn one clear alarm into a flappy one that gets muted. The current
  state rides along in the ping body instead, so the service's event log
  shows what the app was doing each time without changing whether it alerts.

Set `KONA_HEARTBEAT_URL` to a ping URL from any dead-man's-switch service
(healthchecks.io's free tier is the obvious one) and it will email you when
the pings stop. Leave it blank and none of this runs.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger("kona_tracker.web")

DEFAULT_INTERVAL_SECONDS = 300.0
#: Long enough to survive a slow link, short enough that a wedged request
#: cannot hold up shutdown behind it.
REQUEST_TIMEOUT_SECONDS = 10.0


class Heartbeat:
    """Pings `url` on a daemon thread until it is stopped.

    Failures are logged and otherwise ignored: a monitoring service being
    down must never take the camera down with it. That is also why the first
    ping goes out immediately rather than one interval later -- a typo in the
    URL should show up in the log while you are still sitting there, not in
    five minutes when you have walked away believing it works.
    """

    def __init__(
        self,
        url: str,
        summary: Callable[[], dict[str, Any]],
        interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
        post: Callable[..., Any] | None = None,
    ):
        self._url = url
        self._summary = summary
        self._interval = max(interval_seconds, 5.0)
        self._post = post
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.sent = 0
        self.failures = 0

    def _send(self) -> bool:
        try:
            body = json.dumps(self._summary())
        except Exception:  # a broken summary must not stop the heartbeat
            body = ""
        try:
            post = self._post
            if post is None:
                import httpx

                post = httpx.post
            response = post(self._url, content=body, timeout=REQUEST_TIMEOUT_SECONDS)
            if response is not None and not response.is_success:
                self.failures += 1
                log.warning("heartbeat ping rejected: HTTP %s", response.status_code)
                return False
        except Exception as e:
            self.failures += 1
            # Never log the URL: anyone holding it can forge this app's
            # heartbeat and suppress the alarm that says the house is dark.
            # HTTP exceptions can contain the full secret ping URL.
            log.warning("heartbeat ping failed: %s (details omitted)", type(e).__name__)
            return False
        self.sent += 1
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            self._send()
            # Waiting on the event rather than sleeping means shutdown is
            # immediate instead of up to one interval late.
            self._stop.wait(self._interval)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="kona-heartbeat", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=timeout)
