"""ENTSO-E source: raw client, per-day fetch, dispatch to method handlers.

Each day returns raw XML documents keyed by call key:
    day_ahead_price/1  day_ahead_price/2   (SDAC, EXAA)
    load_actual  load_forecast
    generation_actual/B16  ...   (one doc per requested psr type)
    generation_forecast            (one doc covering all wind/solar types)

Parsing is the silver layer's job (delukit.layers.silver.entsoe).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from entsoe import Area, EntsoeRawClient
from entsoe.exceptions import (
    InvalidBusinessParameterError,
    InvalidPSRTypeError,
    NoMatchingDataError,
    PaginationError,
)
from pyrate_limiter import Duration, Limiter, Rate

from delukit.sources.data_source import DataSource, SourceError

from . import (
    actual_generation,
    actual_load,
    exaa,
    forecast_generation,
    forecast_load,
    sdac,
)


def _day_ahead_price(
    source: EntsoeSource,
    day: date,
    area: Area,
    sequences: tuple[int, ...] = (1,),
) -> dict[str, str]:
    raws: dict[str, str] = {}
    for sequence in sequences:
        fetch = _SEQUENCE_HANDLERS[sequence]
        try:
            raws.update(fetch(source, day, area))
        except NoMatchingDataError:
            continue
    return raws


_SEQUENCE_HANDLERS = {1: sdac.fetch_day, 2: exaa.fetch_day}

_HANDLERS = {
    "day_ahead_price": _day_ahead_price,
    "load_actual": actual_load.fetch_day,
    "load_forecast": forecast_load.fetch_day,
    "generation_actual": actual_generation.fetch_day,
    "generation_forecast": forecast_generation.fetch_day,
}


class EntsoeSource(DataSource):
    name = "entsoe"
    limiter = Limiter(Rate(400, Duration.MINUTE))
    max_retries = 3

    def __init__(
        self, client: EntsoeRawClient | None = None, tz: str = "Europe/Berlin"
    ):
        try:
            self.client = client or EntsoeRawClient()
        except TypeError as error:
            raise SourceError(
                "entsoe: ENTSOE_API_KEY environment variable is not set"
            ) from error
        self.tz = tz

    def _fetch_day(self, day: date, method: str, **params) -> dict[str, str]:
        handler = _HANDLERS.get(method)
        if handler is None:
            raise SourceError(f"{self.name}: unknown method {method!r}")
        if "area" in params:
            params["area"] = self._area(params["area"])
        try:
            return handler(self, day, **params)
        except NoMatchingDataError:
            return {}
        except (
            InvalidBusinessParameterError,
            InvalidPSRTypeError,
            PaginationError,
        ) as error:
            raise SourceError(
                f"{self.name}: {error.__class__.__name__}: {error}"
            ) from error
        except Exception as error:
            error.add_note(f"source={self.name} method={method} day={day.isoformat()}")
            raise

    def _area(self, code: str) -> Area:
        try:
            return Area[code]
        except (KeyError, TypeError):
            raise SourceError(f"{self.name}: unknown area {code!r}")

    def _day_window(self, day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
        start = pd.Timestamp(day).tz_localize(self.tz)
        end = pd.Timestamp(day + timedelta(days=1)).tz_localize(self.tz)
        return start, end

    def _request_xml(self, fn, *args, **kwargs) -> str:
        text = self._call(fn, *args, **kwargs)
        if "<TimeSeries" not in text:
            raise SourceError(f"{self.name}: unexpected response, no TimeSeries in XML")
        return text
