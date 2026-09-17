"""Bronze store interface and the shared landing routine."""

from __future__ import annotations

import sys
from abc import ABC, abstractmethod

from tqdm import tqdm

from delukit.layers.bronze.records import RECORD_COLUMNS

# ponytail: row cap + byte cap; a batch flushes on whichever hits first.
# 800k chars sits under Databricks' 1M parameterized-query limit with room
# for connector overhead — a single weather row (~490k) always fits alone.
_BATCH_SIZE = 20
_MAX_PARAMS_CHARS = 800_000


class BronzeStore(ABC):
    """Lands bronze records into one backend.

    write() must be idempotent: records whose (source, day, key,
    payload_hash) identity already exists are skipped, everything else is
    appended as a fresh version.
    """

    @abstractmethod
    def write(self, records: list[dict]) -> int:
        """Write records not already stored; return the number written."""


def land_records(
    connection,
    ddl: tuple[str, ...],
    sql: str,
    records: list[dict],
    marker: str,
    table: str = "",
    label: str = "",
    colour: str | None = None,
    batch_size: int = _BATCH_SIZE,
) -> int:
    """Run DDL once, then land records in batched statements.

    Each batch is a single multi-row statement, which keeps round trips
    bounded instead of one per record (connector executemany is N
    sequential requests). Batches split on row count or estimated
    parameter size, whichever hits first, so giant payloads (weather)
    land one row per statement while small rows still batch up.
    Progress is shown on a tty only.
    """
    if not records:
        return 0
    with connection.cursor() as cursor:
        for statement in ddl:
            cursor.execute(statement)
        with tqdm(
            total=len(records),
            desc=label,
            unit="rows",
            colour=colour,
            disable=not sys.stderr.isatty(),
        ) as bar:
            for chunk in _batches(records, batch_size):
                rows = ", ".join(_row(marker) for _ in chunk)
                cursor.execute(
                    sql.format(table=table, values=rows), _flat_values(chunk)
                )
                bar.update(len(chunk))
    return len(records)


def _batches(records: list[dict], batch_size: int):
    """Yield chunks of at most batch_size rows or _MAX_PARAMS_CHARS."""
    batch, size = [], 0
    for record in records:
        need = _params_size(record)
        if batch and (len(batch) >= batch_size or size + need > _MAX_PARAMS_CHARS):
            yield batch
            batch, size = [], 0
        batch.append(record)
        size += need
    if batch:
        yield batch


def _params_size(record: dict) -> int:
    return sum(
        len(value) if isinstance(value, str) else 16
        for value in (_flat_values([record]))
    )


def _row(marker: str) -> str:
    return f"({', '.join([marker] * len(RECORD_COLUMNS))})"


def _flat_values(records: list[dict]) -> list:
    return [record[column] for record in records for column in RECORD_COLUMNS]
