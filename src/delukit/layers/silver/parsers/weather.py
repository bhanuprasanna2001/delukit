"""Weather silver: parse raw Single Runs payloads into clean per-day frames.

One day's raw payload (dict keyed by call key) in, one clean frame out:

    forecast -> location, run_time, valid_time, <one column per field>

Hours where every field is null (the IFS horizon ends after 15 days while
16 were requested) are dropped; partial nulls stay as NaN.
"""

from __future__ import annotations

import pandas as pd


def parse_day(
    raws: dict,
    method: str,
    tz: str = "Europe/Berlin",
) -> pd.DataFrame:
    """Parse one day's raw payload for a method into one frame."""
    try:
        handler = _HANDLERS[method]
    except KeyError:
        raise ValueError(f"unknown weather method: {method!r}")
    payload = raws.get(method)
    if payload is None:
        return pd.DataFrame()
    try:
        return handler(payload, tz)
    except Exception as error:
        raise ValueError(f"weather: unparseable {method} document: {error}") from error


def _forecast(payload: dict, tz: str) -> pd.DataFrame:
    if not isinstance(payload, dict):
        raise TypeError("expected a json object")
    run = payload.get("run")
    if not isinstance(run, str):
        raise TypeError("run must be a string")
    run_time = pd.Timestamp(run, tz="UTC")
    locations = payload.get("locations")
    if not isinstance(locations, dict) or not locations:
        raise TypeError("locations must be a non-empty object")
    frames = [
        _location_frame(name, run_time, item, tz) for name, item in locations.items()
    ]
    return pd.concat(frames, ignore_index=True)


def _location_frame(
    name: str,
    run_time: pd.Timestamp,
    item: dict,
    tz: str,
) -> pd.DataFrame:
    if not isinstance(item, dict) or not isinstance(item.get("hourly"), dict):
        raise TypeError(f"location {name} is missing hourly data")
    hourly = item["hourly"]
    times = hourly.get("time")
    if not isinstance(times, list) or not times:
        raise ValueError(f"location {name} has no hourly time series")
    fields = [key for key in hourly if key != "time"]
    if not fields:
        raise ValueError(f"location {name} has no weather fields")
    if not all(isinstance(values, list) for values in hourly.values()):
        raise ValueError(f"location {name} has mismatched array lengths")
    lengths = {len(values) for values in hourly.values()}
    if len(lengths) != 1:
        raise ValueError(f"location {name} has mismatched array lengths")
    # API emits naive local times, including the nonexistent spring-forward
    # hour (dropped) and both duplicated fall-back hours (kept, offset inferred).
    valid_times = pd.to_datetime(times).tz_localize(
        tz, ambiguous="infer", nonexistent="NaT"
    )
    data = pd.DataFrame({"valid_time": valid_times})
    for field in fields:
        data[field] = pd.to_numeric(hourly[field])
    data = data.loc[data["valid_time"].notna()].reset_index(drop=True)
    data = data.loc[data[fields].notna().any(axis=1)].reset_index(drop=True)
    data.insert(0, "run_time", run_time)
    data.insert(0, "location", name)
    return data


_HANDLERS = {
    "forecast": _forecast,
}
