from datetime import date, datetime

import pandas as pd
import pytest

from delukit.layers.bronze.records import RECORD_COLUMNS, make_records
from delukit.storages.databricks import DatabricksStore
from delukit.storages.local import LocalStore
from delukit.storages.snowflake import SnowflakeStore

FETCHED_AT = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design
DAY = date(2026, 9, 15)


def record(payload='{"series": [[1, 2.0]]}', day=DAY, key="day_ahead_price"):
    return make_records("smard", {day: {key: payload}}, FETCHED_AT)[0]


def values(rows):
    return [row[column] for row in rows for column in RECORD_COLUMNS]


class FakeCursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self):
        self.cursor_ = FakeCursor()

    def cursor(self):
        return self.cursor_


class TestLocalStore:
    def test_write_then_rewrite_dedupes(self, tmp_path):
        store = LocalStore(tmp_path)
        rows = [record(), record(day=date(2026, 9, 16))]

        assert store.write(rows) == 2
        assert store.write(rows) == 0
        assert len(pd.read_parquet(store.file)) == 2

    def test_revised_payload_appends_version(self, tmp_path):
        store = LocalStore(tmp_path)
        store.write([record(payload='{"series": [[1, 2.0]]}')])
        store.write([record(payload='{"series": [[1, 3.0]]}')])

        frame = pd.read_parquet(store.file)
        assert len(frame) == 2
        assert len(frame["payload_hash"].unique()) == 2

    def test_coverage(self, tmp_path):
        store = LocalStore(tmp_path)
        assert store.coverage() == set()
        store.write([record()])
        assert store.coverage() == {("smard", DAY)}

    def test_write_empty_creates_nothing(self, tmp_path):
        store = LocalStore(tmp_path)
        assert store.write([]) == 0
        assert not store.file.exists()


class TestDatabricksStore:
    def test_write_merges_records(self):
        connection = FakeConnection()
        store = DatabricksStore(connection=connection)
        rows = [record(), record(day=date(2026, 9, 16))]

        assert store.write(rows) == 2

        cursor = connection.cursor_
        statements = [sql for sql, _ in cursor.calls]
        assert "CREATE CATALOG" not in "\n".join(statements)
        assert "CREATE SCHEMA IF NOT EXISTS delukit.bronze" in statements
        assert any(
            "CREATE TABLE IF NOT EXISTS delukit.bronze.payloads" in sql
            for sql in statements
        )
        merge_sql = next(sql for sql, _ in cursor.calls if sql.startswith("\nMERGE"))
        assert "USING (" in merge_sql
        assert "FROM VALUES" in merge_sql
        assert "WHEN NOT MATCHED THEN INSERT" in merge_sql
        _, params = next(call for call in cursor.calls if call[0].startswith("\nMERGE"))
        assert params == values(rows)

    def test_records_land_in_batches(self):
        connection = FakeConnection()
        store = DatabricksStore(connection=connection)
        rows = make_records(
            "smard",
            {DAY: {f"key_{i}": '{"series": [[1, 2.0]]}' for i in range(25)}},
            FETCHED_AT,
        )

        assert store.write(rows) == 25

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("\nMERGE")
        ]
        assert [len(params) // 6 for _, params in merges] == [20, 5]

    def test_write_empty_skips_sql(self):
        store = DatabricksStore(connection=FakeConnection())
        assert store.write([]) == 0
        assert store.connection.cursor_.calls == []

    def test_missing_env_raises(self, monkeypatch):
        for name in (
            "DATABRICKS_SERVER_HOSTNAME",
            "DATABRICKS_HTTP_PATH",
            "DATABRICKS_TOKEN",
        ):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ValueError, match="DATABRICKS_"):
            DatabricksStore()


class TestSnowflakeStore:
    def test_write_merges_records(self):
        connection = FakeConnection()
        store = SnowflakeStore(connection=connection)
        rows = [record()]

        assert store.write(rows) == 1

        cursor = connection.cursor_
        statements = [sql for sql, _ in cursor.calls]
        assert "CREATE DATABASE" not in "\n".join(statements)
        assert "CREATE SCHEMA IF NOT EXISTS DELUKIT_DB.BRONZE" in statements
        assert any(
            "CREATE TABLE IF NOT EXISTS DELUKIT_DB.BRONZE.PAYLOADS" in sql
            for sql in statements
        )
        merge_sql = next(sql for sql, _ in cursor.calls if sql.startswith("\nMERGE"))
        assert "FROM VALUES" in merge_sql
        assert "$1 AS SOURCE" in merge_sql
        assert '"KEY"' in merge_sql
        assert "WHEN NOT MATCHED THEN INSERT" in merge_sql
        _, params = next(call for call in cursor.calls if call[0].startswith("\nMERGE"))
        assert params == values(rows)

    def test_records_land_in_batches(self):
        connection = FakeConnection()
        store = SnowflakeStore(connection=connection)
        rows = make_records(
            "smard",
            {DAY: {f"key_{i}": '{"series": [[1, 2.0]]}' for i in range(25)}},
            FETCHED_AT,
        )

        assert store.write(rows) == 25

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("\nMERGE")
        ]
        assert [len(params) // 6 for _, params in merges] == [20, 5]

    def test_write_empty_skips_sql(self):
        store = SnowflakeStore(connection=FakeConnection())
        assert store.write([]) == 0
        assert store.connection.cursor_.calls == []

    def test_missing_env_raises(self, monkeypatch):
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"):
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ValueError, match="SNOWFLAKE_"):
            SnowflakeStore()
