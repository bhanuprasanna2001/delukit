"""delukit: German energy data pipeline.

Usage: delukit [raw_config_path]   (default: configs/raw.json)

Library:
    import delukit
    delukit.fetch("entsoe", "2025-10-01", "2025-10-02",
                  method="day_ahead_price", area="DE_LU")
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

__all__ = ["fetch", "main"]


def _coerce_day(value: date | datetime | str, tz: str = "Europe/Berlin") -> date:
    if isinstance(value, str):
        return date.fromisoformat(value)
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(ZoneInfo(tz)).date()
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(
        f"start/end must be a date or ISO date string, got {type(value).__name__}"
    )


def fetch(
    source: str,
    start: date | datetime | str,
    end: date | datetime | str,
    tz: str = "Europe/Berlin",
    **params: Any,
) -> dict[date, Any]:
    """Fetch raw per-day payloads for one source, no config file or storage.

    Args:
        source: one of "smard", "entsoe", "energy_charts", "weather".
        start: first day (inclusive), ISO "YYYY-MM-DD" string, date, or datetime.
        end: last day (inclusive), must not be before start.
        tz: timezone passed to the source; aware datetimes are converted
            to it before truncation, naive datetimes are truncated as-is.
        **params: weather requires locations and fields (plus optional
            model, forecast_days); other sources pass method/area/etc.
            straight through to ``DataSource.fetch``. Weather has a single
            implicit "forecast" method: pass no method, or method="forecast".

    Raises:
        TypeError: start/end is not a date or ISO string.
        ValueError: unknown source, weather missing locations/fields,
            weather method other than "forecast", or start after end.
    """
    from delukit.sources.build import build_source

    start_day = _coerce_day(start, tz)
    end_day = _coerce_day(end, tz)
    if start_day > end_day:
        raise ValueError(
            f"start {start_day.isoformat()} is after end {end_day.isoformat()}"
        )
    if source == "weather":
        method = params.pop("method", "forecast")
        if method != "forecast":
            raise ValueError(
                f"weather has a single implicit 'forecast' method, got {method!r}"
            )

    src = build_source(source, params, tz)
    kwargs = {} if source == "weather" else params
    return src.fetch(start_day, end_day, **kwargs)


def main() -> None:
    from delukit.core.log import setup_logging
    from delukit.pipelines.raw import run

    setup_logging()
    path = sys.argv[1] if len(sys.argv) > 1 else "configs/raw.json"
    run(path)
