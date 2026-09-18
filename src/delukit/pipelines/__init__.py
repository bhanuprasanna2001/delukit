"""Pipeline stages: one module per medallion layer, composed by the CLI.

bronze.py fetches APIs into bronze storage, silver.py parses bronze into
silver tables, and gold.py joins when transforms/ grows its first
transform. Window and failure semantics live here so every stage decides
what to (re)process and reports errors identically.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

__all__ = ["PipelineError", "fmt_elapsed", "resolve_day", "window_start"]

_DEFAULT_REFRESH_DAYS = {
    "smard": 7,
    "entsoe": 7,
    "energy_charts": 7,
    "weather": 3,
}


class PipelineError(Exception):
    """One or more sources failed; every successful source still landed."""


def resolve_day(value: date | str, timezone_name: str) -> date:
    """Resolve a config bound ("latest", iso string, or date) to a day."""
    if value == "latest":
        return _today(timezone_name)
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _today(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def window_start(
    name: str,
    source_config: dict[str, Any],
    begin: date,
    coverage: set[tuple[str, date]],
) -> date:
    """First day to process for a source: refresh window before its latest day."""
    days = {day for source, day in coverage if source == name}
    if not days:
        return begin
    refresh_days = source_config.get("refresh_days", _DEFAULT_REFRESH_DAYS[name])
    return max(begin, max(days) - timedelta(days=refresh_days - 1))


def fmt_elapsed(seconds: float) -> str:
    """Compact duration: 12s, 5m42s, 1h02m03s."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s"
