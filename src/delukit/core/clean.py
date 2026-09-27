from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from delukit.core.config import BASE_DIR, CLEAN_DIR, TIMEZONE

UTC = ZoneInfo("UTC")
BERLIN = ZoneInfo(TIMEZONE)


def raw_days() -> list[date]:
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
    start = datetime.combine(day, dtime.min, BERLIN).astimezone(UTC)
    end = datetime.combine(day + timedelta(days=1), dtime.min, BERLIN).astimezone(UTC)
    return start, end, int((end - start).total_seconds() // 900)


def quarter_grid(day: date) -> pd.DatetimeIndex:
    start, _, n = day_bounds(day)
    return pd.DatetimeIndex([start + timedelta(minutes=15 * i) for i in range(n)])


def master_index(days: list[date]) -> pd.DatetimeIndex:
    parts = [quarter_grid(day) for day in days]
    if not parts:
        return pd.DatetimeIndex([], tz=UTC)
    return pd.DatetimeIndex([stamp for part in parts for stamp in part])


def frame(idx: pd.DatetimeIndex) -> pd.DataFrame:
    berlin = idx.tz_convert(BERLIN)
    local_time = pd.Series(berlin, index=idx)
    return pd.DataFrame(
        {
            "timestamp_utc": idx,
            "timestamp_berlin": berlin,
            "date": local_time.dt.date.astype(str),
            "quarter": local_time.dt.hour * 4 + local_time.dt.minute // 15 + 1,
        }
    ).set_index("timestamp_utc")


def write_clean(df: pd.DataFrame, name: str) -> Path:
    path = CLEAN_DIR / f"{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.sort_index()
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, engine="pyarrow")
    tmp.replace(path)
    return path
