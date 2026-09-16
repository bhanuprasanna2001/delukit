"""Colored tree-styled console logging for the CLI.

Each line reads like:

    21:08:37 [INFO] ── run start · sources=entsoe, smard · window=2026-09-09..2026-09-16
    21:09:10 [INFO] ── smard: 3285 records
    21:09:11 [INFO] │  ├─ local: 3285 rows
    21:09:11 [INFO] │  ├─ databricks: 3285 rows

Level tags are tinted per level and nested lines get tree connectors
(the `indent` record attribute controls depth). Logs go to stderr so
stdout stays clean; the level is configurable via the
DELUKIT_LOG_LEVEL environment variable (default INFO).
"""

from __future__ import annotations

import logging
import os
import sys

_LEVEL_COLORS = {
    logging.DEBUG: "\033[2m",
    logging.INFO: "\033[36m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"


class ColoredFormatter(logging.Formatter):
    """Standard formatter with level tags and tree-style indentation."""

    def format(self, record: logging.LogRecord) -> str:
        indent = getattr(record, "indent", 0)
        color = _LEVEL_COLORS.get(record.levelno)
        record.leveltag = (
            f"{color}[{record.levelname}]{_RESET}" if color else f"[{record.levelname}]"
        )
        record.tree = "│  " * indent + ("├─ " if indent else "── ")
        if record.levelno == logging.DEBUG:
            record.msg = f"\033[2m{record.msg}{_RESET}"
        return super().format(record)


def setup_logging() -> None:
    level = logging.getLevelNamesMapping().get(
        os.environ.get("DELUKIT_LOG_LEVEL", "").upper(), logging.INFO
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        ColoredFormatter(
            "%(asctime)s %(leveltag)s %(tree)s%(message)s", datefmt="%H:%M:%S"
        )
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # third-party HTTP chatter: keep warnings/errors, drop the per-request lines
    for noisy in ("databricks.sql", "snowflake.connector", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
