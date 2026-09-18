import json
from datetime import date, timedelta

import pandas as pd
import pytest

from delukit.layers.bronze.store import LocalBronzeStore
from delukit.pipelines import PipelineError
from delukit.pipelines.bronze import run
from delukit.sources.data_source import SourceError

TODAY = date(2026, 9, 16)
START = date(2025, 10, 1)

SMARD_CONFIG = {
    "area": "DE_LU",
    "resolution": "15min",
    "methods": [{"method": "day_ahead_price"}],
}

SMARD_PAYLOAD = '{"series": [[1789250400000, 42.5]]}'

WEATHER_CONFIG = {
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

ENERGY_CHARTS_CONFIG = {
    "methods": [{"bidding_zone": "DE-LU", "method": "day_ahead_price"}],
}


class FakeSource:
    def __init__(self, scripted=None, raws=None, error=None):
        self.scripted = list(scripted or [])
        self.raws = raws or {}
        self.error = error
        self.calls = []

    def fetch(self, start, end, **params):
        self.calls.append((start, end, params))
        if self.error is not None:
            raise self.error
        if self.scripted:
            for expected, raws in self.scripted:
                if all(params.get(key) == value for key, value in expected.items()):
                    return {
                        day: docs for day, docs in raws.items() if start <= day <= end
                    }
            raise AssertionError(f"no scripted response for {params}")
        return {day: docs for day, docs in self.raws.items() if start <= day <= end}


class FakeStore:
    def __init__(self, error=None, coverage=None):
        self.written = []
        self.error = error
        self._coverage = set(coverage or set())
        self.coverage_calls = 0
        self.identities_calls = 0

    def write(self, records):
        if self.error is not None:
            raise self.error
        self.written.append(list(records))
        return len(records)

    def coverage(self):
        self.coverage_calls += 1
        return set(self._coverage)

    def identities(self):
        self.identities_calls += 1
        if self.error is not None:
            raise self.error
        return {
            (r["source"], r["day"], r["key"], r["payload_hash"])
            for batch in self.written
            for r in batch
        }


def write_config(tmp_path, **overrides):
    data = {
        "start": "2025-10-01",
        "end": "latest",
        "timezone": "Europe/Berlin",
        "storages": ["local"],
        "sources": {"smard": SMARD_CONFIG},
    }
    data.update(overrides)
    path = tmp_path / "bronze.json"
    path.write_text(json.dumps(data))
    return path


def patch(monkeypatch, sources, store_map):
    monkeypatch.setattr(
        "delukit.pipelines.bronze.build_source",
        lambda name, config, tz: sources[name],
    )
    monkeypatch.setattr(
        "delukit.pipelines.bronze.build_bronze_store", lambda name: store_map[name]
    )
    monkeypatch.setattr("delukit.pipelines._today", lambda tz: TODAY)


def seed(store, source, day, payload=SMARD_PAYLOAD, key="day_ahead_price"):
    from delukit.layers.bronze.records import make_records

    store.write(make_records(source, {day: {key: payload}}, TODAY - timedelta(days=1)))


def test_first_run_backfills_from_start(monkeypatch, tmp_path):
    path = write_config(tmp_path)
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"smard": smard}, {"local": local})

    run(str(path))

    assert smard.calls == [
        (
            START,
            TODAY,
            {"method": "day_ahead_price", "area": "DE_LU", "resolution": "15min"},
        )
    ]
    assert len(pd.read_parquet(local.file)) == 1


def test_second_run_fetches_refresh_window_only(monkeypatch, tmp_path):
    path = write_config(tmp_path)
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"smard": smard}, {"local": local})
    seed(local, "smard", TODAY - timedelta(days=1))

    run(str(path))

    assert smard.calls[0][0] == TODAY - timedelta(days=7)
    assert smard.calls[0][1] == TODAY


def test_refresh_days_config_override(monkeypatch, tmp_path):
    path = write_config(
        tmp_path, sources={"smard": {**SMARD_CONFIG, "refresh_days": 2}}
    )
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"smard": smard}, {"local": local})
    seed(local, "smard", TODAY - timedelta(days=1))

    run(str(path))

    assert smard.calls[0][0] == TODAY - timedelta(days=2)


def test_weather_default_refresh_days(monkeypatch, tmp_path):
    path = write_config(tmp_path, sources={"weather": WEATHER_CONFIG})
    weather = FakeSource(
        raws={
            TODAY: {
                "forecast": {
                    "run": "2026-09-16T00:00",
                    "locations": {"berlin": {"hourly": {"time": ["2026-09-16T02:00"]}}},
                }
            }
        }
    )
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"weather": weather}, {"local": local})
    seed(
        local,
        "weather",
        TODAY - timedelta(days=1),
        payload={"run": "2026-09-15T00:00", "locations": {"berlin": {"hourly": {}}}},
        key="forecast",
    )

    run(str(path))

    assert weather.calls[0][0] == TODAY - timedelta(days=3)


def test_revised_payload_appends_version_without_duplicates(monkeypatch, tmp_path):
    path = write_config(tmp_path)
    smard = FakeSource(raws={TODAY: {"day_ahead_price": '{"series": [[1, 42.5]]}'}})
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"smard": smard}, {"local": local})

    run(str(path))
    smard.raws = {TODAY: {"day_ahead_price": '{"series": [[1, 43.0]]}'}}
    run(str(path))
    run(str(path))

    frame = pd.read_parquet(local.file)
    assert len(frame) == 2
    assert set(frame["payload"]) == {
        '{"series": [[1, 42.5]]}',
        '{"series": [[1, 43.0]]}',
    }


def test_tail_holes_stay_inside_fetch_window(monkeypatch, tmp_path):
    path = write_config(tmp_path)
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"smard": smard}, {"local": local})
    seed(local, "smard", TODAY - timedelta(days=3))

    run(str(path))

    start, end, _ = smard.calls[0]
    assert start == TODAY - timedelta(days=9)
    assert end == TODAY


def test_failed_source_does_not_block_others(monkeypatch, tmp_path):
    path = write_config(
        tmp_path,
        sources={
            "smard": SMARD_CONFIG,
            "energy_charts": ENERGY_CHARTS_CONFIG,
        },
    )
    smard = FakeSource(error=SourceError("smard: HTTP 500"))
    charts = FakeSource(
        raws={TODAY: {"day_ahead_price": '{"unix_seconds": [1], "price": [40.0]}'}}
    )
    local = LocalBronzeStore(tmp_path / "store")
    patch(
        monkeypatch,
        {"smard": smard, "energy_charts": charts},
        {"local": local},
    )

    with pytest.raises(PipelineError, match="smard"):
        run(str(path))

    assert {row.source for row in pd.read_parquet(local.file).itertuples()} == {
        "energy_charts"
    }


def test_fetch_policy_not_passed_to_source(monkeypatch, tmp_path):
    methods = [
        {
            "bidding_zone": "DE-LU",
            "method": "day_ahead_price",
            "fetch_policy": {"mode": "fallback"},
        }
    ]
    path = write_config(tmp_path, sources={"energy_charts": {"methods": methods}})
    charts = FakeSource(
        raws={TODAY: {"day_ahead_price": '{"unix_seconds": [1], "price": [40.0]}'}}
    )
    local = LocalBronzeStore(tmp_path / "store")
    patch(monkeypatch, {"energy_charts": charts}, {"local": local})

    run(str(path))

    _, _, params = charts.calls[0]
    assert "fetch_policy" not in params
    assert params == {"method": "day_ahead_price", "bidding_zone": "DE-LU"}


def test_failed_store_does_not_block_other_stores(monkeypatch, tmp_path):
    path = write_config(tmp_path, storages=["local", "databricks"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    databricks = FakeStore(error=RuntimeError("connection refused"))
    patch(monkeypatch, {"smard": smard}, {"local": local, "databricks": databricks})

    with pytest.raises(PipelineError, match="databricks"):
        run(str(path))

    assert len(pd.read_parquet(local.file)) == 1


def test_records_land_in_every_configured_storage(monkeypatch, tmp_path):
    path = write_config(tmp_path, storages=["local", "databricks", "snowflake"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    databricks = FakeStore()
    snowflake = FakeStore()
    patch(
        monkeypatch,
        {"smard": smard},
        {"local": local, "databricks": databricks, "snowflake": snowflake},
    )

    run(str(path))

    assert len(pd.read_parquet(local.file)) == 1
    assert len(databricks.written) == 1 and len(databricks.written[0]) == 1
    assert len(snowflake.written) == 1 and len(snowflake.written[0]) == 1


def test_remote_only_uses_remote_coverage(monkeypatch, tmp_path):
    path = write_config(tmp_path, storages=["databricks"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    databricks = FakeStore(coverage={("smard", TODAY - timedelta(days=1))})
    patch(monkeypatch, {"smard": smard}, {"databricks": databricks})

    run(str(path))

    assert databricks.coverage_calls == 1
    assert smard.calls[0][0] == TODAY - timedelta(days=7)
    assert len(databricks.written) == 1


def test_prefers_local_anchor_when_present(monkeypatch, tmp_path):
    path = write_config(tmp_path, storages=["local", "databricks"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    seed(local, "smard", TODAY - timedelta(days=1))
    databricks = FakeStore(coverage={("smard", TODAY - timedelta(days=30))})
    patch(monkeypatch, {"smard": smard}, {"local": local, "databricks": databricks})

    run(str(path))

    assert databricks.coverage_calls == 0
    assert smard.calls[0][0] == TODAY - timedelta(days=7)


def test_failed_remote_heals_on_sync(monkeypatch, tmp_path):
    from delukit.pipelines.bronze import sync

    path = write_config(tmp_path, storages=["local", "databricks"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    databricks = FakeStore(error=RuntimeError("connection refused"))
    patch(monkeypatch, {"smard": smard}, {"local": local, "databricks": databricks})

    with pytest.raises(PipelineError, match="databricks"):
        run(str(path))
    assert len(pd.read_parquet(local.file)) == 1
    assert databricks.written == []

    databricks.error = None
    sync(str(path))

    assert len(databricks.written) == 1 and len(databricks.written[0]) == 1
    sync(str(path))  # idempotent: nothing new to relay
    assert len(databricks.written) == 1


def test_sync_heals_hole_outside_refresh_window(monkeypatch, tmp_path):
    from delukit.pipelines.bronze import sync

    path = write_config(tmp_path, storages=["local", "databricks"])
    old = TODAY - timedelta(days=30)
    local = LocalBronzeStore(tmp_path / "store")
    seed(local, "smard", old)
    databricks = FakeStore()
    patch(
        monkeypatch,
        {"smard": FakeSource(raws={})},
        {"local": local, "databricks": databricks},
    )

    sync(str(path))

    assert len(databricks.written) == 1
    assert databricks.written[0][0]["day"] == old


def test_revised_payload_syncs_new_version_only(monkeypatch, tmp_path):
    from delukit.pipelines.bronze import sync

    path = write_config(tmp_path, storages=["local", "databricks"])
    smard = FakeSource(raws={TODAY: {"day_ahead_price": SMARD_PAYLOAD}})
    local = LocalBronzeStore(tmp_path / "store")
    databricks = FakeStore()
    patch(monkeypatch, {"smard": smard}, {"local": local, "databricks": databricks})
    run(str(path))
    assert len(databricks.written) == 1

    seed(local, "smard", TODAY, payload='{"series": [[1, 99.0]]}')
    sync(str(path))

    assert len(databricks.written) == 2 and len(databricks.written[1]) == 1
    assert databricks.written[1][0]["payload"] == '{"series": [[1, 99.0]]}'
