"""Raw SMARD XML exports, one file per day.

Layout: data/raw/<day>/smard/<category>/data.xml
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


def _number(text):
    text = text.strip().replace(",", "")
    return float("nan") if text in ("", "-") else float(text)


def _slug(name):
    return name.lower().replace("/", "_").replace(" ", "_").replace("-", "_")


def _columns(category, components):
    """Canonical clean names for a category's components, in file order."""
    if category in ("day_ahead_prices", "load_actual", "load_forecast"):
        return {
            "day_ahead_prices": "price_day_ahead_eur_mwh",
            "load_actual": "load_actual_mwh",
            "load_forecast": "load_forecast_mwh",
        }[category]
    prefix = "gen_actual" if category == "generation_actual" else "gen_forecast"
    return [f"{prefix}_{_slug(c.findtext('Component_name'))}_mwh" for c in components]


def to_clean(days=None):
    """Parse every raw day-file into data/clean/smard.parquet (NaN on gaps)."""
    import pandas as pd

    from delukit.core.clean import (
        frame,
        master_index,
        quarter_grid,
        raw_days,
        write_clean,
    )

    days = days or raw_days()
    columns = {}
    for day in days:
        grid = quarter_grid(day)
        for category in smard_modules:
            path = BASE_DIR / day.isoformat() / "smard" / category / "data.xml"
            if not path.exists():
                continue
            root = ET.parse(path).getroot()
            components = root.find("Category").find("Components").findall("Component")
            names = _columns(category, components)
            if isinstance(names, str):
                names = [names]
            for name, comp in zip(names, components, strict=True):
                # Positional mapping: i-th value is the i-th quarter of the
                # Berlin day. This survives the duplicated 2am hour on
                # fall-back days; values past midnight belong to next day.
                values = comp.find("Values").findall("Value_detail")
                if len(values) < len(grid):
                    log.warning(
                        "smard %s %s: only %d values for %d quarters",
                        category,
                        day,
                        len(values),
                        len(grid),
                    )
                series = columns.setdefault(name, {})
                for stamp, detail in zip(grid, values, strict=False):
                    series[stamp] = _number(detail.findtext("Value"))
    idx = master_index(days)
    df = frame(idx)
    for key, series in columns.items():
        df[key] = pd.Series(series).groupby(level=0).last().reindex(idx)
    path = write_clean(df, "smard")
    log.info("clean smard: %d rows x %d cols -> %s", len(df), len(df.columns), path)
    return path


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
