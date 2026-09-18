"""Silver loader: bronze versions collapse to the latest payload.

Reads the local bronze store (the pipeline's anchor, same as raw), picks
max(fetched_at) per (day, key) — ties break on max(payload_hash) so reruns
are deterministic — and groups back into each parser's expected shape:
{day: {key: payload}}. Weather payloads are deserialized to dicts (bronze
stores them JSON-encoded); every other source stays byte-for-byte text.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd


def load_latest(
    root: str | Path, source: str, start: date, end: date
) -> dict[date, dict[str, Any]]:
    """Latest bronze payload per (day, key) for one source in [start, end]."""
    file = Path(root) / "bronze" / "payloads.parquet"
    if not file.is_file():
        return {}
    frame = pd.read_parquet(file)
    frame = frame[frame["source"] == source]
    if frame.empty:
        return {}
    frame = frame.copy()
    frame["day"] = pd.to_datetime(frame["day"]).dt.date
    frame = frame[(frame["day"] >= start) & (frame["day"] <= end)]
    if frame.empty:
        return {}
    frame["fetched_at"] = pd.to_datetime(frame["fetched_at"])
    # ponytail: full-file sort + drop_duplicates; a keyed merge only if
    # bronze ever grows past ~1M rows (same ceiling as LocalBronzeStore.write)
    frame = frame.sort_values(
        ["fetched_at", "payload_hash"], ascending=[False, False]
    ).drop_duplicates(subset=["day", "key"], keep="first")
    out: dict[date, dict[str, Any]] = {}
    for row in frame.itertuples():
        payload = json.loads(row.payload) if source == "weather" else row.payload
        out.setdefault(row.day, {})[row.key] = payload
    return out
