"""Bronze table knowledge: schema, identity, and per-dialect statements.

The only place bronze table/DDL/SQL text lives — backends only execute
it. The `delukit` catalog / `DELUKIT_DB` database must exist before the
first write (created once out of band); schema and table are created here.
"""

from __future__ import annotations

from delukit.backends.base import quote

RECORD_COLUMNS = ["source", "day", "key", "payload", "payload_hash", "fetched_at"]

IDENTITY_COLUMNS = ["source", "day", "key", "payload_hash"]

TABLE_NAMES = {
    "databricks": "delukit.bronze.payloads",
    "snowflake": "DELUKIT_DB.BRONZE.PAYLOADS",
}

_COLUMN_TYPES = {
    "databricks": {
        "source": "STRING",
        "day": "DATE",
        "key": "STRING",
        "payload": "STRING",
        "payload_hash": "STRING",
        "fetched_at": "TIMESTAMP",
    },
    "snowflake": {
        "source": "VARCHAR",
        "day": "DATE",
        "key": "VARCHAR",
        "payload": "VARCHAR",
        "payload_hash": "VARCHAR(64)",
        "fetched_at": "TIMESTAMP_NTZ",
    },
}


def table_name(backend: str) -> str:
    """Physical bronze table for a backend; raises on unknown backends."""
    try:
        return TABLE_NAMES[backend]
    except KeyError:
        raise ValueError(f"unknown backend: {backend!r}") from None


def ddl(backend: str, table: str) -> tuple[str, str]:
    """Schema + table creation; idempotent, runs on every write."""
    types = _types(backend)
    schema = table.rsplit(".", 1)[0]
    columns = ", ".join(
        f"{quote(backend, column)} {types[column]}" for column in RECORD_COLUMNS
    )
    return (
        f"CREATE SCHEMA IF NOT EXISTS {schema}",
        f"CREATE TABLE IF NOT EXISTS {table} ({columns})",
    )


def merge_sql(backend: str, table: str) -> str:
    """Insert-only MERGE on the identity; {values} filled per batch."""
    quoted = [quote(backend, column) for column in RECORD_COLUMNS]
    if backend == "snowflake":
        inner = ", ".join(f"${i + 1} AS {name}" for i, name in enumerate(quoted))
        using = f"(SELECT {inner} FROM VALUES {{values}})"
    elif backend == "databricks":
        using = f"(SELECT * FROM VALUES {{values}} AS v({', '.join(quoted)}))"
    else:
        raise ValueError(f"unknown backend: {backend!r}")
    identity = [quote(backend, column) for column in IDENTITY_COLUMNS]
    on = " AND ".join(f"target.{name} = s.{name}" for name in identity)
    return (
        f"MERGE INTO {table} AS target USING {using} AS s ON {on} "
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(quoted)}) "
        f"VALUES ({', '.join(f's.{name}' for name in quoted)})"
    )


def coverage_sql(backend: str, table: str) -> str:
    """Stored (source, day) pairs for the pipeline's watermark math."""
    _types(backend)
    return (
        f"SELECT DISTINCT {quote(backend, 'source')}, {quote(backend, 'day')} "
        f"FROM {table}"
    )


def identities_sql(backend: str, table: str) -> str:
    """Stored identities for relaying local rows to remotes."""
    _types(backend)
    columns = ", ".join(quote(backend, column) for column in IDENTITY_COLUMNS)
    return f"SELECT DISTINCT {columns} FROM {table}"


def _types(backend: str) -> dict[str, str]:
    try:
        return _COLUMN_TYPES[backend]
    except KeyError:
        raise ValueError(f"unknown backend: {backend!r}") from None
