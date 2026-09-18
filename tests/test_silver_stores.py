import pandas as pd
import pytest

from delukit.backends.base import SqlBackend
from delukit.layers.silver.store import (
    LocalSilverStore,
    SqlSilverStore,
    build_silver_store,
)

TZ = "Europe/Berlin"


def sql_store(connection, backend):
    return SqlSilverStore(SqlBackend(connection, backend))


def price_frame(*prices, sequence=1):
    timestamps = pd.date_range("2026-09-15", periods=len(prices), freq="15min", tz=TZ)
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "price_eur_per_mwh": list(prices),
            "sequence": sequence,
        }
    )


class FakeCursor:
    def __init__(self, rowcount=None):
        self.calls = []
        self._rowcount = rowcount
        self.rowcount = 0

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if params is None:
            return
        self.rowcount = (
            self._rowcount if self._rowcount is not None else len(params) // 3
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeConnection:
    def __init__(self, rowcount=None):
        self.cursor_ = FakeCursor(rowcount=rowcount)

    def cursor(self):
        return self.cursor_


class TestLocalSilverStore:
    def test_upsert_writes_domain_subfolder(self, tmp_path):
        store = LocalSilverStore(tmp_path)

        assert store.upsert("energy_charts_day_ahead_price", price_frame(1.0)) == 1

        path = tmp_path / "silver" / "prices" / "energy_charts_day_ahead_price.parquet"
        assert path.is_file()
        assert len(pd.read_parquet(path)) == 1

    def test_revised_rows_overwrite_by_natural_key(self, tmp_path):
        store = LocalSilverStore(tmp_path)
        store.upsert("smard_day_ahead_price", price_frame(1.0, 2.0))

        assert store.upsert("smard_day_ahead_price", price_frame(9.0, 2.0)) == 2

        frame = pd.read_parquet(
            tmp_path / "silver" / "prices" / "smard_day_ahead_price.parquet"
        )
        assert len(frame) == 2
        assert sorted(frame["price_eur_per_mwh"]) == [2.0, 9.0]

    def test_rerun_is_a_noop(self, tmp_path):
        store = LocalSilverStore(tmp_path)
        frame = price_frame(1.0)
        store.upsert("smard_day_ahead_price", frame)

        assert store.upsert("smard_day_ahead_price", frame) == 1

        path = tmp_path / "silver" / "prices" / "smard_day_ahead_price.parquet"
        assert len(pd.read_parquet(path)) == 1

    def test_tables_do_not_share_files(self, tmp_path):
        store = LocalSilverStore(tmp_path)
        store.upsert("smard_day_ahead_price", price_frame(1.0))
        store.upsert("entsoe_day_ahead_price", price_frame(2.0, sequence=2))

        smard = pd.read_parquet(
            tmp_path / "silver" / "prices" / "smard_day_ahead_price.parquet"
        )
        entsoe = pd.read_parquet(
            tmp_path / "silver" / "prices" / "entsoe_day_ahead_price.parquet"
        )
        assert smard["price_eur_per_mwh"].tolist() == [1.0]
        assert entsoe["price_eur_per_mwh"].tolist() == [2.0]


class TestDatabricksSilverStore:
    def test_merge_upserts_on_natural_key(self):
        connection = FakeConnection()
        store = sql_store(connection, "databricks")

        assert store.upsert("smard_day_ahead_price", price_frame(1.0, 2.0)) == 2

        cursor = connection.cursor_
        statements = [sql for sql, _ in cursor.calls]
        assert "CREATE SCHEMA IF NOT EXISTS delukit.silver" in statements
        assert any(
            "CREATE TABLE IF NOT EXISTS delukit.silver.smard_day_ahead_price" in sql
            for sql in statements
        )
        merge = next(sql for sql, _ in cursor.calls if sql.startswith("MERGE"))
        assert "AS v(`timestamp`, `price_eur_per_mwh`, `sequence`)" in merge
        assert "`timestamp`" in merge  # reserved word is quoted
        assert "target.`timestamp` = s.`timestamp`" in merge
        assert "target.`sequence` = s.`sequence`" in merge
        assert "WHEN MATCHED THEN UPDATE SET" in merge
        assert "WHEN NOT MATCHED THEN INSERT" in merge
        _, params = next(call for call in cursor.calls if call[0].startswith("MERGE"))
        assert len(params) == 2 * 3
        assert params[1] == 1.0


class TestSnowflakeSilverStore:
    def test_merge_uses_positional_markers_and_upper_identifiers(self):
        connection = FakeConnection()
        store = sql_store(connection, "snowflake")

        assert store.upsert("entsoe_day_ahead_price", price_frame(1.0)) == 1

        cursor = connection.cursor_
        assert any(
            "DELUKIT_DB.SILVER.ENTSOE_DAY_AHEAD_PRICE" in sql for sql, _ in cursor.calls
        )
        merge = next(sql for sql, _ in cursor.calls if sql.startswith("MERGE"))
        assert "%s" in merge and "?" not in merge
        assert '$1 AS "TIMESTAMP"' in merge
        assert '"TIMESTAMP"' in merge
        ddl = " ".join(sql for sql, _ in cursor.calls if sql.startswith("CREATE"))
        assert "TIMESTAMP_TZ" in ddl  # Berlin/UTC instants stay exact


@pytest.mark.parametrize("backend", ["local", "databricks", "snowflake"])
def test_empty_skips_io(tmp_path, backend):
    if backend == "local":
        store = LocalSilverStore(tmp_path)
        assert store.upsert("smard_day_ahead_price", pd.DataFrame()) == 0
        assert not (tmp_path / "silver").exists()
    else:
        connection = FakeConnection()
        store = sql_store(connection, backend)
        assert store.upsert("smard_day_ahead_price", pd.DataFrame()) == 0
        assert connection.cursor_.calls == []


def test_builder_registry():
    assert isinstance(build_silver_store("local"), LocalSilverStore)
    with pytest.raises(ValueError, match="unknown backend"):
        build_silver_store("bogus")
    with pytest.raises(ValueError, match="unknown backend"):
        SqlSilverStore(SqlBackend(FakeConnection(), "supabase"))
