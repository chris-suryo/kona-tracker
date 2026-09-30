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
    """Drop successful access lines for POLLED_PATHS; keep everything else.

    A failure on those paths is still written: a 401 or a 5xx is the line
    worth finding. The page load that started the polling is written too,
    so who watched and when stays answerable.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if record.name != "uvicorn.access" or not isinstance(args, tuple) or len(args) != 5:
            return True
        path, status = str(args[2]).split("?", 1)[0], args[4]
        return not (path in POLLED_PATHS and isinstance(status, int) and status < 400)


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
