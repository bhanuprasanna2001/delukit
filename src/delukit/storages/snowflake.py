"""Snowflake bronze store: DELUKIT_DB.BRONZE.PAYLOADS.

One MERGE per run keyed on (source, day, "KEY", payload_hash) inserts
only rows whose identity is new, so unchanged refetches write nothing
and revised payloads accumulate as fresh versions. KEY is reserved in
Snowflake, hence the quoting. Records are landed in batched multi-row
statements (executemany is N sequential requests, which a year-long
backfill would feel).

The DELUKIT_DB database must exist before the first write (create it
once out of band); schema and table are created here.

Connection: snowflake-connector-python with SNOWFLAKE_ACCOUNT,
SNOWFLAKE_USER and SNOWFLAKE_PASSWORD env vars (SNOWFLAKE_ROLE and
SNOWFLAKE_WAREHOUSE optional); tests pass an explicit connection.
"""

from __future__ import annotations

import os

import snowflake.connector

from delukit.storages.base import BronzeStore, land_records

_MERGE = """
MERGE INTO {table} AS target
USING (
  SELECT $1 AS SOURCE, $2 AS DAY, $3 AS "KEY", $4 AS PAYLOAD,
         $5 AS PAYLOAD_HASH, $6 AS FETCHED_AT
  FROM VALUES {values}
) AS s
ON target.SOURCE = s.SOURCE
   AND target.DAY = s.DAY
   AND target."KEY" = s."KEY"
   AND target.PAYLOAD_HASH = s.PAYLOAD_HASH
WHEN NOT MATCHED THEN INSERT
  (SOURCE, DAY, "KEY", PAYLOAD, PAYLOAD_HASH, FETCHED_AT)
  VALUES
  (s.SOURCE, s.DAY, s."KEY", s.PAYLOAD, s.PAYLOAD_HASH, s.FETCHED_AT)
"""

_DDL = (
    "CREATE SCHEMA IF NOT EXISTS DELUKIT_DB.BRONZE",
    (
        "CREATE TABLE IF NOT EXISTS DELUKIT_DB.BRONZE.PAYLOADS ("
        'SOURCE VARCHAR, DAY DATE, "KEY" VARCHAR, PAYLOAD VARCHAR, '
        "PAYLOAD_HASH VARCHAR(64), FETCHED_AT TIMESTAMP_NTZ)"
    ),
)


class SnowflakeStore(BronzeStore):
    def __init__(self, connection=None, table: str = "DELUKIT_DB.BRONZE.PAYLOADS"):
        self.table = table
        self.connection = connection or snowflake.connector.connect(**_connect_params())

    def write(self, records: list[dict]) -> int:
        return land_records(
            self.connection,
            _DDL,
            _MERGE,
            records,
            marker="%s",
            table=self.table,
        )


def _connect_params() -> dict:
    params = {
        "account": _env("SNOWFLAKE_ACCOUNT"),
        "user": _env("SNOWFLAKE_USER"),
        "password": _env("SNOWFLAKE_PASSWORD"),
    }
    for name, key in (
        ("SNOWFLAKE_ROLE", "role"),
        ("SNOWFLAKE_WAREHOUSE", "warehouse"),
    ):
        if os.environ.get(name):
            params[key] = os.environ[name]
    return params


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"snowflake: {name} environment variable is not set")
    return value
