"""A log file that outlives the console window.

"It was broken this morning" has had no answer so far: uvicorn's access log
and every camera or Fi failure went to a PowerShell window that closes.
With KONA_LOG_DIR set, `kona serve` appends them to a rotating file there.

Attached at app startup rather than at import, because uvicorn configures
logging inside `uvicorn.run` with `propagate: False` on its own loggers; a
handler on the root logger added earlier would never see an access line.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGERS = ("uvicorn", "uvicorn.access", "kona_tracker")
FILE_NAME = "kona.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 5

#: What a page open on a phone asks for on a timer rather than because
#: somebody did something. The camera picture alone is several requests a
#: second per viewer -- measured at about 6 MB of access lines an hour -- so
#: left in, one evening of watching rotated the whole 30 MB of history away
#: and took "it was broken this morning" with it.
POLLED_PATHS = frozenset({"/snapshot.jpg", "/status.json", "/map.json", "/robot/telemetry"})


class QuietPolling(logging.Filter):
    """Thin out successful access lines for POLLED_PATHS; keep everything else.

    Only a 200 or 304 is ever dropped. A 401, a redirect to the login page
    (a stranger probing without a cookie) or a 5xx is written every time.
    And the first successful poll from each address in every `every`
    seconds is written too, so who watched and when stays answerable even
    for a script that polls with a cookie and never loads a page: about six
    lines an hour per watcher, instead of thousands.
    """

    #: Past this many remembered addresses, forget the ones outside the
    #: window. A home app sees a handful; this only bounds the pathological.
    _PRUNE_AT = 256

    def __init__(self, every: float = 600.0, clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self._every = every
        self._clock = clock
        self._last: dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.name != "uvicorn.access" or not isinstance(args, tuple) or len(args) != 5:
            return True
        path, status = str(args[2]).split("?", 1)[0], args[4]
        if path not in POLLED_PATHS or status not in (200, 304):
            return True
        # "host:port"; the port changes per connection, the watcher does not.
        who = str(args[0]).rsplit(":", 1)[0]
        now = self._clock()
        last = self._last.get(who)
        if last is not None and now - last < self._every:
            return False
        if len(self._last) >= self._PRUNE_AT:
            self._last = {k: t for k, t in self._last.items() if now - t < self._every}
        self._last[who] = now
        return True


def attach_file_logging(log_dir: Path) -> logging.Handler:
    """Start writing to `log_dir/kona.log`; returns the handler to detach."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.addFilter(QuietPolling())
    for name in LOGGERS:
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        if logger.level == logging.NOTSET or logger.level > logging.INFO:
            logger.setLevel(logging.INFO)
    return handler


def detach_file_logging(handler: logging.Handler) -> None:
    for name in LOGGERS:
        logging.getLogger(name).removeHandler(handler)
    handler.close()
