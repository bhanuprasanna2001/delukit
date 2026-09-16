"""Bronze store interface and the shared landing routine."""

from __future__ import annotations

from abc import ABC, abstractmethod

from delukit.layers.bronze.records import RECORD_COLUMNS

# ponytail: fixed batch; raise it if payload sizes or counts grow
_BATCH_SIZE = 20


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
    batch_size: int = _BATCH_SIZE,
) -> int:
    """Run DDL once, then land records in batched statements.

    Each batch is a single multi-row statement, which keeps round trips
    bounded instead of one per record (connector executemany is N
    sequential requests).
    """
    if not records:
        return 0
    with connection.cursor() as cursor:
        for statement in ddl:
            cursor.execute(statement)
        for start in range(0, len(records), batch_size):
            chunk = records[start : start + batch_size]
            rows = ", ".join(_row(marker) for _ in chunk)
            cursor.execute(sql.format(table=table, values=rows), _flat_values(chunk))
    return len(records)


def _row(marker: str) -> str:
    return f"({', '.join([marker] * len(RECORD_COLUMNS))})"


def _flat_values(records: list[dict]) -> list:
    return [record[column] for record in records for column in RECORD_COLUMNS]
