"""Raw Energy-Charts day-ahead prices, one file per day.

Layout: data/raw/<day>/energy_charts/day_ahead_price/data.json

DE-LU only. Prices are final once the day-ahead auction publishes, so a file
once written is never re-fetched; days with no data yet (404) retry next run.
"""

import json
import logging
import time
from datetime import date, timedelta

import requests

from delukit.core.config import BASE_DIR
from delukit.core.config.energy_charts import (
    ENERGY_CHARTS_BZN,
    ENERGY_CHARTS_URL,
    energy_charts_categories,
)
from delukit.core.parallel import RateLimited, run_parallel

log = logging.getLogger(__name__)

REQUEST_GAP = 1.0  # per worker; 2 workers stay under the stricter v1.5 limits
WORKERS = 2
RETRY_GAP = 60
MAX_RETRIES = 3


def _download(session, day):
    params = {
        "bzn": ENERGY_CHARTS_BZN,
        "start": day.isoformat(),
        "end": day.isoformat(),
    }
    for attempt in range(MAX_RETRIES + 1):
        time.sleep(REQUEST_GAP)
        try:
            response = session.get(ENERGY_CHARTS_URL, params=params, timeout=60)
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code == 404:  # auction not published yet
            return None
        if response.status_code == 429:
            if attempt == MAX_RETRIES:
                raise RateLimited(f"day_ahead_price {day}")
            log.warning("rate limited, sleeping %ss: day_ahead_price %s", RETRY_GAP, day)
            time.sleep(RETRY_GAP)
            continue
        if response.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
            time.sleep(2**attempt)
            continue
        response.raise_for_status()
        return response.content
    raise RateLimited(f"day_ahead_price {day}")


def _parse(body):
    """Raw bytes, None for an empty day, False for an invalid payload."""
    if body is None:
        return None
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(document, dict):
        return False
    stamps = document.get("unix_seconds")
    prices = document.get("price")
    if (
        not isinstance(stamps, list)
        or not isinstance(prices, list)
        or len(stamps) != len(prices)
        or not all(isinstance(s, (int, float)) for s in stamps)
        or not all(isinstance(p, (int, float)) for p in prices)
    ):
        return False
    if not stamps:
        return None
    return body


def fetch_day(category, day, session=None):
    if category not in energy_charts_categories:
        raise ValueError(f"unknown Energy-Charts category: {category}")
    path = BASE_DIR / day.isoformat() / "energy_charts" / category / "data.json"

    if path.exists():  # auction results never change; fetch each day once
        return "unchanged"

    own = session is None
    session = session or requests.Session()
    try:
        body = _parse(_download(session, day))
    finally:
        if own:
            session.close()
    if body is None:
        return "no_data"
    if body is False:
        raise ValueError(f"invalid JSON: {category} {day}")

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(body)
    tmp.replace(path)
    return "fetched"


def sync(start, end, on_each=None):
    work = []
    skipped = 0
    day = start
    while day <= end:
        for category in energy_charts_categories:
            if (BASE_DIR / day.isoformat() / "energy_charts" / category / "data.json").exists():
                skipped += 1
                if on_each:
                    on_each(category, day, "unchanged")
            else:
                work.append((category, day))
        day += timedelta(days=1)

    with requests.Session() as session:
        session.headers.update({"user-agent": "delukit"})
        counts = run_parallel(
            work,
            lambda c, d: fetch_day(c, d, session=session),
            WORKERS,
            on_each,
        )
    counts["unchanged"] += skipped
    return counts


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
