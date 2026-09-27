from pathlib import Path

OPENHOLIDAYS_PUBLIC_URL = "https://openholidaysapi.org/PublicHolidays"
OPENHOLIDAYS_SCHOOL_URL = "https://openholidaysapi.org/SchoolHolidays"
OPENHOLIDAYS_CACHE_DIR = Path("data/cache/openholidays")

calendar_countries = {
    "de": "DE",
    "lu": "LU",
}

CALENDAR_AHEAD_DAYS = 10
