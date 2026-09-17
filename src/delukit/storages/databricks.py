"""Databricks bronze store: delukit.bronze.payloads (Delta table).

One MERGE per run keyed on (source, day, key, payload_hash) inserts only
rows whose identity is new, so unchanged refetches write nothing and
revised payloads accumulate as fresh versions. Records are landed in
batched multi-row statements (the connector's executemany is N sequential
requests, which a year-long backfill would feel).

The `delukit` catalog must exist before the first write (create it once
out of band); schema and table are created here.

Connection: databricks-sql-connector with DATABRICKS_SERVER_HOSTNAME,
DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN env vars; tests pass an
explicit connection.
"""

from __future__ import annotations

import os
from datetime import date

from databricks import sql as databricks_sql

from delukit.storages.base import (
    BronzeStore,
    is_missing_table,
    land_records,
    normalize_day,
)

_MERGE = """
MERGE INTO {table} AS target
USING (
  SELECT * FROM VALUES {values}
  AS v(source, day, key, payload, payload_hash, fetched_at)
) AS s
ON target.source = s.source
   AND target.day = s.day
   AND target.key = s.key
   AND target.payload_hash = s.payload_hash
WHEN NOT MATCHED THEN INSERT
  (source, day, key, payload, payload_hash, fetched_at)
  VALUES
  (s.source, s.day, s.key, s.payload, s.payload_hash, s.fetched_at)
"""

_DDL = (
    "CREATE SCHEMA IF NOT EXISTS delukit.bronze",
    (
        "CREATE TABLE IF NOT EXISTS delukit.bronze.payloads ("
        "source STRING, day DATE, key STRING, payload STRING, "
        "payload_hash STRING, fetched_at TIMESTAMP)"
    ),
)


class DatabricksStore(BronzeStore):
    def __init__(self, connection=None, table: str = "delukit.bronze.payloads"):
        self.table = table
        self.connection = connection or databricks_sql.connect(
            server_hostname=_env("DATABRICKS_SERVER_HOSTNAME"),
            http_path=_env("DATABRICKS_HTTP_PATH"),
            access_token=_env("DATABRICKS_TOKEN"),
        )

    def write(self, records: list[dict]) -> int:
        return land_records(
            self.connection,
            _DDL,
            _MERGE,
            records,
            marker="?",
            table=self.table,
            label="databricks",
            colour="blue",
        )

    def coverage(self) -> set[tuple[str, date]]:
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"SELECT DISTINCT source, day FROM {self.table}")
                rows = cursor.fetchall()
        except Exception as error:
            if is_missing_table(error):
                return set()
            raise
        return {(source, normalize_day(day)) for source, day in rows}


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"databricks: {name} environment variable is not set")
    return value
