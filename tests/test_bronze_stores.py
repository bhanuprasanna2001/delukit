from datetime import date, datetime

import pandas as pd
import pytest

from delukit.backends.base import SqlBackend
from delukit.layers.bronze.records import make_records
from delukit.layers.bronze.store import (
    LocalBronzeStore,
    SqlBronzeStore,
    build_bronze_store,
)
from delukit.layers.bronze.tables import RECORD_COLUMNS

FETCHED_AT = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design
DAY = date(2026, 9, 15)


def record(payload='{"series": [[1, 2.0]]}', day=DAY, key="day_ahead_price"):
    return make_records("smard", {day: {key: payload}}, FETCHED_AT)[0]


def values(rows):
    return [row[column] for row in rows for column in RECORD_COLUMNS]


class FakeCursor:
    def __init__(self, rows=None, rowcount=None, error=None):
        self.calls = []
        self._rows = rows or []
        self._rowcount = rowcount
        self._error = error
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql.lstrip().upper().startswith("SELECT") and self._error is not None:
            raise self._error
        if params is None:
            return
        if isinstance(self._rowcount, list):
            self.rowcount = self._rowcount.pop(0) if self._rowcount else 0
        elif self._rowcount is not None:
            self.rowcount = self._rowcount
        else:
            self.rowcount = len(params) // 6

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, rows=None, rowcount=None, error=None):
        self.cursor_ = FakeCursor(rows=rows, rowcount=rowcount, error=error)

    def cursor(self):
        return self.cursor_


def databricks_store(connection, **kwargs):
    return SqlBronzeStore(SqlBackend(connection, "databricks"), **kwargs)


def snowflake_store(connection, **kwargs):
    return SqlBronzeStore(SqlBackend(connection, "snowflake"), **kwargs)


class TestLocalBronzeStore:
    def test_write_then_rewrite_dedupes(self, tmp_path):
        store = LocalBronzeStore(tmp_path)
        rows = [record(), record(day=date(2026, 9, 16))]

        assert store.write(rows) == 2
        assert store.write(rows) == 0
        assert len(pd.read_parquet(store.file)) == 2

    def test_revised_payload_appends_version(self, tmp_path):
        store = LocalBronzeStore(tmp_path)
        store.write([record(payload='{"series": [[1, 2.0]]}')])
        store.write([record(payload='{"series": [[1, 3.0]]}')])

        frame = pd.read_parquet(store.file)
        assert len(frame) == 2
        assert len(frame["payload_hash"].unique()) == 2

    def test_coverage(self, tmp_path):
        store = LocalBronzeStore(tmp_path)
        assert store.coverage() == set()
        store.write([record()])
        assert store.coverage() == {("smard", DAY)}

    def test_write_empty_creates_nothing(self, tmp_path):
        store = LocalBronzeStore(tmp_path)
        assert store.write([]) == 0
        assert not store.file.exists()


@pytest.fixture(params=["databricks", "snowflake"])
def sql_store_factory(request):
    return {"databricks": databricks_store, "snowflake": snowflake_store}[request.param]


class TestSqlBronzeStore:
    @pytest.mark.parametrize(
        "factory, schema",
        [
            (databricks_store, "delukit.bronze"),
            (snowflake_store, "DELUKIT_DB.BRONZE"),
        ],
    )
    def test_write_merges_records(self, factory, schema):
        connection = FakeConnection()
        store = factory(connection=connection)
        rows = [record(), record(day=date(2026, 9, 16))]

        assert store.write(rows) == 2

        cursor = connection.cursor_
        statements = [sql for sql, _ in cursor.calls]
        assert any(f"CREATE SCHEMA IF NOT EXISTS {schema}" in sql for sql in statements)
        merge_sql = next(sql for sql, _ in cursor.calls if sql.startswith("MERGE"))
        assert "FROM VALUES" in merge_sql
        assert "WHEN NOT MATCHED THEN INSERT" in merge_sql
        _, params = next(call for call in cursor.calls if call[0].startswith("MERGE"))
        assert params == values(rows)

    def test_records_land_in_batches(self, sql_store_factory):
        connection = FakeConnection()
        store = sql_store_factory(connection=connection)
        rows = make_records(
            "smard",
            {DAY: {f"key_{i}": '{"series": [[1, 2.0]]}' for i in range(25)}},
            FETCHED_AT,
        )

        assert store.write(rows) == 25

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("MERGE")
        ]
        assert [len(params) // 6 for _, params in merges] == [20, 5]

    def test_write_empty_skips_sql(self, sql_store_factory):
        store = sql_store_factory(connection=FakeConnection())
        assert store.write([]) == 0
        assert store.backend.connection.cursor_.calls == []

    def test_huge_payloads_land_one_row_per_batch(self):
        # batching lives in shared SqlBronzeStore code: one backend pins it.
        connection = FakeConnection()
        store = databricks_store(connection=connection)
        big = '{"series": [[1, "' + "x" * 460_000 + '"]]}'
        rows = [record(payload=big, key=f"forecast_{i}") for i in range(3)]

        assert store.write(rows) == 3

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("MERGE")
        ]
        assert [len(params) // 6 for _, params in merges] == [1, 1, 1]
        for _, params in merges:
            size = sum(len(v) if isinstance(v, str) else 16 for v in params)
            assert size < 1_048_576

    def test_batches_split_on_bytes_before_row_count(self):
        connection = FakeConnection()
        store = databricks_store(connection=connection)
        rows = [record(key=f"key_{i}") for i in range(20)]
        rows.append(
            record(payload='{"series": [[1, "' + "x" * 460_000 + '"]]}', key="forecast")
        )

        assert store.write(rows) == 21

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("MERGE")
        ]
        assert [len(params) // 6 for _, params in merges] == [20, 1]

    def test_single_row_over_cap_still_lands(self):
        connection = FakeConnection()
        store = databricks_store(connection=connection)
        rows = [record(payload='{"series": [[1, "' + "x" * 900_000 + '"]]}')]

        assert store.write(rows) == 1

        merges = [
            call for call in connection.cursor_.calls if call[0].startswith("MERGE")
        ]
        assert len(merges) == 1
        assert merges[0][1] == values(rows)

    @pytest.mark.parametrize(
        "backend, env_names, match",
        [
            (
                "databricks",
                (
                    "DATABRICKS_SERVER_HOSTNAME",
                    "DATABRICKS_HTTP_PATH",
                    "DATABRICKS_TOKEN",
                ),
                "DATABRICKS_",
            ),
            (
                "snowflake",
                ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"),
                "SNOWFLAKE_",
            ),
        ],
    )
    def test_missing_env_raises(self, monkeypatch, backend, env_names, match):
        for name in env_names:
            monkeypatch.delenv(name, raising=False)
        with pytest.raises(ValueError, match=match):
            build_bronze_store(backend)

    def test_write_returns_actual_inserted_not_attempted(self, sql_store_factory):
        connection = FakeConnection(rowcount=0)
        store = sql_store_factory(connection=connection)

        assert store.write([record(), record(day=date(2026, 9, 16))]) == 0

    def test_write_sums_rowcounts_across_batches(self, sql_store_factory):
        connection = FakeConnection(rowcount=[20, 0])
        store = sql_store_factory(connection=connection)
        rows = make_records(
            "smard",
            {DAY: {f"key_{i}": '{"series": [[1, 2.0]]}' for i in range(25)}},
            FETCHED_AT,
        )

        assert store.write(rows) == 20

    def test_coverage(self, sql_store_factory):
        connection = FakeConnection(rows=[("smard", DAY), ("smard", "2026-09-16")])
        store = sql_store_factory(connection=connection)

        assert store.coverage() == {("smard", DAY), ("smard", date(2026, 9, 16))}
        assert "SELECT DISTINCT" in connection.cursor_.calls[0][0]

    @pytest.mark.parametrize(
        "error",
        [
            Exception("TABLE_OR_VIEW_NOT_FOUND: delukit.bronze.payloads"),
            Exception(
                "002003 (02000): Object 'DELUKIT_DB.BRONZE.PAYLOADS' "
                "does not exist or not authorized."
            ),
        ],
    )
    def test_coverage_missing_table_returns_empty(self, sql_store_factory, error):
        store = sql_store_factory(connection=FakeConnection(error=error))

        assert store.coverage() == set()

    def test_coverage_propagates_unexpected_errors(self, sql_store_factory):
        error = RuntimeError("connection refused")
        store = sql_store_factory(connection=FakeConnection(error=error))

        with pytest.raises(RuntimeError, match="connection refused"):
            store.coverage()


class TestIdentities:
    def test_local_identities_and_records_for(self, tmp_path):
        store = LocalBronzeStore(tmp_path)
        assert store.identities() == set()
        assert store.records_for({("smard", DAY, "k", "h")}) == []
        rows = [record(), record(day=date(2026, 9, 16))]
        store.write(rows)

        idents = store.identities()
        assert len(idents) == 2
        assert all(len(ident) == 4 for ident in idents)

        replay = store.records_for(idents)
        assert len(replay) == 2
        assert replay[0]["day"] == DAY
        assert isinstance(replay[0]["fetched_at"], datetime)
        assert store.records_for(set()) == []

    @pytest.mark.parametrize("factory", [databricks_store, snowflake_store])
    def test_identities(self, factory):
        rows = [
            ("smard", DAY, "day_ahead_price", "abc"),
            ("smard", "2026-09-16", "day_ahead_price", "def"),
        ]
        store = factory(connection=FakeConnection(rows=rows))

        assert store.identities() == {
            ("smard", DAY, "day_ahead_price", "abc"),
            ("smard", date(2026, 9, 16), "day_ahead_price", "def"),
        }

    def test_identities_missing_table_returns_empty(self):
        error = Exception("TABLE_OR_VIEW_NOT_FOUND: delukit.bronze.payloads")
        assert (
            databricks_store(connection=FakeConnection(error=error)).identities()
            == set()
        )
        assert (
            snowflake_store(connection=FakeConnection(error=error)).identities()
            == set()
        )


class TestBuilders:
    def test_build_bronze_store_registry(self, tmp_path):
        store = build_bronze_store("local", root=tmp_path)

        assert isinstance(store, LocalBronzeStore)
        assert store.root == tmp_path
        with pytest.raises(ValueError, match="unknown backend"):
            build_bronze_store("supabase")
