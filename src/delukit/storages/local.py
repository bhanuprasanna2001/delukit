"""Local bronze store: one append-only parquet table.

delukit_store/bronze/payloads.parquet holds every landed record across
sources; write() skips identities already present, so daily refetches of
unchanged payloads write nothing while revised payloads append a fresh
version. coverage() feeds the pipeline's fetch-watermark math.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from delukit.layers.bronze.records import RECORD_COLUMNS
from delukit.storages.base import BronzeStore

_IDENTITY = ["source", "day", "key", "payload_hash"]


class LocalStore(BronzeStore):
    def __init__(self, root: str | Path = "delukit_store"):
        self.file = Path(root) / "bronze" / "payloads.parquet"

    def write(self, records: list[dict]) -> int:
        if not records:
            return 0
        new = pd.DataFrame(records, columns=RECORD_COLUMNS)
        new["day"] = pd.to_datetime(new["day"])
        new["fetched_at"] = pd.to_datetime(new["fetched_at"])
        new = new.drop_duplicates(subset=_IDENTITY)
        if self.file.is_file():
            old = pd.read_parquet(self.file)
            # ponytail: tuple-scan dedupe; switch to a hash-keyed merge if the
            # table ever grows past ~1M rows
            seen = set(old[_IDENTITY].apply(tuple, axis=1))
            new = new[~new[_IDENTITY].apply(tuple, axis=1).isin(seen)]
            if new.empty:
                return 0
            frame = pd.concat([old, new], ignore_index=True)
        else:
            frame = new
        self.file.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(self.file, index=False)
        return len(new)

    def coverage(self) -> set[tuple[str, date]]:
        """Stored (source, day) pairs; days normalized to date objects."""
        if not self.file.is_file():
            return set()
        frame = pd.read_parquet(self.file, columns=["source", "day"])
        return {(row.source, row.day.date()) for row in frame.itertuples()}
