"""Shared raw-sync settings (used by every source)."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = "Europe/Berlin"

BASE_DIR = Path("data/raw")
CLEAN_DIR = Path("data/clean")
VERSIONED_DIR = Path("data/versioned")

# Days with no local file yet are always fetched. Files younger than this are
# re-fetched every run because providers revise recent data in place.
REFRESH_DAYS = 7

START = date(2025, 10, 1)


def end_date():
    return datetime.now(ZoneInfo("Europe/Berlin")).date() + timedelta(days=1)


# Back-compat: `from delukit.core.config import <SOURCE_...>` keeps working.
from delukit.core.config.calendar import (
    OPENHOLIDAYS_CACHE_DIR,
    OPENHOLIDAYS_PUBLIC_URL,
    OPENHOLIDAYS_SCHOOL_URL,
    calendar_countries,
)
from delukit.core.config.energy_charts import (
    ENERGY_CHARTS_BZN,
    ENERGY_CHARTS_URL,
    energy_charts_categories,
)
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
    "CLEAN_DIR",
    "ENERGY_CHARTS_BZN",
    "ENERGY_CHARTS_URL",
    "ENTSOE_AREA",
    "ENTSOE_URL",
    "OPENHOLIDAYS_CACHE_DIR",
    "OPENHOLIDAYS_PUBLIC_URL",
    "OPENHOLIDAYS_SCHOOL_URL",
    "REFRESH_DAYS",
    "SMARD_REGION",
    "SMARD_RESOLUTION",
    "SMARD_URL",
    "START",
    "TIMEZONE",
    "VERSIONED_DIR",
    "WEATHER_FIELDS",
    "WEATHER_FORECAST_DAYS",
    "WEATHER_LOCATIONS",
    "WEATHER_MODEL",
    "WEATHER_URL",
    "calendar_countries",
    "end_date",
    "energy_charts_categories",
    "entsoe_params",
    "smard_modules",
]
