"""Raw ENTSO-E Transparency XML, one file per day.

Layout: data/raw/<day>/entsoe/<category>/data.xml
"""

import logging
import os
import re
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

# Document <mRID> (random hex per response) and <createdDateTime> (fetch time)
# are envelope metadata, not data; ignore them or every re-fetch looks
# "updated". TimeSeries <mRID>1,2,..</TimeSeries> are stable indexes, kept.
# Same idea as smard's <Header> strip.
_VOLATILE = re.compile(
    rb"<mRID>[0-9a-fA-F]{32}</mRID>"
    rb"|<createdDateTime>.*?</createdDateTime>"
    rb"|<revisionNumber>.*?</revisionNumber>",
    re.DOTALL,
)


def _comparable(body):
    return _VOLATILE.sub(b"", body)


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


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _series_key(category, header):
    if category == "SDAC":
        return f"price_sdac_seq{header['seq']}_eur_mwh"
    if category == "EXAA":
        return "price_exaa_eur_mwh"
    if category == "load_actual":
        return "load_actual_mw"
    if category == "load_forecast":
        return "load_forecast_mw"
    if category == "generation_forecast":
        return "gen_forecast_total_mw"
    if category == "generation_wind_solar_forecast":
        return {
            "B16": "solar_forecast_mw",
            "B18": "wind_offshore_forecast_mw",
            "B19": "wind_onshore_forecast_mw",
        }[header["psr"]]
    if category == "generation_actual":
        # B10 metered twice: pumping (outBiddingZone) vs turbine (inBiddingZone).
        suffix = ""
        if header["psr"] == "B10":
            suffix = "_inBZ" if header["in_bz"] else "_outBZ"
        return f"gen_actual_{header['psr']}{suffix}_mw"
    raise ValueError(f"unknown ENTSO-E category: {category}")


def _read_file(path):
    """{series_key: {timestamp_utc: value}} for one raw day-file."""
    import pandas as pd

    root = ET.parse(path).getroot()
    out = {}
    for ts in root.iter():
        if _local(ts.tag) != "TimeSeries":
            continue
        header = {"seq": None, "psr": None, "in_bz": False}
        period = None
        for child in ts:
            name = _local(child.tag)
            if name == "Period":
                period = child
            elif name == "classificationSequence_AttributeInstanceComponent.position":
                header["seq"] = child.text
            elif name == "MktPSRType":
                header["psr"] = next(
                    c.text for c in child if _local(c.tag) == "psrType"
                )
            elif name == "inBiddingZone_Domain.mRID":
                header["in_bz"] = True
        match = re.fullmatch(r"PT(\d+)([MH])", _text(period, "resolution"))
        step = int(match.group(1)) * (60 if match.group(2) == "H" else 1)
        start = _period_start(period)
        key = _series_key(path.parent.name, header)
        series = out.setdefault(key, {})
        for point in period:
            if _local(point.tag) != "Point":
                continue
            pos, value = None, None
            for field in point:
                fname = _local(field.tag)
                if fname == "position":
                    pos = int(field.text)
                elif fname in ("quantity", "price.amount"):
                    value = float(field.text)
            stamp = start + timedelta(minutes=step * (pos - 1))
            series[pd.Timestamp(stamp)] = value
    return out


def _text(period, name):
    for child in period:
        if _local(child.tag) == name:
            return child.text
    raise ValueError(f"missing <{name}> in ENTSO-E Period")


def _period_start(period):
    for child in period:
        if _local(child.tag) == "timeInterval":
            for field in child:
                if _local(field.tag) == "start":
                    return datetime.fromisoformat(field.text)
    raise ValueError("missing Period timeInterval start")


def to_clean(days=None):
    """Parse every raw day-file into data/clean/entsoe.parquet.

    NaN on gaps, except solar: the TSO omits night quarters (PV is zero),
    so a partial solar series is completed with 0. Missing files stay NaN.
    """
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
        for category in entsoe_params:
            path = BASE_DIR / day.isoformat() / "entsoe" / category / "data.xml"
            if not path.exists():
                continue
            result = _read_file(path)
            solar = result.get("solar_forecast_mw")
            if solar is not None and sum(pd.notna(v) for v in solar.values()) >= 10:
                for ts in quarter_grid(day):
                    solar.setdefault(pd.Timestamp(ts), 0.0)
            for key, series in result.items():
                columns.setdefault(key, {}).update(series)
    idx = master_index(days)
    df = frame(idx)
    for key, series in columns.items():
        df[key] = pd.Series(series).groupby(level=0).last().reindex(idx)
    path = write_clean(df, "entsoe")
    log.info("clean entsoe: %d rows x %d cols -> %s", len(df), len(df.columns), path)
    return path


if __name__ == "__main__":
    import sys

    sync(date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2]))
