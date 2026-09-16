"""Bronze semantic hashing: change detection over payload content.

Raw payloads carry volatile metadata (document ids, creation timestamps,
generation times), so byte-level hashes cannot tell "values changed" from
"created date changed". Each source gets a small normalizer that reduces a
payload to its data-bearing content; the hash covers only that, which is
what the bronze store dedupes on.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from typing import Any


def semantic_hash(source: str, payload: Any) -> str:
    """Sha256 hex digest of a payload's data-bearing content."""
    try:
        normalize = _NORMALIZERS[source]
    except KeyError:
        raise ValueError(f"unknown source: {source!r}") from None
    canonical = json.dumps(normalize(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1]


def _entsoe(payload: Any) -> list[str]:
    """TimeSeries subtrees only: excludes document mRID and createdDateTime.

    The TimeSeries-level mRID is an identifier, not data, so it is dropped
    too; positions, quantities and period structure all stay.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise ValueError(f"entsoe: unparseable payload: {error}") from error
    series: list[str] = []
    for element in root.iter():
        if _local_name(element.tag) != "TimeSeries":
            continue
        for child in list(element):
            if _local_name(child.tag) == "mRID":
                element.remove(child)
        series.append(ET.tostring(element, encoding="unicode"))
    if not series:
        raise ValueError("entsoe: no TimeSeries in payload")
    return series


def _json_document(source: str, payload: Any) -> dict:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as error:
        raise ValueError(f"{source}: unparseable payload: {error}") from error
    if not isinstance(data, dict):
        raise TypeError(f"{source}: payload must be a json object")
    return data


def _smard(payload: Any) -> Any:
    """Series only: meta_data holds timestamps/version info and is volatile."""
    data = _json_document("smard", payload)
    series = data.get("series")
    if not isinstance(series, list):
        raise TypeError("smard: series must be a list")
    return series


def _energy_charts(payload: Any) -> dict:
    """Timestamps and prices only: license_info and deprecated are metadata."""
    data = _json_document("energy_charts", payload)
    seconds = data.get("unix_seconds")
    prices = data.get("price")
    if not isinstance(seconds, list) or not isinstance(prices, list):
        raise TypeError("energy_charts: unix_seconds and price must be lists")
    return {"unix_seconds": seconds, "price": prices, "unit": data.get("unit")}


def _weather(payload: Any) -> dict:
    """Hourly values per location: generationtime_ms and site metadata vary
    per request even when the forecast itself did not change."""
    if not isinstance(payload, dict):
        raise TypeError("weather: payload must be a json object")
    locations = payload.get("locations")
    if not isinstance(locations, dict) or not locations:
        raise TypeError("weather: locations must be a non-empty object")
    return {
        "run": payload.get("run"),
        "model": payload.get("model"),
        "locations": {
            name: {"hourly": item.get("hourly")}
            for name, item in locations.items()
            if isinstance(item, dict) and isinstance(item.get("hourly"), dict)
        },
    }


_NORMALIZERS = {
    "smard": _smard,
    "entsoe": _entsoe,
    "energy_charts": _energy_charts,
    "weather": _weather,
}
