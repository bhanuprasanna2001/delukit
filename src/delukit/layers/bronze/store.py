"""Bronze stores: the BronzeStore port plus local and SQL adapters.

Table text comes from layers.bronze.tables; connection mechanics from
delukit.backends. One SqlBronzeStore serves every SQL backend through its
dialect — a new backend adds statements in tables.py, never a new class.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Literal, overload

import pandas as pd

from delukit.backends import build_backend
from delukit.backends.base import (
    SqlBackend,
    is_missing_table,
    label_colour,
    marker,
    normalize_day,
    run_batched,
)
from delukit.layers.bronze import tables

# ponytail: row cap, not just bytes — bronze weather rows (~490k chars)
# always land alone while small rows still batch up.
_MAX_ROWS = 20


class BronzeStore(ABC):
    """Lands bronze records into one backend.

    write() must be idempotent: records whose (source, day, key,
    payload_hash) identity already exists are skipped, everything else is
    appended as a fresh version.
    """

    @abstractmethod
    def write(self, records: list[dict]) -> int:
        """Write records not already stored; return the number written."""

    @abstractmethod
    def coverage(self) -> set[tuple[str, date]]:
        """Stored (source, day) pairs; days normalized to date objects."""

    @abstractmethod
    def identities(self) -> set[tuple[str, date, str, str]]:
        """Stored (source, day, key, payload_hash) identities."""


class LocalBronzeStore(BronzeStore):
    """One append-only parquet table: <root>/bronze/payloads.parquet."""

    def __init__(self, root: str | Path = "delukit_store"):
        self.root = Path(root)
        self.file = self.root / "bronze" / "payloads.parquet"

    def write(self, records: list[dict]) -> int:
        if not records:
            return 0
        new = pd.DataFrame(records, columns=tables.RECORD_COLUMNS)
        new["day"] = pd.to_datetime(new["day"])
        new["fetched_at"] = pd.to_datetime(new["fetched_at"])
        new = new.drop_duplicates(subset=tables.IDENTITY_COLUMNS)
        if self.file.is_file():
            old = pd.read_parquet(self.file)
            # ponytail: tuple-scan dedupe; switch to a hash-keyed merge if the
            # table ever grows past ~1M rows
            seen = set(old[tables.IDENTITY_COLUMNS].apply(tuple, axis=1))
            new = new[~new[tables.IDENTITY_COLUMNS].apply(tuple, axis=1).isin(seen)]
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

    def identities(self) -> set[tuple[str, date, str, str]]:
        """Stored (source, day, key, payload_hash) identities."""
        if not self.file.is_file():
            return set()
        frame = pd.read_parquet(
            self.file, columns=["source", "day", "key", "payload_hash"]
        )
        return {
            (row.source, row.day.date(), row.key, row.payload_hash)
            for row in frame.itertuples()
        }

    def records_for(self, wanted: set[tuple[str, date, str, str]]) -> list[dict]:
        """Full records for the given identities, oldest day first."""
        if not wanted or not self.file.is_file():
            return []
        frame = pd.read_parquet(self.file)
        rows: list[dict] = []
        for row in frame.itertuples():
            ident = (row.source, row.day.date(), row.key, row.payload_hash)
            if ident not in wanted:
                continue
            rows.append(
                {
                    "source": row.source,
                    "day": row.day.date(),
                    "key": row.key,
                    "payload": row.payload,
                    "payload_hash": row.payload_hash,
                    "fetched_at": row.fetched_at.to_pydatetime()
                    if hasattr(row.fetched_at, "to_pydatetime")
                    else row.fetched_at,
                }
            )
        rows.sort(key=lambda r: (r["source"], r["day"], r["key"], r["payload_hash"]))
        return rows


class SqlBronzeStore(BronzeStore):
    """Insert-only MERGE on the identity; dialect comes from the backend."""

    def __init__(self, backend: SqlBackend, table: str | None = None):
        self.backend = backend
        self.table = table or tables.table_name(backend.name)

    def write(self, records: list[dict]) -> int:
        rows = [
            [record[column] for column in tables.RECORD_COLUMNS] for record in records
        ]
        return run_batched(
            self.backend.connection,
            tables.ddl(self.backend.name, self.table),
            tables.merge_sql(self.backend.name, self.table),
            rows,
            marker=marker(self.backend.name),
            label=f"{self.backend.name} bronze",
            colour=label_colour(self.backend.name),
            max_rows=_MAX_ROWS,
        )

    def coverage(self) -> set[tuple[str, date]]:
        rows = self._select(tables.coverage_sql(self.backend.name, self.table))
        return {(source, normalize_day(day)) for source, day in rows}

    def identities(self) -> set[tuple[str, date, str, str]]:
        rows = self._select(tables.identities_sql(self.backend.name, self.table))
        return {
            (source, normalize_day(day), key, payload_hash)
            for source, day, key, payload_hash in rows
        }

    def _select(self, sql: str) -> list:
        try:
            with self.backend.connection.cursor() as cursor:
                cursor.execute(sql)
                return cursor.fetchall()
        except Exception as error:
            if is_missing_table(error):
                return []
            raise


@overload
def build_bronze_store(name: Literal["local"], **kwargs) -> LocalBronzeStore: ...


@overload
def build_bronze_store(name: str, **kwargs) -> BronzeStore: ...


def build_bronze_store(name: str, **kwargs) -> BronzeStore:
    """Build a bronze store by backend name."""
    if name == "local":
        return LocalBronzeStore(root=kwargs.get("root", "delukit_store"))
    backend = build_backend(name, connection=kwargs.get("connection"))
    if not isinstance(backend, SqlBackend):
        raise TypeError(f"expected SqlBackend, got {type(backend).__name__}")
    return SqlBronzeStore(backend, table=kwargs.get("table"))
