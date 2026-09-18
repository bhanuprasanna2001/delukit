import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from delukit.layers.bronze.records import make_records
from delukit.layers.bronze.store import LocalBronzeStore
from delukit.layers.silver.store import LocalSilverStore
from delukit.pipelines.data import run
from delukit.pipelines.raw import PipelineError

TODAY = date(2026, 9, 16)
DAY = date(2026, 9, 15)
T0 = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design
T1 = datetime(2026, 9, 17, 6, 0)  # noqa: DTZ001 — naive UTC by design

SMARD_CONFIG = {
    "area": "DE_LU",
    "resolution": "15min",
    "methods": [{"method": "day_ahead_price"}],
}

WEATHER_CONFIG = {
    "model": "ecmwf_ifs",
    "forecast_days": 16,
    "fields": ["temperature_2m"],
    "locations": [
        {
            "name": "berlin",
            "latitude": 52.52,
            "longitude": 13.41,
            "cell_selection": "land",
        }
    ],
}


def smard_doc(values):
    base = pd.Timestamp("2026-09-15 00:00", tz="Europe/Berlin").value // 1_000_000
    return json.dumps(
        {"series": [[base + i * 900_000, v] for i, v in enumerate(values)]}
    )


def weather_doc(temps):
    return {
        "run": "2026-09-15T00:00",
        "model": "ecmwf_ifs",
        "locations": {
            "berlin": {
                "hourly": {
                    "time": ["2026-09-15T02:00", "2026-09-15T03:00"][: len(temps)],
                    "temperature_2m": list(temps),
                }
            }
        },
    }


class FakeSilverStore:
    def __init__(self, error=None):
        self.upserts = []
        self.error = error

    def upsert(self, table, frame):
        if self.error is not None:
            raise self.error
        self.upserts.append((table, frame.copy()))
        return len(frame)


def write_config(tmp_path, sources, **overrides):
    data = {
        "start": "2025-10-01",
        "end": "latest",
        "timezone": "Europe/Berlin",
        "storages": ["local"],
        "sources": sources,
    }
    data.update(overrides)
    path = tmp_path / "data.json"
    path.write_text(json.dumps(data))
    return str(path)


def patch(monkeypatch, bronze, silvers):
    monkeypatch.setattr(
        "delukit.pipelines.data.build_bronze_store", lambda name: bronze
    )
    monkeypatch.setattr(
        "delukit.pipelines.data.build_silver_store", lambda name: silvers[name]
    )
    monkeypatch.setattr("delukit.pipelines.raw._today", lambda tz: TODAY)


def seed(bronze, source, raws, fetched_at=T0):
    bronze.write(make_records(source, raws, fetched_at))


def test_each_source_lands_in_its_own_table(monkeypatch, tmp_path):
    path = write_config(tmp_path, {"smard": SMARD_CONFIG, "weather": WEATHER_CONFIG})
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([1.0, 2.0])}})
    seed(bronze, "weather", {DAY: {"forecast": weather_doc([21.5, 22.0])}})
    silver = FakeSilverStore()
    patch(monkeypatch, bronze, {"local": silver})

    run(path)

    by_table = {table: frame for table, frame in silver.upserts}
    assert set(by_table) == {"smard_day_ahead_price", "weather_forecast"}
    assert by_table["smard_day_ahead_price"]["price_eur_per_mwh"].tolist() == [1.0, 2.0]
    assert by_table["weather_forecast"]["temperature_2m"].tolist() == [21.5, 22.0]
    assert "location" not in by_table["smard_day_ahead_price"].columns


def test_rerun_overwrites_without_duplicates(monkeypatch, tmp_path):
    path = write_config(tmp_path, {"smard": SMARD_CONFIG})
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([1.0])}})
    silver = LocalSilverStore(tmp_path / "silver")
    patch(monkeypatch, bronze, {"local": silver})

    run(path)
    run(path)

    frame = pd.read_parquet(
        tmp_path / "silver" / "silver" / "prices" / "smard_day_ahead_price.parquet"
    )
    assert len(frame) == 1
    assert frame["price_eur_per_mwh"].tolist() == [1.0]


def test_revised_bronze_replaces_silver_rows(monkeypatch, tmp_path):
    path = write_config(tmp_path, {"smard": SMARD_CONFIG})
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([1.0])}}, T0)
    silver = LocalSilverStore(tmp_path / "silver")
    patch(monkeypatch, bronze, {"local": silver})
    run(path)

    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([9.0])}}, T1)
    run(path)

    frame = pd.read_parquet(
        tmp_path / "silver" / "silver" / "prices" / "smard_day_ahead_price.parquet"
    )
    assert len(frame) == 1
    assert frame["price_eur_per_mwh"].tolist() == [9.0]


def test_corrupt_day_fails_but_blocks_nothing_else(monkeypatch, tmp_path):
    path = write_config(tmp_path, {"smard": SMARD_CONFIG, "weather": WEATHER_CONFIG})
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(
        bronze,
        "smard",
        {
            DAY - timedelta(days=1): {"day_ahead_price": smard_doc([1.0])},
            DAY: {"day_ahead_price": '{"series": [[1, 2, 3]]}'},
        },
    )
    seed(bronze, "weather", {DAY: {"forecast": weather_doc([21.5])}})
    silver = FakeSilverStore()
    patch(monkeypatch, bronze, {"local": silver})

    with pytest.raises(PipelineError, match="smard_day_ahead_price"):
        run(path)

    by_table = {table: frame for table, frame in silver.upserts}
    assert by_table["smard_day_ahead_price"]["price_eur_per_mwh"].tolist() == [1.0]
    assert by_table["weather_forecast"]["temperature_2m"].tolist() == [21.5]


def test_failed_store_does_not_block_other_stores(monkeypatch, tmp_path):
    path = write_config(
        tmp_path, {"smard": SMARD_CONFIG}, storages=["local", "databricks"]
    )
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([1.0])}})
    good, bad = FakeSilverStore(), FakeSilverStore(error=RuntimeError("down"))
    patch(monkeypatch, bronze, {"local": good, "databricks": bad})

    with pytest.raises(PipelineError, match="databricks"):
        run(path)

    assert [table for table, _ in good.upserts] == ["smard_day_ahead_price"]


def test_nothing_new_skips_upserts(monkeypatch, tmp_path):
    path = write_config(tmp_path, {"smard": SMARD_CONFIG}, end="2025-10-02")
    bronze = LocalBronzeStore(tmp_path / "bronze")
    seed(bronze, "smard", {DAY: {"day_ahead_price": smard_doc([1.0])}})
    silver = FakeSilverStore()
    patch(monkeypatch, bronze, {"local": silver})

    run(path)

    assert silver.upserts == []


def test_empty_bronze_warns_instead_of_silent_noop(monkeypatch, tmp_path, caplog):
    import logging

    path = write_config(tmp_path, {"smard": SMARD_CONFIG})
    bronze = LocalBronzeStore(tmp_path / "bronze")
    silver = FakeSilverStore()
    patch(monkeypatch, bronze, {"local": silver})

    with caplog.at_level(logging.WARNING, logger="delukit.data"):
        run(path)

    assert silver.upserts == []
    assert "run `delukit raw` before `delukit data`" in caplog.text
