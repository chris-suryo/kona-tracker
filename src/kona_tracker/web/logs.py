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


def attach_file_logging(log_dir: Path) -> logging.Handler:
    """Start writing to `log_dir/kona.log`; returns the handler to detach."""
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / FILE_NAME, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
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
