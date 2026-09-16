import json

import pandas as pd
import pytest

from delukit.layers.silver.parsers.energy_charts import parse_day

TZ = "Europe/Berlin"


def price_doc(points, start="2025-10-01 00:00:00+02:00", step_min=15):
    start_epoch = int(pd.Timestamp(start).timestamp())
    seconds = [start_epoch + i * step_min * 60 for i in range(len(points))]
    return json.dumps(
        {
            "license_info": "CC BY 4.0",
            "unix_seconds": seconds,
            "price": points,
            "unit": "EUR / MWh",
            "deprecated": False,
        }
    )


def test_15min_day():
    prices = [50.0 + i for i in range(96)]

    frame = parse_day({"day_ahead_price": price_doc(prices)}, "day_ahead_price", tz=TZ)

    assert list(frame.columns) == ["timestamp", "price_eur_per_mwh", "sequence"]
    assert len(frame) == 96
    assert frame["price_eur_per_mwh"].tolist() == prices
    assert (frame["sequence"] == 1).all()
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2025-10-01 00:00", tz=TZ)
    assert frame["timestamp"].diff().iloc[1] == pd.Timedelta("15min")
    assert frame["timestamp"].dt.tz.key == TZ


def test_hourly_day():
    prices = [50.0 + i for i in range(24)]

    frame = parse_day(
        {"day_ahead_price": price_doc(prices, step_min=60)}, "day_ahead_price", tz=TZ
    )

    assert len(frame) == 24
    assert frame["timestamp"].diff().iloc[1] == pd.Timedelta("60min")


def test_spring_forward_day_skips_hour_02():
    prices = list(range(92))

    frame = parse_day(
        {"day_ahead_price": price_doc(prices, start="2026-03-29 00:00:00+01:00")},
        "day_ahead_price",
        tz=TZ,
    )

    assert len(frame) == 92
    assert "02" not in frame["timestamp"].dt.strftime("%H").tolist()
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2026-03-29 00:00", tz=TZ)
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2026-03-29 23:45", tz=TZ)


def test_fall_back_day_spans_25_hours():
    prices = list(range(100))

    frame = parse_day(
        {"day_ahead_price": price_doc(prices, start="2026-10-25 00:00:00+02:00")},
        "day_ahead_price",
        tz=TZ,
    )

    assert len(frame) == 100
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2026-10-25 00:00", tz=TZ)
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2026-10-25 23:45+01:00")


def test_missing_doc_is_empty():
    assert parse_day({}, "day_ahead_price", tz=TZ).empty


def test_empty_arrays_give_empty_frame_with_columns():
    frame = parse_day({"day_ahead_price": price_doc([])}, "day_ahead_price", tz=TZ)

    assert frame.empty
    assert list(frame.columns) == ["timestamp", "price_eur_per_mwh", "sequence"]


def test_length_mismatch_raises():
    doc = price_doc([1.0, 2.0])
    data = json.loads(doc)
    data["price"] = [1.0]
    doc = json.dumps(data)

    with pytest.raises(ValueError, match="different lengths"):
        parse_day({"day_ahead_price": doc}, "day_ahead_price", tz=TZ)


def test_wrong_unit_raises():
    doc = price_doc([1.0])
    data = json.loads(doc)
    data["unit"] = "USD / MWh"
    doc = json.dumps(data)

    with pytest.raises(ValueError, match="unexpected unit"):
        parse_day({"day_ahead_price": doc}, "day_ahead_price", tz=TZ)


def test_malformed_json_raises_clean_error():
    with pytest.raises(ValueError, match="unparseable day_ahead_price"):
        parse_day({"day_ahead_price": "not json"}, "day_ahead_price", tz=TZ)


def test_unknown_method():
    with pytest.raises(ValueError, match="unknown energy_charts method"):
        parse_day({}, "bogus")
