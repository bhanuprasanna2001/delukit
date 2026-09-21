"""Shared clean-build helpers (raw -> data/clean/*.parquet).

Master grain is the Berlin quarter-hour. Timestamps are generated in UTC
directly (midnight-to-midnight Berlin converted to UTC), so DST days
naturally yield 92/96/100 quarters with no fold bookkeeping.
"""

from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from delukit.core.config import BASE_DIR, CLEAN_DIR, TIMEZONE

UTC = ZoneInfo("UTC")
BERLIN = ZoneInfo(TIMEZONE)


def raw_days() -> list[date]:
    """Sorted days present under data/raw."""
    return [
        date.fromisoformat(p.name)
        for p in sorted(BASE_DIR.iterdir())
        if p.is_dir() and _is_date(p.name)
    ]


def _is_date(name: str) -> bool:
    try:
        date.fromisoformat(name)
        return True
    except ValueError:
        return False


def day_bounds(day: date) -> tuple[datetime, datetime, int]:
    """(start_utc, end_utc, n_quarters) for a Berlin day."""
    start = datetime.combine(day, dtime.min, BERLIN).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), dtime.min, BERLIN).astimezone(UTC)
    return start, end, int((end - start).total_seconds() // 900)


def quarter_grid(day: date) -> pd.DatetimeIndex:
    """UTC instants of every quarter-hour of a Berlin day."""
    start, _, n = day_bounds(day)
    return pd.DatetimeIndex([start + timedelta(minutes=15 * i) for i in range(n)])


def master_index(days: list[date]) -> pd.DatetimeIndex:
    """Full quarter-hour UTC index over all days."""
    parts = [quarter_grid(day) for day in days]
    return parts[0].append(parts[1:]) if parts else pd.DatetimeIndex([])


def frame(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Empty frame with canonical time columns on the given UTC index."""
    berlin = idx.tz_convert(BERLIN)
    return pd.DataFrame(
        {
            "timestamp_utc": idx,
            "timestamp_berlin": berlin,
            "date": berlin.date.astype(str),
            "quarter": berlin.hour * 4 + berlin.minute // 15 + 1,
        }
    ).set_index("timestamp_utc")


def write_clean(df: pd.DataFrame, name: str) -> Path:
    """Sort by timestamp_utc and atomically write data/clean/<name>.parquet."""
    path = CLEAN_DIR / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_index()
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, engine="pyarrow")
    tmp.replace(path)
    return path
