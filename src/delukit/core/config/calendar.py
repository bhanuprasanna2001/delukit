"""OpenHolidays public and school holidays for the DE-LU bidding zone.

One category per country; downstream combines DE and LU with OR.
Subdivision detail stays in the daily file (no per-state categories).
"""

from pathlib import Path

OPENHOLIDAYS_PUBLIC_URL = "https://openholidaysapi.org/PublicHolidays"
OPENHOLIDAYS_SCHOOL_URL = "https://openholidaysapi.org/SchoolHolidays"
OPENHOLIDAYS_CACHE_DIR = Path("data/cache/openholidays")

calendar_countries = {
    "de": "DE",
    "lu": "LU",
}

# Feature snapshots need delivery days D+1..D+10, but the shared sync end is
# only D+1; calendar extends its own window to cover the horizon.
CALENDAR_AHEAD_DAYS = 10
