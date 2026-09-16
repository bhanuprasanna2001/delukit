"""Colored console logging for the CLI.

Level names are tinted per level (debug dim, info cyan, warning yellow,
error red). Logs go to stderr so stdout stays clean; the level is
configurable via the DELUKIT_LOG_LEVEL environment variable (default
INFO).
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
    """Standard formatter that tints the level name."""

    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelno)
        if color is not None:
            record.levelname = f"{color}{record.levelname}{_RESET}"
        return super().format(record)


def setup_logging() -> None:
    level = logging.getLevelNamesMapping().get(
        os.environ.get("DELUKIT_LOG_LEVEL", "").upper(), logging.INFO
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        ColoredFormatter(
            "%(asctime)s %(levelname)s %(name)s · %(message)s", datefmt="%H:%M:%S"
        )
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
