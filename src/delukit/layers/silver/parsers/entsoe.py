"""ENTSO-E silver: parse raw XML documents into clean per-day frames.

One day's raw documents (dict keyed by call key) in, one clean frame out:

    day_ahead_price    -> timestamp, price_eur_per_mwh, sequence
    load_actual        -> timestamp, load_mw
    load_forecast      -> timestamp, load_mw
    generation_actual  -> timestamp, generation_mw, psr_type
    generation_forecast-> timestamp, generation_mw, psr_type
"""

from __future__ import annotations

import warnings

import pandas as pd
from bs4 import XMLParsedAsHTMLWarning
from entsoe.parsers import PSRTYPE_MAPPINGS, parse_generation, parse_loads, parse_prices

# entsoe-py parses XML with html.parser (upstream issue #180); silence that noise.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

_DESCRIPTION_TO_CODE = {name: code for code, name in PSRTYPE_MAPPINGS.items()}


def parse_day(
    raws: dict[str, str],
    method: str,
    sequences: tuple[int, ...] = (1,),
    psr_types: list[str] | None = None,
    tz: str = "Europe/Berlin",
) -> pd.DataFrame:
    """Parse one day's raw documents for a method into one frame."""
    try:
        handler = _HANDLERS[method]
    except KeyError:
        raise ValueError(f"unknown entsoe method: {method!r}")
    try:
        return handler(raws, sequences, psr_types or [], tz)
    except Exception as error:
        raise ValueError(f"entsoe: unparseable {method} document: {error}") from error


def _frame(series: pd.Series, name: str, tz: str) -> pd.DataFrame:
    if series.empty:
        return pd.DataFrame(columns=["timestamp", name])
    df = series.to_frame(name)
    df.index = df.index.tz_convert(tz)
    return df.reset_index(names="timestamp")


def _day_ahead_price(raws, sequences, psr_types, tz) -> pd.DataFrame:
    frames = []
    for sequence in sequences:
        text = raws.get(f"day_ahead_price/{sequence}")
        if text is None:
            continue
        prices = parse_prices(text)
        series = next(
            (s for s in prices.values() if not s.empty), pd.Series(dtype=float)
        )
        frame = _frame(series, "price_eur_per_mwh", tz)
        frame["sequence"] = sequence
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _load(raws, key: str, process_type: str, tz: str) -> pd.DataFrame:
    text = raws.get(key)
    if text is None:
        return pd.DataFrame()
    df = parse_loads(text, process_type=process_type)
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "load_mw"])
    return _frame(df.iloc[:, 0], "load_mw", tz)


def _load_actual(raws, sequences, psr_types, tz) -> pd.DataFrame:
    return _load(raws, "load_actual", "A16", tz)


def _load_forecast(raws, sequences, psr_types, tz) -> pd.DataFrame:
    return _load(raws, "load_forecast", "A01", tz)


def _generation_actual(raws, sequences, psr_types, tz) -> pd.DataFrame:
    frames = []
    for psr_type in psr_types:
        text = raws.get(f"generation_actual/{psr_type}")
        if text is None:
            continue
        df = parse_generation(text, nett=False)
        if df.empty:
            continue
        frame = _frame(df.iloc[:, 0], "generation_mw", tz)
        frame["psr_type"] = psr_type
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _generation_forecast(raws, sequences, psr_types, tz) -> pd.DataFrame:
    text = raws.get("generation_forecast")
    if text is None:
        return pd.DataFrame()
    df = parse_generation(text, nett=True)
    if df.empty:
        return pd.DataFrame()
    long = df.stack().rename("generation_mw")
    long = long.rename_axis(["timestamp", "psr_type"])
    frame = long.reset_index()
    frame["timestamp"] = frame["timestamp"].dt.tz_convert(tz)
    frame["psr_type"] = frame["psr_type"].map(_DESCRIPTION_TO_CODE)
    if psr_types:
        frame = frame[frame["psr_type"].isin(psr_types)]
    return frame[["timestamp", "generation_mw", "psr_type"]].reset_index(drop=True)


_HANDLERS = {
    "day_ahead_price": _day_ahead_price,
    "load_actual": _load_actual,
    "load_forecast": _load_forecast,
    "generation_actual": _generation_actual,
    "generation_forecast": _generation_forecast,
}
