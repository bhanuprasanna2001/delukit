"""SMARD source: raw fetcher, per-day slicing, dispatch to method handlers.

SMARD serves whole weeks only (stamps = Monday 00:00 Berlin), so one day is
a slice of a memoized week payload:

    day_ahead_price                       -> SDAC DE-LU (filter 4169)
    load_actual / load_forecast           -> 410 / 411
    generation_actual/<type>              -> one doc per production type
    generation_forecast_day_ahead/<type>  -> one doc per type

Parsing is the silver layer's job (delukit.layers.silver.parsers.smard).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pandas as pd
import requests
from pyrate_limiter import Duration, Limiter, Rate

from delukit.sources.data_source import DataSource, SourceError

from . import actual_generation, actual_load, forecast_generation, forecast_load, sdac

_HANDLERS = {
    "day_ahead_price": sdac.fetch_day,
    "load_actual": actual_load.fetch_day,
    "load_forecast": forecast_load.fetch_day,
    "generation_actual": actual_generation.fetch_day,
    "generation_forecast_day_ahead": forecast_generation.fetch_day_ahead,
}

_REGIONS = {"DE": "DE", "DE_LU": "DE-LU", "DE_AT_LU": "DE-AT-LU"}
_RESOLUTIONS = {"15min": "quarterhour", "hour": "hour"}
BASE_URL = "https://www.smard.de/app/chart_data"


class SmardSource(DataSource):
    """Fetches SMARD chart_data JSON, one raw day-document per call key."""

    name = "smard"
    limiter = Limiter(Rate(30, Duration.MINUTE))
    max_retries = 3

    def __init__(
        self, session: requests.Session | None = None, tz: str = "Europe/Berlin"
    ):
        self.session = session or requests.Session()
        self.tz = tz
        # ponytail: per-run week cache; restart if multi-week runs across days matter
        self._weeks: dict[tuple, dict | None] = {}

    def _fetch_day(self, day: date, method: str, **params) -> dict[str, str]:
        handler = _HANDLERS.get(method)
        if handler is None:
            raise SourceError(f"{self.name}: unknown method {method!r}")
        try:
            return handler(self, day, **params)
        except Exception as error:
            error.add_note(f"source={self.name} method={method} day={day.isoformat()}")
            raise

    def _day_payload(
        self, day: date, filter_id: int, key: str, area: str, resolution: str
    ) -> dict[str, str]:
        """One day's slice of a week document, keyed by call key."""
        week = self._week(
            filter_id,
            self._region(area),
            self._resolution(resolution),
            self._week_stamp(day),
        )
        if week is None:
            return {}
        start_ms, end_ms = self._day_window_ms(day)
        points = [
            point for point in week.get("series", []) if start_ms <= point[0] < end_ms
        ]
        return {
            key: json.dumps({"meta_data": week.get("meta_data", {}), "series": points})
        }

    def _week(
        self, filter_id: int, region: str, resolution: str, stamp: int
    ) -> dict | None:
        key = (filter_id, region, resolution, stamp)
        if key not in self._weeks:
            self._weeks[key] = self._fetch_week(filter_id, region, resolution, stamp)
        return self._weeks[key]

    def _fetch_week(self, filter_id: int, region: str, resolution: str, stamp: int):
        url = f"{BASE_URL}/{filter_id}/{region}/{filter_id}_{region}_{resolution}_{stamp}.json"
        text = self._request(url, allow_404=True)
        if text is None:
            return None
        return json.loads(text)

    def _request(self, url: str, allow_404: bool = False) -> str | None:
        def get() -> requests.Response:
            response = self.session.get(url, timeout=30)
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

    def _week_stamp(self, day: date) -> int:
        """SMARD week stamp: Monday 00:00 Berlin of the day's week, in ms UTC."""
        monday = day - timedelta(days=day.weekday())
        return pd.Timestamp(monday).tz_localize(self.tz).value // 1_000_000

    def _day_window_ms(self, day: date) -> tuple[int, int]:
        start = pd.Timestamp(day).tz_localize(self.tz).value // 1_000_000
        end = (
            pd.Timestamp(day + timedelta(days=1)).tz_localize(self.tz).value
            // 1_000_000
        )
        return start, end

    def _region(self, code: str) -> str:
        try:
            return _REGIONS[code]
        except (KeyError, TypeError):
            raise SourceError(f"{self.name}: unknown area {code!r}") from None

    def _resolution(self, resolution: str) -> str:
        try:
            return _RESOLUTIONS[resolution]
        except (KeyError, TypeError):
            raise SourceError(
                f"{self.name}: unknown resolution {resolution!r}"
            ) from None
