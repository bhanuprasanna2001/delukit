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
