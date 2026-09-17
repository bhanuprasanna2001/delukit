"""Console logging for the CLI: one event per line, bars never break.

Each run reads like:

    21:08:37 [INFO] ┌ run start · window=2026-09-09..2026-09-16 · sources=entsoe, smard · storages=local
    21:09:10 [INFO] ├─ smard: 3285 fetched · 12s · local +3285
    21:09:11 [INFO] └ run complete · 3285 fetched · 12s · 0 synced

INFO is milestones only (per source + final); per-method detail is DEBUG.
Logs go to stderr via ``tqdm.write`` so progress bars never split a line;
level is configurable via DELUKIT_LOG_LEVEL (default INFO). Colors are
omitted when stderr is not a tty or NO_COLOR is set.
"""

from __future__ import annotations

import copy
import logging
import os
import sys

from tqdm import tqdm

_LEVEL_COLORS = {
    logging.DEBUG: "\033[2m",
    logging.INFO: "\033[36m",
    logging.WARNING: "\033[33m",
    logging.ERROR: "\033[31m",
    logging.CRITICAL: "\033[1;31m",
}
_RESET = "\033[0m"

# ponytail: fixed widths keep sequential bars aligned; leave=False since
# the per-source log line persists the outcome after the bar clears.
BAR_FORMAT = (
    "{desc:<32} {percentage:3.0f}%|{bar:30}| "
    "{n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}{postfix}]"
)


def _use_color() -> bool:
    return sys.stderr.isatty() and os.environ.get("NO_COLOR") is None


class ColoredFormatter(logging.Formatter):
    """Level tags tinted per level; messages carry their own ┌/├─/└."""

    def format(self, record: logging.LogRecord) -> str:
        # ponytail: copy — formatting the same record twice (caplog +
        # handler) must not double-wrap colors
        record = copy.copy(record)
        if _use_color():
            color = _LEVEL_COLORS.get(record.levelno)
            record.leveltag = (
                f"{color}[{record.levelname}]{_RESET}"
                if color
                else f"[{record.levelname}]"
            )
            if record.levelno == logging.DEBUG:
                record.msg = f"\033[2m{record.msg}{_RESET}"
        else:
            record.leveltag = f"[{record.levelname}]"
        return super().format(record)


class TqdmHandler(logging.StreamHandler):
    """StreamHandler that writes via tqdm.write so bars stay intact."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            tqdm.write(msg, file=self.stream)
            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:  # noqa: BLE001 — logging must never raise; report via handleError
            self.handleError(record)


def setup_logging() -> None:
    level = logging.getLevelNamesMapping().get(
        os.environ.get("DELUKIT_LOG_LEVEL", "").upper(), logging.INFO
    )
    handler = TqdmHandler(sys.stderr)
    handler.setFormatter(
        ColoredFormatter("%(asctime)s %(leveltag)s %(message)s", datefmt="%H:%M:%S")
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
    # third-party HTTP chatter: keep warnings/errors, drop the per-request lines
    for noisy in ("databricks.sql", "snowflake.connector", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
