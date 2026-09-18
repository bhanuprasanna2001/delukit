import json

import pandas as pd
import pytest

from delukit.layers.silver.parsers.smard import parse_day

TZ = "Europe/Berlin"


def doc(points):
    return json.dumps({"meta_data": {"version": 1}, "series": points})


def day_points(start, n, step_min=15):
    start_ts = pd.Timestamp(start)
    return [
        [(start_ts + pd.Timedelta(minutes=step_min * i)).value // 1_000_000, float(i)]
        for i in range(n)
    ]


def test_price_15min_day():
    points = day_points("2025-10-01 00:00:00+02:00", 96)

    frame = parse_day({"day_ahead_price": doc(points)}, "day_ahead_price", tz=TZ)

    assert list(frame.columns) == ["timestamp", "price_eur_per_mwh", "sequence"]
    assert len(frame) == 96
    assert frame["price_eur_per_mwh"].tolist() == [float(i) for i in range(96)]
    assert (frame["sequence"] == 1).all()
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2025-10-01 00:00", tz=TZ)
    assert frame["timestamp"].diff().iloc[1] == pd.Timedelta("15min")
    assert frame["timestamp"].dt.tz.key == TZ


@pytest.mark.parametrize(
    ("method", "n", "step_min", "delta"),
    [("load_actual", 96, 15, "15min"), ("load_forecast", 24, 60, "60min")],
)
def test_load(method, n, step_min, delta):
    points = day_points("2025-10-01 00:00:00+02:00", n, step_min=step_min)

    frame = parse_day({method: doc(points)}, method, tz=TZ)

    assert list(frame.columns) == ["timestamp", "load_mw"]
    assert len(frame) == n
    assert frame["load_mw"].iloc[0] == 0.0
    assert frame["timestamp"].diff().iloc[1] == pd.Timedelta(delta)


def test_generation_multiple_types():
    raws = {
        "generation_actual/solar": doc(day_points("2025-10-01 00:00:00+02:00", 2)),
        "generation_actual/wind_onshore": doc(
            day_points("2025-10-01 00:00:00+02:00", 2, step_min=15)
        ),
    }

    frame = parse_day(
        raws, "generation_actual", generation_types=["solar", "wind_onshore"], tz=TZ
    )

    assert list(frame.columns) == ["timestamp", "generation_mw", "generation_type"]
    assert frame["generation_type"].tolist() == [
        "solar",
        "solar",
        "wind_onshore",
        "wind_onshore",
    ]
    assert frame["generation_mw"].tolist() == [0.0, 1.0, 0.0, 1.0]

    frame = parse_day(
        {
            "generation_forecast_day_ahead/solar": doc(
                day_points("2025-10-01 00:00:00+02:00", 2)
            )
        },
        "generation_forecast_day_ahead",
        generation_types=["solar"],
        tz=TZ,
    )

    assert list(frame.columns) == ["timestamp", "generation_mw", "generation_type"]
    assert frame["generation_type"].tolist() == ["solar", "solar"]


def test_null_values_dropped():
    points = day_points("2025-10-01 00:00:00+02:00", 4)
    points[1][1] = None
    points[3][1] = None

    frame = parse_day({"load_actual": doc(points)}, "load_actual", tz=TZ)

    assert frame["load_mw"].tolist() == [0.0, 2.0]
    assert len(frame) == 2


@pytest.mark.parametrize(
    ("raws", "method", "kwargs", "columns"),
    [
        ({}, "day_ahead_price", {}, ["timestamp", "price_eur_per_mwh", "sequence"]),
        ({"load_actual": doc([])}, "load_actual", {}, ["timestamp", "load_mw"]),
        (
            {},
            "generation_actual",
            {"generation_types": ["solar"]},
            ["timestamp", "generation_mw", "generation_type"],
        ),
    ],
)
def test_empty_gives_typed_empty(raws, method, kwargs, columns):
    frame = parse_day(raws, method, **kwargs, tz=TZ)

    assert frame.empty
    assert list(frame.columns) == columns


def test_spring_forward_day_skips_hour_02():
    points = day_points("2026-03-29 00:00:00+01:00", 92)

    frame = parse_day({"day_ahead_price": doc(points)}, "day_ahead_price", tz=TZ)

    assert len(frame) == 92
    assert "02" not in frame["timestamp"].dt.strftime("%H").tolist()
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2026-03-29 00:00", tz=TZ)
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2026-03-29 23:45", tz=TZ)


def test_fall_back_day_spans_25_hours():
    points = day_points("2026-10-25 00:00:00+02:00", 100)

    frame = parse_day({"day_ahead_price": doc(points)}, "day_ahead_price", tz=TZ)

    assert len(frame) == 100
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2026-10-25 00:00", tz=TZ)
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2026-10-25 23:45+01:00")


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        json.dumps({"series": "not a list"}),
        json.dumps({"series": [[1, 2, 3]]}),
        json.dumps({"series": [["not_ms", 1.0]]}),
        json.dumps({"series": [[1, "not_a_value"]]}),
        json.dumps([1, 2, 3]),
    ],
)
def test_malformed_docs_raise_clean_error(text):
    with pytest.raises(ValueError, match="unparseable load_actual"):
        parse_day({"load_actual": text}, "load_actual", tz=TZ)


def test_unknown_method():
    with pytest.raises(ValueError, match="unknown smard method"):
        parse_day({}, "bogus")
