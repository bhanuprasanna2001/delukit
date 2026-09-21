"""Raw SMARD XML exports, one file per day.

Layout: data/bronze/<day>/smard/<category>/data.xml
"""

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

import requests

from delukit.core.config import BASE_DIR, REFRESH_DAYS, TIMEZONE
from delukit.core.config.smard import (
    SMARD_REGION,
    SMARD_RESOLUTION,
    SMARD_URL,
    smard_modules,
)
from delukit.core.parallel import run_parallel

log = logging.getLogger(__name__)

REQUEST_GAP = 1.0  # per worker; 4 workers ≈ 4 req/s
WORKERS = 4
MAX_RETRIES = 3

# <Header> carries the server's export timestamp, not data; ignore it or
# every re-fetch looks "updated".
_HEADER = re.compile(rb"<Header>.*?</Header>", re.DOTALL)


def _comparable(body):
    return _HEADER.sub(b"", body)


def _body(category, day):
    tz = ZoneInfo(TIMEZONE)
    start = datetime.combine(day, dtime.min, tz)
    end = datetime.combine(day + timedelta(days=1), dtime.min, tz)
    return {
        "request_form": [
            {
                "moduleIds": list(smard_modules[category]),
                "region": SMARD_REGION,
                "resolution": SMARD_RESOLUTION,
                "format": "XML",
                "timestamp_from": int(start.timestamp() * 1_000),
                "timestamp_to": int(end.timestamp() * 1_000),
                "type": "discrete",
                "language": "en",
            }
        ]
    }


def _download(session, category, day):
    for attempt in range(MAX_RETRIES + 1):
        time.sleep(REQUEST_GAP)
        try:
            response = session.post(SMARD_URL, json=_body(category, day), timeout=60)
        except requests.RequestException:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)
            continue
        if response.status_code in (429, 500, 502, 503, 504) and attempt < MAX_RETRIES:
            time.sleep(2**attempt)
            continue
        response.raise_for_status()
        return response.content
    raise RuntimeError("unreachable")


def _parse(body):
    """Raw bytes, None for an empty export, False for invalid XML."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return False
    if root.tag != "Categories" or not root.findall("Category"):
        return False
    if not root.findall("./Category/Components/Component"):
        return None
    return body


def _cached(category, day, today):
    path = BASE_DIR / day.isoformat() / "smard" / category / "data.xml"
    return path.exists() and (today - day).days > REFRESH_DAYS


def fetch_day(category, day, today=None, session=None):
    path = BASE_DIR / day.isoformat() / "smard" / category / "data.xml"
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

    if path.exists() and _comparable(path.read_bytes()) == _comparable(body):
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
        for category in smard_modules:
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
