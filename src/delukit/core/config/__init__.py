"""Shared bronze-sync settings (used by every source)."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = "Europe/Berlin"

BASE_DIR = Path("data/bronze")

# Days with no local file yet are always fetched. Files younger than this are
# re-fetched every run because providers revise recent data in place.
REFRESH_DAYS = 7

START = date(2025, 10, 1)


def end_date():
    return datetime.now(ZoneInfo("Europe/Berlin")).date() + timedelta(days=1)


# Back-compat: `from delukit.core.config import <SOURCE_...>` keeps working.
from delukit.core.config.entsoe import (
    ENTSOE_AREA,
    ENTSOE_URL,
    entsoe_params,
)
from delukit.core.config.smard import (
    SMARD_REGION,
    SMARD_RESOLUTION,
    SMARD_URL,
    smard_modules,
)
from delukit.core.config.weather import (
    WEATHER_FIELDS,
    WEATHER_FORECAST_DAYS,
    WEATHER_LOCATIONS,
    WEATHER_MODEL,
    WEATHER_URL,
)

__all__ = [
    "BASE_DIR",
    "ENTSOE_AREA",
    "ENTSOE_URL",
    "REFRESH_DAYS",
    "SMARD_REGION",
    "SMARD_RESOLUTION",
    "SMARD_URL",
    "START",
    "TIMEZONE",
    "WEATHER_FIELDS",
    "WEATHER_FORECAST_DAYS",
    "WEATHER_LOCATIONS",
    "WEATHER_MODEL",
    "WEATHER_URL",
    "end_date",
    "entsoe_params",
    "smard_modules",
]
