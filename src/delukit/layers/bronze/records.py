"""Bronze records: fetched payloads become landing rows.

One row per (day, key) payload with the semantic hash attached. Days with
no payloads are skipped, so gaps in a source's history never appear as
rows; the pipeline retries them through its refresh window on later runs.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from delukit.layers.bronze.semantic import semantic_hash

RECORD_COLUMNS = ["source", "day", "key", "payload", "payload_hash", "fetched_at"]


def make_records(
    source: str, raws: dict[Any, dict[str, Any]], fetched_at: datetime
) -> list[dict]:
    """Turn a source's fetch result into bronze rows.

    Text payloads are stored byte-for-byte; structured payloads (weather)
    are serialized to JSON. fetched_at is the same for every row of a run.
    """
    rows: list[dict] = []
    for day, documents in raws.items():
        for key, payload in documents.items():
            text = payload if isinstance(payload, str) else json.dumps(payload)
            rows.append(
                {
                    "source": source,
                    "day": day,
                    "key": key,
                    "payload": text,
                    "payload_hash": semantic_hash(source, payload),
                    "fetched_at": fetched_at,
                }
            )
    return rows
