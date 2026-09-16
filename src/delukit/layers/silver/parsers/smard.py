"""SMARD silver: parse raw JSON day-documents into clean per-day frames.

One day's raw documents (dict keyed by call key) in, one clean frame out:

    day_ahead_price       -> timestamp, price_eur_per_mwh, sequence
    load_actual           -> timestamp, load_mw
    load_forecast         -> timestamp, load_mw
    generation_actual     -> timestamp, generation_mw, generation_type
    generation_forecast_day_ahead
                          -> timestamp, generation_mw, generation_type

Null values (future hours, pruned history) are dropped.
"""

from __future__ import annotations

import json

import pandas as pd

_PRICE_COLUMNS = ["timestamp", "price_eur_per_mwh", "sequence"]
_LOAD_COLUMNS = ["timestamp", "load_mw"]
_GENERATION_COLUMNS = ["timestamp", "generation_mw", "generation_type"]


def parse_day(
    raws: dict[str, str],
    method: str,
    generation_types: list[str] | None = None,
    tz: str = "Europe/Berlin",
) -> pd.DataFrame:
    """Parse one day's raw documents for a method into one frame."""
    try:
        handler = _HANDLERS[method]
    except KeyError:
        raise ValueError(f"unknown smard method: {method!r}")
    try:
        return handler(raws, generation_types or [], tz)
    except Exception as error:
        raise ValueError(f"smard: unparseable {method} document: {error}") from error


def _points(text: str) -> list[tuple[int, float]]:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("expected a json object")
    series = data.get("series")
    if not isinstance(series, list):
        raise TypeError("series must be a list")
    points: list[tuple[int, float]] = []
    for point in series:
        if (
            not isinstance(point, list)
            or len(point) != 2
            or not isinstance(point[0], int)
            or (point[1] is not None and not isinstance(point[1], (int, float)))
        ):
            raise TypeError("series points must be [timestamp_ms, value] pairs")
        if point[1] is not None:
            points.append((point[0], float(point[1])))
    return points


def _value_frame(points: list[tuple[int, float]], name: str, tz: str) -> pd.DataFrame:
    if not points:
        return pd.DataFrame(columns=["timestamp", name])
    timestamps = pd.to_datetime(
        [point[0] for point in points], unit="ms", utc=True
    ).tz_convert(tz)
    return pd.DataFrame({"timestamp": timestamps, name: [point[1] for point in points]})


def _day_ahead_price(raws, generation_types, tz) -> pd.DataFrame:
    text = raws.get("day_ahead_price")
    if text is None:
        return pd.DataFrame(columns=_PRICE_COLUMNS)
    frame = _value_frame(_points(text), "price_eur_per_mwh", tz)
    frame["sequence"] = 1
    return frame


def _load(raws, key: str, tz: str) -> pd.DataFrame:
    text = raws.get(key)
    if text is None:
        return pd.DataFrame(columns=_LOAD_COLUMNS)
    return _value_frame(_points(text), "load_mw", tz)


def _load_actual(raws, generation_types, tz) -> pd.DataFrame:
    return _load(raws, "load_actual", tz)


def _load_forecast(raws, generation_types, tz) -> pd.DataFrame:
    return _load(raws, "load_forecast", tz)


def _generation(
    raws, method: str, generation_types: list[str], tz: str
) -> pd.DataFrame:
    frames = []
    for name in generation_types:
        text = raws.get(f"{method}/{name}")
        if text is None:
            continue
        frame = _value_frame(_points(text), "generation_mw", tz)
        frame["generation_type"] = name
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=_GENERATION_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def _generation_actual(raws, generation_types, tz) -> pd.DataFrame:
    return _generation(raws, "generation_actual", generation_types, tz)


def _generation_forecast_day_ahead(raws, generation_types, tz) -> pd.DataFrame:
    return _generation(raws, "generation_forecast_day_ahead", generation_types, tz)


_HANDLERS = {
    "day_ahead_price": _day_ahead_price,
    "load_actual": _load_actual,
    "load_forecast": _load_forecast,
    "generation_actual": _generation_actual,
    "generation_forecast_day_ahead": _generation_forecast_day_ahead,
}
