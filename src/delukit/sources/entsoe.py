"""Raw ENTSO-E Transparency XML, one file per day.

Layout: data/bronze/<day>/entsoe/<category>/data.xml
"""

import logging
import os
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

import requests

from delukit.core.config import BASE_DIR, REFRESH_DAYS, TIMEZONE
from delukit.core.config.entsoe import ENTSOE_URL, entsoe_params
from delukit.core.parallel import RateLimited, run_parallel

log = logging.getLogger(__name__)

REQUEST_GAP = 1.0  # per worker; 6 workers ≈ 360 req/min, under the 400 limit
WORKERS = 6
RETRY_GAP = 60  # token banned ~10 min on abuse; leftovers resume next run
MAX_RETRIES = 3


def _window(day):
    """Day in Berlin as a UTC periodStart/periodEnd pair (YYYYMMDDHHMM)."""
    tz = ZoneInfo(TIMEZONE)
    start = datetime.combine(day, dtime.min, tz).astimezone(ZoneInfo("UTC"))
    end = datetime.combine(day + timedelta(days=1), dtime.min, tz).astimezone(
        ZoneInfo("UTC")
    )
    return start.strftime("%Y%m%d%H%M"), end.strftime("%Y%m%d%H%M")


def _download(session, category, day):
    start, end = _window(day)
    params = {
        **entsoe_params[category],
        "securityToken": os.environ["ENTSOE_API_KEY"],
        "periodStart": start,
        "periodEnd": end,
    }
    for attempt in range(MAX_RETRIES + 1):
        time.sleep(REQUEST_GAP)
        response = session.get(ENTSOE_URL, params=params, timeout=60)
        if response.status_code == 429 and attempt < MAX_RETRIES:
            log.warning("rate limited, sleeping %ss: %s %s", RETRY_GAP, category, day)
            time.sleep(RETRY_GAP)
            continue
        if response.status_code in (500, 502, 503, 504) and attempt < MAX_RETRIES:
            time.sleep(5 * (attempt + 1))
            continue
        if response.status_code == 429:
            raise RateLimited(f"{category} {day}")
        response.raise_for_status()
        return response.content
    raise RateLimited(f"{category} {day}")


def _parse(body):
    """Raw bytes, or None when the API reports no data for the day."""
    if b"No matching data found" in body:
        return None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return False
    if not any(e.tag.rsplit("}", 1)[-1] == "TimeSeries" for e in root.iter()):
        return None
    return body


def _cached(category, day, today):
    path = BASE_DIR / day.isoformat() / "entsoe" / category / "data.xml"
    return path.exists() and (today - day).days > REFRESH_DAYS


def fetch_day(category, day, today=None, session=None):
    path = BASE_DIR / day.isoformat() / "entsoe" / category / "data.xml"
    today = today or datetime.now(ZoneInfo(TIMEZONE)).date()

    if _cached(category, day, today):
        return "unchanged"

    own = session is None
    session = session or requests.Session()
    try:
        body = _parse(_download(session, category, day))
    finally:
        if own:
            session.close()
    if body is None:
        return "unchanged" if path.exists() else "no_data"
    if body is False:
        raise ValueError(f"invalid XML: {category} {day}")

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
    skipped = 0
    day = start
    while day <= end:
        for category in entsoe_params:
            if _cached(category, day, today):
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
            lambda c, d: fetch_day(c, d, today=today, session=session),
            WORKERS,
            on_each,
        )
    counts["unchanged"] += skipped
    return counts


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
