"""Live Databricks bronze roundtrip: MERGE dedupe + coverage.

Skipped without DATABRICKS_SERVER_HOSTNAME/HTTP_PATH/TOKEN. Uses an
ephemeral table per run and drops it afterwards.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest
from conftest import has_databricks_creds

pytestmark = pytest.mark.skipif(
    not has_databricks_creds(), reason="DATABRICKS_* credentials not set"
)

DAY = date(2026, 9, 15)
FETCHED_AT = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design


def _records():
    from delukit.layers.bronze.records import make_records

    return make_records(
        "smard", {DAY: {"day_ahead_price": '{"series": [[1, 2.0]]}'}}, FETCHED_AT
    )


def test_databricks_roundtrip():
    from delukit.storages.databricks import DatabricksStore

    table = f"delukit.bronze.payloads_test_{uuid.uuid4().hex[:12]}"
    store = DatabricksStore(table=table)
    try:
        assert store.coverage() == set()
        assert store.write(_records()) == 1
        assert store.write(_records()) == 0
        assert store.coverage() == {("smard", DAY)}
    finally:
        with store.connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE IF EXISTS {table}")
