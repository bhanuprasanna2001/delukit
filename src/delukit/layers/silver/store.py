"""Silver stores: the SilverStore port plus local and SQL adapters.

Table text comes from layers.silver.tables; connection mechanics from
delukit.backends. One SqlSilverStore serves every SQL backend through its
dialect — a new backend adds statements in tables.py, never a new class.

Local: <root>/silver/<domain>/<table>.parquet (pandas read-modify-write,
natural-key dedupe keep-last). Every upsert is idempotent: reprocessing
unchanged bronze is a no-op, revised payloads overwrite by natural key —
history lives in bronze only.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

import pandas as pd

from delukit.backends import build_backend
from delukit.backends.base import SqlBackend, label_colour, marker, run_batched
from delukit.layers.silver import tables

# ponytail: fixed 500-row chunks; a weather day (~25 locs x 384h x 8 cols)
# stays far under the 1M-char parameterized-query limit per statement.
_MAX_ROWS = 500

_DEFAULT_PREFIXES = {
    "databricks": "delukit.silver",
    "snowflake": "DELUKIT_DB.SILVER",
}


class SilverStore(ABC):
    """Upserts parsed frames into one backend."""

    @abstractmethod
    def upsert(self, table: str, frame: pd.DataFrame) -> int:
        """Merge frame rows by the table's natural key; return rows merged."""


class LocalSilverStore(SilverStore):
    def __init__(self, root: str | Path = "delukit_store"):
        self.root = Path(root)

    def upsert(self, table: str, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        keys = tables.keys_for_table(table)
        new = frame.drop_duplicates(subset=keys, keep="last")
        _, method = tables.split_table(table)
        path = self.root / "silver" / tables.domain_for(method) / f"{table}.parquet"
        if path.is_file():
            old = pd.read_parquet(path)
            # ponytail: full-file concat + dedupe; a keyed merge only if a
            # silver table ever grows past ~1M rows
            merged = pd.concat([old, new], ignore_index=True).drop_duplicates(
                subset=keys, keep="last"
            )
        else:
            merged = new
        path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_parquet(path, index=False)
        return len(new)


class SqlSilverStore(SilverStore):
    """Natural-key MERGE; dialect comes from the backend."""

    def __init__(self, backend: SqlBackend, prefix: str | None = None):
        self.backend = backend
        try:
            default = _DEFAULT_PREFIXES[backend.name]
        except KeyError:
            raise ValueError(f"unknown backend: {backend.name!r}") from None
        self.prefix = prefix or default

    def upsert(self, table: str, frame: pd.DataFrame) -> int:
        if frame.empty:
            return 0
        name = tables.table_name(self.backend.name, self.prefix, table)
        columns = list(frame.columns)
        keys = tables.keys_for_table(table)
        ddl = (
            f"CREATE SCHEMA IF NOT EXISTS {self.prefix}",
            (
                f"CREATE TABLE IF NOT EXISTS {name} "
                f"({tables.columns_ddl(frame, self.backend.name)})"
            ),
        )
        rows = [list(row) for row in frame.itertuples(index=False, name=None)]
        return run_batched(
            self.backend.connection,
            ddl,
            tables.merge_sql(self.backend.name, name, columns, keys),
            rows,
            marker=marker(self.backend.name),
            label=f"{self.backend.name} {table}",
            colour=label_colour(self.backend.name),
            max_rows=_MAX_ROWS,
        )


def build_silver_store(name: str, **kwargs) -> SilverStore:
    """Build a silver store by backend name."""
    if name == "local":
        return LocalSilverStore(root=kwargs.get("root", "delukit_store"))
    backend = build_backend(name, connection=kwargs.get("connection"))
    if not isinstance(backend, SqlBackend):
        raise TypeError(f"expected SqlBackend, got {type(backend).__name__}")
    return SqlSilverStore(backend, prefix=kwargs.get("prefix"))
