"""Weather source: ECMWF IFS HRES forecast runs via the Open-Meteo
Single Runs API.

Each day fetches the forecast run initialised that day at 00:00 UTC (the
latest run safely available before the EPEX day-ahead gate closure) and
returns one raw payload keyed by method:

    forecast -> {"run": "2025-10-01T00:00", "model": "ecmwf_ifs",
                 "locations": {name: api item, ...}}

The API applies one cell_selection per request, so locations are batched
per cell_selection group (land/sea/nearest). Response items are zipped
back to their location names in request order. A run that is not archived
yet (e.g. today's) yields an empty mapping for that day.

Parsing is the silver layer's job (delukit.layers.silver.parsers.weather).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

import requests
from pyrate_limiter import Duration, Limiter, Rate

from delukit.sources.data_source import DataSource, SourceError

_URL = "https://single-runs-api.open-meteo.com/v1/forecast"


class WeatherSource(DataSource):
    name = "weather"
    colour = "yellow"
    limiter = Limiter(Rate(60, Duration.MINUTE))
    max_retries = 3

    def __init__(
        self,
        locations: list[dict],
        fields: list[str],
        model: str = "ecmwf_ifs",
        forecast_days: int = 16,
        tz: str = "Europe/Berlin",
        session: requests.Session | None = None,
    ):
        self.locations = locations
        self.fields = fields
        self.model = model
        self.forecast_days = forecast_days
        self.tz = tz
        self.session = session or requests.Session()

    def _fetch_day(self, day: date) -> dict:
        run = f"{day.isoformat()}T00:00"
        groups: dict[str, list[dict]] = defaultdict(list)
        for location in self.locations:
            groups[location["cell_selection"]].append(location)
        locations: dict[str, dict] = {}
        for selection, group in groups.items():
            items = self._request_json(group, selection, run)
            if items is None:
                return {}
            for location, item in zip(group, items, strict=True):
                locations[location["name"]] = item
        return {"forecast": {"run": run, "model": self.model, "locations": locations}}

    def _request_json(self, group: list[dict], selection: str, run: str):
        params = {
            "latitude": ",".join(str(location["latitude"]) for location in group),
            "longitude": ",".join(str(location["longitude"]) for location in group),
            "models": self.model,
            "hourly": ",".join(self.fields),
            "forecast_days": self.forecast_days,
            "cell_selection": selection,
            "timezone": self.tz,
            "run": run,
        }

        def get():
            response = self.session.get(_URL, params=params, timeout=60)
            try:
                data = response.json()
            except ValueError:
                # ponytail: 2xx without json = run not archived yet (empty
                # body); heals on the next pipeline run, which refetches all
                # days. Other errors surface via raise_for_status.
                if response.status_code < 400:
                    return None
                response.raise_for_status()
                raise
            if isinstance(data, dict) and data.get("error"):
                reason = data.get("reason", "")
                if "run is not available" in reason:
                    return None
                if response.status_code < 500:
                    raise SourceError(f"{self.name}: {reason}")
            response.raise_for_status()
            return data

        return self._call(get)
