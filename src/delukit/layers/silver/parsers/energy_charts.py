"""Energy-Charts silver: parse raw JSON documents into clean per-day frames.

One day's raw documents (dict keyed by call key) in, one clean frame out:

    day_ahead_price    -> timestamp, price_eur_per_mwh, sequence
"""

from __future__ import annotations

import json

import pandas as pd

_UNIT = "EUR / MWh"


def parse_day(
    raws: dict[str, str],
    method: str,
    tz: str = "Europe/Berlin",
) -> pd.DataFrame:
    """Parse one day's raw documents for a method into one frame."""
    try:
        handler = _HANDLERS[method]
    except KeyError:
        raise ValueError(f"unknown energy_charts method: {method!r}")
    text = raws.get(method)
    if text is None:
        return pd.DataFrame()
    try:
        return handler(text, tz)
    except Exception as error:
        raise ValueError(
            f"energy_charts: unparseable {method} document: {error}"
        ) from error


def _day_ahead_price(text: str, tz: str) -> pd.DataFrame:
    data = json.loads(text)
    if not isinstance(data, dict):
        raise TypeError("expected a json object")
    seconds = data.get("unix_seconds")
    prices = data.get("price")
    if not isinstance(seconds, list) or not isinstance(prices, list):
        raise TypeError("unix_seconds and price must be lists")
    if len(seconds) != len(prices):
        raise ValueError("unix_seconds and price have different lengths")
    if data.get("unit") != _UNIT:
        raise ValueError(f"unexpected unit: {data.get('unit')!r}")
    if not seconds:
        return pd.DataFrame(columns=["timestamp", "price_eur_per_mwh", "sequence"])
    timestamps = pd.to_datetime(seconds, unit="s", utc=True).tz_convert(tz)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_per_mwh": prices,
            "sequence": 1,
        }
    )


_HANDLERS = {
    "day_ahead_price": _day_ahead_price,
}
