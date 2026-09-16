"""
Weather — ECMWF IFS HRES forecasts from the Open-Meteo Single Runs API.

Extract:
    1. Forecast runs initialised 00:00 UTC, full 16-day horizon requested
       (IFS issues 15 days of data; the trailing day is null and trimmed
       in silver).

Locations are grouped by cell selection: land cities get land grid cells,
offshore points get sea grid cells.

Rate limit: 600 req/min (Open-Meteo free tier), 60 req/min applied.
"""

from delukit.sources.weather.ecmwf import WeatherSource

__all__ = ["WeatherSource"]
