import json
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from delukit.layers.bronze.records import make_records
from delukit.layers.bronze.store import LocalBronzeStore
from delukit.layers.silver.loader import load_latest

DAY = date(2026, 9, 15)
DAY2 = date(2026, 9, 16)
T0 = datetime(2026, 9, 16, 6, 0)  # noqa: DTZ001 — naive UTC by design
T1 = datetime(2026, 9, 17, 6, 0)  # noqa: DTZ001 — naive UTC by design


def smard_payload(value=42.5):
    ms = pd.Timestamp("2026-09-15 00:00", tz="Europe/Berlin").value // 1_000_000
    return json.dumps({"series": [[ms, value]]})


def entsoe_doc(n=1):
    return (
        "<GL_MarketDocument><TimeSeries><mRID>"
        f"{n}</mRID></TimeSeries></GL_MarketDocument>"
    )


def weather_payload(temp=21.5):
    return {
        "run": "2026-09-15T00:00",
        "model": "ecmwf_ifs",
        "locations": {
            "berlin": {
                "hourly": {"time": ["2026-09-15T02:00"], "temperature_2m": [temp]}
            }
        },
    }


def seed(store, source, raws, fetched_at=T0):
    store.write(make_records(source, raws, fetched_at))


def test_latest_version_wins(tmp_path):
    store = LocalBronzeStore(tmp_path)
    seed(store, "smard", {DAY: {"day_ahead_price": smard_payload(1.0)}}, T0)
    seed(store, "smard", {DAY: {"day_ahead_price": smard_payload(2.0)}}, T1)

    raws = load_latest(tmp_path, "smard", DAY, DAY)

    assert json.loads(raws[DAY]["day_ahead_price"])["series"][0][1] == 2.0


def test_tie_break_is_deterministic(tmp_path):
    store = LocalBronzeStore(tmp_path)
    seed(store, "smard", {DAY: {"day_ahead_price": smard_payload(1.0)}}, T0)
    seed(store, "smard", {DAY: {"day_ahead_price": smard_payload(2.0)}}, T0)

    first = load_latest(tmp_path, "smard", DAY, DAY)
    second = load_latest(tmp_path, "smard", DAY, DAY)

    assert first == second
    assert set(first[DAY]) == {"day_ahead_price"}


def test_groups_keys_per_day_and_filters_window(tmp_path):
    store = LocalBronzeStore(tmp_path)
    seed(
        store,
        "entsoe",
        {
            DAY: {"load_actual": entsoe_doc(1), "load_forecast": entsoe_doc(2)},
            DAY2: {"load_actual": entsoe_doc(3)},
        },
    )

    raws = load_latest(tmp_path, "entsoe", DAY, DAY)

    assert set(raws) == {DAY}
    assert raws[DAY] == {"load_actual": entsoe_doc(1), "load_forecast": entsoe_doc(2)}


@pytest.mark.parametrize(
    ("source", "key"), [("weather", "forecast"), ("smard", "day_ahead_price")]
)
def test_payload_type_dispatch(tmp_path, source, key):
    store = LocalBronzeStore(tmp_path)
    seed(
        store,
        source,
        {DAY: {key: weather_payload() if source == "weather" else smard_payload()}},
    )

    raws = load_latest(tmp_path, source, DAY, DAY)

    value = raws[DAY][key]
    if source == "weather":
        assert value["locations"]["berlin"]["hourly"]["temperature_2m"] == [21.5]
    else:
        assert isinstance(value, str)


def test_empty_bronze_is_empty(tmp_path):
    assert load_latest(tmp_path, "smard", DAY, DAY) == {}
    store = LocalBronzeStore(tmp_path)
    seed(store, "entsoe", {DAY: {"load_actual": entsoe_doc()}})

    assert load_latest(tmp_path, "smard", DAY, DAY) == {}
    assert load_latest(tmp_path, "entsoe", DAY2, DAY2 + timedelta(days=30)) == {}
