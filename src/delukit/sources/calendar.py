"""DE-LU calendar, one file per day and country.

Layout: data/raw/<day>/calendar/<de|lu>/data.json

Each file holds that day's deterministic date parts (Monday=0 day_of_week,
weekend), nationwide public-holiday flags, plus the regional detail shaping
zone load: per-subdivision public holidays (e.g. Assumption Day in BY/SL)
and school holidays. Downstream combines DE and LU with OR -- the same
holiday/weekend/school-break dummies day-ahead price models use as exogenous
regressors (OpenSTEF HolidayFeatureAdder, EPFToolbox, mlforecast X_df).

Raw API payloads are cached per country, kind and year under
data/cache/openholidays/<ISO>/<public|school>/<year>.json. Years are fetched
one at a time, always inside the API's 3-year per-request limit. Past years
are immutable; the current and future years re-fetch when older than
REFRESH_DAYS, and daily files are rewritten when the flags change.

``is_holiday`` / ``is_bridge_day`` stay nationwide: a single state's holiday
doesn't move zone-level load, and bridge days are a national long-weekend
effect. Subdivision detail is kept verbatim for downstream weighting.
"""

import json
import logging
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from delukit.core.config import BASE_DIR, REFRESH_DAYS, TIMEZONE
from delukit.core.config.calendar import (
    OPENHOLIDAYS_CACHE_DIR,
    OPENHOLIDAYS_PUBLIC_URL,
    OPENHOLIDAYS_SCHOOL_URL,
    calendar_countries,
)
from delukit.core.parallel import run_parallel

log = logging.getLogger(__name__)

REQUEST_GAP = 1.0
WORKERS = 2
MAX_RETRIES = 3

KINDS = {
    "public": OPENHOLIDAYS_PUBLIC_URL,
    "school": OPENHOLIDAYS_SCHOOL_URL,
}

_throttle_lock = threading.Lock()
_last_request = 0.0
_fetch_lock = threading.Lock()


def _throttle():
    """Space requests REQUEST_GAP apart across all workers."""
    global _last_request
    with _throttle_lock:
        wait = _last_request + REQUEST_GAP - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _download(session, kind, iso, year):
    params = {
        "countryIsoCode": iso,
        "languageIsoCode": "EN",
        "validFrom": f"{year}-01-01",
        "validTo": f"{year}-12-31",
    }
    for attempt in range(MAX_RETRIES + 1):
        _throttle()
        try:
            response = session.get(
                KINDS[kind],
                params=params,
                headers={"accept": "text/json"},
                timeout=60,
            )
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504):
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            time.sleep(2**attempt)
            continue
        response.raise_for_status()
        return response.content
    raise RuntimeError("unreachable")


def _dates(record):
    start_value = record.get("startDate")
    end_value = record.get("endDate")
    if not isinstance(start_value, str) or not isinstance(end_value, str):
        raise TypeError("holiday dates must be strings")
    start = date.fromisoformat(start_value)
    end = date.fromisoformat(end_value)
    if start.isoformat() != start_value or end.isoformat() != end_value:
        raise ValueError("holiday dates must be ISO dates")
    if end < start:
        raise ValueError("holiday end date precedes start date")
    return start, end


def _subdivisions(record):
    subs = record.get("subdivisions") or []
    if not isinstance(subs, list) or not all(
        isinstance(entry, dict)
        and isinstance(entry.get("code"), str)
        and entry["code"]
        for entry in subs
    ):
        raise TypeError("holiday subdivisions must be [{code}]")
    return sorted({entry["code"] for entry in subs})


def _parse_records(payload, source, kind):
    try:
        records = json.loads(payload)
        if not isinstance(records, list):
            raise TypeError("payload is not an array")
        if not all(isinstance(record, dict) for record in records):
            raise TypeError("payload contains a non-object record")
        for record in records:
            _dates(record)
            _subdivisions(record)
            if kind == "public" and not isinstance(record.get("nationwide"), bool):
                raise TypeError("public holiday nationwide must be boolean")
    except (TypeError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        where = "cache" if source.startswith("cache:") else "response"
        raise ValueError(f"invalid OpenHolidays {where}: {source}") from error
    return records


def _nationwide_dates(records):
    """Nationwide public-holiday dates, expanding multi-day ranges."""
    holidays = set()
    for record in records:
        if not record.get("nationwide"):
            continue
        start, end = _dates(record)
        current = start
        while current <= end:
            holidays.add(current)
            current += timedelta(days=1)
    return holidays


def _fresh(path):
    return time.time() - path.stat().st_mtime < REFRESH_DAYS * 86400


def _year_records(session, kind, iso, year, today):
    """Raw records for one country/kind/year, from cache when usable."""
    path = OPENHOLIDAYS_CACHE_DIR / iso / kind / f"{year}.json"
    if path.exists() and (year < today.year or _fresh(path)):
        return _parse_records(path.read_bytes(), f"cache: {path}", kind)
    with _fetch_lock:  # one fetch per file; concurrent days share it
        if path.exists() and (year < today.year or _fresh(path)):
            return _parse_records(path.read_bytes(), f"cache: {path}", kind)
        payload = _download(session, kind, iso, year)
        records = _parse_records(payload, f"response: {iso}/{kind}/{year}", kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(path)
        return records


def _english_name(record):
    for entry in record.get("name") or []:
        if isinstance(entry, dict) and entry.get("language") == "EN":
            text = entry.get("text")
            if isinstance(text, str):
                return text
    return ""


def _covering(records, day, kind):
    """Entries covering ``day``, deduped across overlapping yearly caches."""
    out = []
    seen = set()
    for record in records:
        start, end = _dates(record)
        if not start <= day <= end:
            continue
        entry = {
            "name": _english_name(record),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "subdivisions": _subdivisions(record),
        }
        if kind == "public":
            entry["nationwide"] = record["nationwide"]
        key = (
            entry["name"],
            entry["start"],
            entry["end"],
            entry.get("nationwide"),
            tuple(entry["subdivisions"]),
        )
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return sorted(out, key=lambda entry: (entry["start"], entry["name"]))


def _document(iso, day, public, school):
    nationwide = _nationwide_dates(public)
    public_covering = _covering(public, day, "public")
    school_covering = _covering(school, day, "school")
    dow = day.weekday()  # Monday=0
    is_weekend = dow >= 5
    is_holiday = day in nationwide
    # Monday off the back of a Tuesday holiday, Friday off a Thursday one.
    is_bridge = (dow == 0 and day + timedelta(days=1) in nationwide) or (
        dow == 4 and day - timedelta(days=1) in nationwide
    )
    return {
        "date": day.isoformat(),
        "country": iso,
        "day_of_week": dow,
        "is_weekend": is_weekend,
        "is_holiday": is_holiday,
        "is_working_day": not is_weekend and not is_holiday,
        "is_bridge_day": is_bridge,
        "public_holidays": public_covering,
        "school_holidays": school_covering,
        "regional_public_subdivisions": sorted(
            {
                code
                for entry in public_covering
                if not entry["nationwide"]
                for code in entry["subdivisions"]
            }
        ),
        "school_subdivisions": sorted(
            {code for entry in school_covering for code in entry["subdivisions"]}
        ),
    }


def fetch_day(category, day, today=None, session=None):
    iso = calendar_countries[category]
    path = BASE_DIR / day.isoformat() / "calendar" / category / "data.json"
    today = today or datetime.now(ZoneInfo(TIMEZONE)).date()

    own = session is None
    session = session or requests.Session()
    try:
        # Neighbor years cover bridge checks and breaks at Jan 1 / Dec 31.
        years = sorted(
            {(day - timedelta(days=1)).year, day.year, (day + timedelta(days=1)).year}
        )
        public = [
            record
            for year in years
            for record in _year_records(session, "public", iso, year, today)
        ]
        school = [
            record
            for year in years
            for record in _year_records(session, "school", iso, year, today)
        ]
        body = (
            json.dumps(_document(iso, day, public, school), sort_keys=True, indent=2)
            .encode()
            + b"\n"
        )
    finally:
        if own:
            session.close()

    if path.exists() and path.read_bytes() == body:
        return "unchanged"

    state = "updated" if path.exists() else "fetched"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return state


def sync(start, end, on_each=None):
    today = end - timedelta(days=1)

    work = []
    day = start
    while day <= end:
        for category in calendar_countries:
            work.append((category, day))
        day += timedelta(days=1)

    with requests.Session() as session:
        session.headers.update({"user-agent": "delukit"})
        return run_parallel(
            work,
            lambda c, d: fetch_day(c, d, today=today, session=session),
            WORKERS,
            on_each,
        )


def _flags(doc):
    school = doc["school_subdivisions"]
    regional = doc["regional_public_subdivisions"]
    return {
        "is_holiday": doc["is_holiday"],
        "is_working_day": doc["is_working_day"],
        "is_bridge_day": doc["is_bridge_day"],
        "school_holiday": bool(school),
        "school_subdivisions": "|".join(school),
        "regional_public_subdivisions": "|".join(regional),
    }


def to_clean(days=None):
    """Expand daily raw files to quarter-hours: data/clean/calendar.parquet.

    Per-country flags keep their ``de_``/``lu_`` prefix; combined columns OR
    both countries, matching how zone load sees holidays.
    """
    import json

    import pandas as pd

    from delukit.core.clean import (
        frame,
        quarter_grid,
        raw_days,
        write_clean,
    )

    days = days or raw_days()
    rows = []
    for day in days:
        docs = {}
        for category in calendar_countries:
            path = BASE_DIR / day.isoformat() / "calendar" / category / "data.json"
            if path.exists():
                docs[category] = json.loads(path.read_bytes())
        if not docs:
            continue
        grid = quarter_grid(day)
        base = frame(grid).reset_index()
        de = _flags(docs["de"]) if "de" in docs else None
        lu = _flags(docs["lu"]) if "lu" in docs else None
        for _, row in base.iterrows():
            record = dict(row)
            for prefix, flags in (("de", de), ("lu", lu)):
                if flags is None:
                    continue
                for key, value in flags.items():
                    record[f"{prefix}_{key}"] = value
            weekend = docs.get("de", docs.get("lu"))["day_of_week"] >= 5
            de_hol = de["is_holiday"] if de else False
            lu_hol = lu["is_holiday"] if lu else False
            record["is_weekend"] = weekend
            record["is_holiday"] = de_hol or lu_hol
            record["is_working_day"] = not weekend and not record["is_holiday"]
            record["is_bridge_day"] = (de["is_bridge_day"] if de else False) or (
                lu["is_bridge_day"] if lu else False
            )
            record["school_holiday"] = (de["school_holiday"] if de else False) or (
                lu["school_holiday"] if lu else False
            )
            rows.append(record)
    df = pd.DataFrame(rows).set_index("timestamp_utc").sort_index()
    path = write_clean(df, "calendar")
    log.info("clean calendar: %d rows x %d cols -> %s", len(df), len(df.columns), path)
    return path


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
