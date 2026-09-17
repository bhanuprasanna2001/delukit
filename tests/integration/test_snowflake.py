"""Live Snowflake bronze roundtrip: MERGE dedupe + coverage.

Skipped without SNOWFLAKE_ACCOUNT/USER/PASSWORD. Uses an ephemeral table
per run and drops it afterwards, so parallel runs never collide.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from conftest import has_snowflake_creds

pytestmark = pytest.mark.skipif(
    not has_snowflake_creds(), reason="SNOWFLAKE_* credentials not set"
)

DAY = date(2026, 9, 15)
FETCHED_AT = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design


def _records():
    from delukit.layers.bronze.records import make_records

    return make_records(
        "smard", {DAY: {"day_ahead_price": '{"series": [[1, 2.0]]}'}}, FETCHED_AT
    )


def test_snowflake_roundtrip():
    from delukit.storages.snowflake import SnowflakeStore

    table = f"DELUKIT_DB.BRONZE.PAYLOADS_TEST_{uuid.uuid4().hex[:12].upper()}"
    store = SnowflakeStore(table=table)
    try:
        assert store.coverage() == set()
        assert store.write(_records()) == 1
        assert store.write(_records()) == 0
        assert store.coverage() == {("smard", DAY)}
    finally:
        with store.connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
