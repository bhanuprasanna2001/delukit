"""Energy-Charts source: raw client, per-day fetch, dispatch to method handlers.

Each day returns the raw JSON documents keyed by call key:
    day_ahead_price            (SDAC, DE-LU)

Parsing is the silver layer's job (delukit.layers.silver.parsers.energy_charts).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import requests
from pyrate_limiter import Duration, Limiter, Rate

from delukit.sources.data_source import DataSource, SourceError

from . import sdac

_HANDLERS = {
    "day_ahead_price": sdac.fetch_day,
}


class EnergyChartsSource(DataSource):
    name = "energy_charts"
    colour = "magenta"
    limiter = Limiter(Rate(2, Duration.MINUTE))
    max_retries = 3

    def __init__(
        self, session: requests.Session | None = None, tz: str = "Europe/Berlin"
    ):
        self.session = session or requests.Session()
        self.tz = tz

    def _fetch_day(self, day: date, method: str, **params) -> dict[str, str]:
        handler = _HANDLERS.get(method)
        if handler is None:
            raise SourceError(f"{self.name}: unknown method {method!r}")
        try:
            return handler(self, day, **params)
        except Exception as error:
            error.add_note(f"source={self.name} method={method} day={day.isoformat()}")
            raise

    def _day_window(self, day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
        start = pd.Timestamp(day).tz_localize(self.tz)
        end = pd.Timestamp(day + timedelta(days=1)).tz_localize(self.tz) - timedelta(
            minutes=1
        )
        return start, end

    def _request(
        self, url: str, params: dict[str, str], allow_404: bool = False
    ) -> str | None:
        def get() -> requests.Response:
            response = self.session.get(url, params=params, timeout=30)
            if response.status_code == 404 and allow_404:
                return response
            response.raise_for_status()
            return response

        response = self._call(get)
        if response.status_code == 404:
            return None
        text = response.text
        if not text.lstrip().startswith("{"):
            raise SourceError(f"{self.name}: unexpected response, not json")
        return text
