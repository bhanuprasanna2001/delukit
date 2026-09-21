"""Raw Open-Meteo single-run forecasts, one file per day and cell group.

Layout: data/raw/<day>/weather/<land|sea>/data.json

Each file holds one model's 00z run for every location in the group.
Runs are immutable: a file, once written, is never re-fetched.
"""

import json
import logging
import re
import threading
import time
from datetime import date, datetime, timedelta

import requests

from delukit.core.config import BASE_DIR, TIMEZONE
from delukit.core.config.weather import (
    WEATHER_FIELDS,
    WEATHER_FORECAST_DAYS,
    WEATHER_LOCATIONS,
    WEATHER_MODEL,
    WEATHER_URL,
)
from delukit.core.parallel import RateLimited, run_parallel

log = logging.getLogger(__name__)

REQUEST_GAP = 60 / 27
WORKERS = 2  # one per cell group; the gap above is the real limit
RETRY_GAP = 60
MAX_RETRIES = 3

_lock = threading.Lock()
_last_request = 0.0

_UNAVAILABLE = re.compile(
    rb"Unexpected error while streaming data: "
    rb"modelRunUnavailable\(model: [A-Za-z0-9_.-]+, "
    rb"run: OmTime\.Timestamp\(timeIntervalSince1970: \d+\)\)"
)


def _throttle():
    """Space requests REQUEST_GAP apart across all workers."""
    global _last_request
    with _lock:
        wait = _last_request + REQUEST_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _retry_after(response):
    try:
        return max(float(response.headers.get("Retry-After", RETRY_GAP)), 0)
    except ValueError:
        return RETRY_GAP


def _download(session, group, day):
    locations = WEATHER_LOCATIONS[group]
    params = {
        "latitude": ",".join(str(lat) for _, lat, _ in locations),
        "longitude": ",".join(str(lon) for _, _, lon in locations),
        "models": WEATHER_MODEL,
        "hourly": ",".join(WEATHER_FIELDS),
        "forecast_days": WEATHER_FORECAST_DAYS,
        "cell_selection": group,
        "timezone": TIMEZONE,
        "run": f"{day.isoformat()}T00:00",
    }
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            response = session.get(WEATHER_URL, params=params, timeout=60)
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code == 204:  # run not published yet
            return None
        if response.status_code == 429:
            if attempt == MAX_RETRIES:
                raise RateLimited(f"{group} {day}")
            log.warning("rate limited, sleeping: %s %s", group, day)
            time.sleep(_retry_after(response))
            continue
        if response.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
            time.sleep(2**attempt)
            continue
        if response.status_code == 400:  # unavailable run, let _parse map to no_data
            return response.content
        response.raise_for_status()
        return response.content
    raise RateLimited(f"{group} {day}")


def _parse(body, group):
    """Raw bytes, None when the run is not available, False when invalid."""
    if body is None or _UNAVAILABLE.fullmatch(body):
        return None
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if isinstance(document, dict):
        reason = document.get("reason", "") if document.get("error") is True else ""
        if isinstance(reason, str) and reason.startswith(
            "The requested model run is not available."
        ):
            return None
        return False
    locations = WEATHER_LOCATIONS[group]
    if not isinstance(document, list) or len(document) != len(locations):
        return False
    for record in document:
        if not isinstance(record, dict) or not isinstance(record.get("hourly"), dict):
            return False
        hourly = record["hourly"]
        if not isinstance(hourly.get("time"), list) or not all(
            isinstance(hourly.get(field), list) for field in WEATHER_FIELDS
        ):
            return False
    return body


def fetch_day(group, day, session=None):
    path = BASE_DIR / day.isoformat() / "weather" / group / "data.json"

    if path.exists():  # runs never change; fetch each run once
        return "unchanged"

    own = session is None
    session = session or requests.Session()
    try:
        body = _parse(_download(session, group, day), group)
    finally:
        if own:
            session.close()
    if body is None:
        return "no_data"
    if body is False:
        raise ValueError(f"invalid JSON: {group} {day}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return "fetched"


def sync(start, end, on_each=None):
    work = []
    skipped = 0
    day = start
    while day <= end:
        for group in WEATHER_LOCATIONS:
            if (BASE_DIR / day.isoformat() / "weather" / group / "data.json").exists():
                skipped += 1
                if on_each:
                    on_each(group, day, "unchanged")
            else:
                work.append((group, day))
        day += timedelta(days=1)

    with requests.Session() as session:
        session.headers.update({"user-agent": "delukit"})
        counts = run_parallel(
            work,
            lambda g, d: fetch_day(g, d, session=session),
            WORKERS,
            on_each,
        )
    counts["unchanged"] += skipped
    return counts


def to_clean(days=None):
    """Parse every raw run-file into versioned data/clean/weather.parquet.

    One row per run x location x valid hour. ``available_at`` is the run's
    00z issue time, so downstream can replay what was known when.
    """
    import json

    import pandas as pd

    from delukit.core.clean import BERLIN, UTC, raw_days, write_clean

    days = days or raw_days()
    rows = []
    for day in days:
        available_at = pd.Timestamp(
            datetime(day.year, day.month, day.day, tzinfo=UTC)
        )
        for group, locations in WEATHER_LOCATIONS.items():
            path = BASE_DIR / day.isoformat() / "weather" / group / "data.json"
            if not path.exists():
                continue
            for (name, _, _), record in zip(locations, json.loads(path.read_bytes())):
                hourly = record["hourly"]
                for i, stamp in enumerate(hourly["time"]):
                    valid_berlin = datetime.fromisoformat(stamp).replace(tzinfo=BERLIN)
                    rows.append(
                        {
                            "timestamp_utc": valid_berlin.astimezone(UTC),
                            "run_day": day.isoformat(),
                            "available_at": available_at,
                            "location": name,
                            "group": group,
                            "latitude": record["latitude"],
                            "longitude": record["longitude"],
                            **{
                                field: hourly[field][i]
                                for field in WEATHER_FIELDS
                            },
                        }
                    )
    df = pd.DataFrame(rows)
    # Spring-forward days contain a nonexistent 02:00 wall time that maps onto
    # the same UTC instant as 03:00; keep the real one. Fall-back's single 02:00
    # maps fold=0, leaving a 1h gap downstream ffill covers (limit 96 quarters).
    # ponytail: hourly wall-time API can't represent both folds; UTC-native
    # hourly+minute API if this gap ever matters.
    df = df.drop_duplicates(subset=["run_day", "location", "timestamp_utc"], keep="last")
    # Night radiation arrives as null in some runs, 0.0 in others; null
    # alongside a valid temperature is night (-> 0). Run-tail nulls
    # (all fields null) stay NaN.
    night = df["shortwave_radiation"].isna() & df["temperature_2m"].notna()
    df.loc[night, "shortwave_radiation"] = 0.0
    df["timestamp_berlin"] = pd.to_datetime(df["timestamp_utc"]).dt.tz_convert(BERLIN)
    df = df.set_index("timestamp_utc").sort_index()
    path = write_clean(df, "weather")
    log.info("clean weather: %d rows x %d cols -> %s", len(df), len(df.columns), path)
    return path


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
