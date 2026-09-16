import pandas as pd
import pytest

from delukit.layers.silver.parsers.weather import parse_day

TZ = "Europe/Berlin"


def item(times, temperature, wind):
    return {
        "latitude": 52.548,
        "longitude": 13.408,
        "elevation": 38.0,
        "utc_offset_seconds": 7200,
        "hourly": {
            "time": times,
            "temperature_2m": temperature,
            "wind_speed_100m": wind,
        },
    }


def raw(*items):
    return {
        "forecast": {
            "run": "2025-10-01T00:00",
            "model": "ecmwf_ifs",
            "locations": {"berlin": items[0], "hamburg": items[1]}
            if len(items) > 1
            else {"berlin": items[0]},
        }
    }


TIMES = ["2025-10-01T02:00", "2025-10-01T03:00", "2025-10-01T04:00"]


def test_parse_day_wide_frame_per_location():
    frame = parse_day(
        raw(
            item(TIMES, [12.5, 12.6, None], [20.0, 21.0, None]),
            item(TIMES, [10.0, 10.1, None], [30.0, 31.0, None]),
        ),
        "forecast",
        tz=TZ,
    )

    assert list(frame.columns) == [
        "location",
        "run_time",
        "valid_time",
        "temperature_2m",
        "wind_speed_100m",
    ]
    assert len(frame) == 4
    assert set(frame["location"]) == {"berlin", "hamburg"}
    assert (frame["run_time"] == pd.Timestamp("2025-10-01 00:00", tz="UTC")).all()
    assert frame["valid_time"].iloc[0] == pd.Timestamp("2025-10-01 02:00", tz=TZ)
    assert frame["valid_time"].dt.tz.key == TZ
    assert frame["temperature_2m"].tolist() == [12.5, 12.6, 10.0, 10.1]


def test_trailing_all_null_hours_are_trimmed():
    frame = parse_day(
        raw(item(TIMES, [12.5, None, None], [20.0, None, None])),
        "forecast",
        tz=TZ,
    )

    assert len(frame) == 1
    assert frame["valid_time"].iloc[0] == pd.Timestamp("2025-10-01 02:00", tz=TZ)


def test_partial_nulls_are_kept():
    frame = parse_day(
        raw(item(TIMES, [None, 12.6, None], [20.0, 21.0, None])),
        "forecast",
        tz=TZ,
    )

    assert len(frame) == 2
    assert pd.isna(frame["temperature_2m"].iloc[0])
    assert frame["temperature_2m"].iloc[1] == 12.6


def test_missing_doc_is_empty():
    assert parse_day({}, "forecast", tz=TZ).empty


def test_unknown_method():
    with pytest.raises(ValueError, match="unknown weather method"):
        parse_day({}, "bogus")


def test_missing_locations_raises():
    with pytest.raises(ValueError, match="locations"):
        parse_day({"forecast": {"run": "2025-10-01T00:00"}}, "forecast", tz=TZ)


def test_missing_run_raises():
    with pytest.raises(ValueError, match="run must be a string"):
        parse_day(
            {"forecast": {"locations": {"berlin": item(TIMES, [1.0], [2.0])}}},
            "forecast",
            tz=TZ,
        )


def test_mismatched_array_lengths_raise():
    bad = item(TIMES, [12.5], [20.0])
    bad["hourly"]["temperature_2m"] = [12.5, 13.0]

    with pytest.raises(ValueError, match="mismatched array lengths"):
        parse_day(raw(bad), "forecast", tz=TZ)


def test_scalar_field_raises():
    bad = item(TIMES, [12.5], [20.0])
    bad["hourly"]["temperature_2m"] = 12.5

    with pytest.raises(ValueError, match="mismatched array lengths"):
        parse_day(raw(bad), "forecast", tz=TZ)


def test_spring_forward_day_skips_nonexistent_hour():
    times = [
        "2026-03-29T00:00",
        "2026-03-29T01:00",
        "2026-03-29T02:00",
        "2026-03-29T03:00",
    ]
    frame = parse_day(
        raw(item(times, [4.0, 4.1, 4.2, 4.3], [20.0, 20.0, 20.0, 20.0])),
        "forecast",
        tz=TZ,
    )

    assert len(frame) == 3
    assert "02" not in frame["valid_time"].dt.strftime("%H").tolist()
    assert frame["temperature_2m"].tolist() == [4.0, 4.1, 4.3]


def test_fall_back_day_keeps_both_duplicate_hours():
    times = [
        "2026-10-25T01:00",
        "2026-10-25T02:00",
        "2026-10-25T02:00",
        "2026-10-25T03:00",
    ]
    frame = parse_day(
        raw(item(times, [10.0, 11.0, 12.0, 13.0], [20.0, 20.0, 20.0, 20.0])),
        "forecast",
        tz=TZ,
    )

    assert len(frame) == 4
    assert frame["valid_time"].dt.strftime("%H").tolist() == ["01", "02", "02", "03"]
    assert (
        frame["valid_time"].iloc[1].utcoffset()
        != frame["valid_time"].iloc[2].utcoffset()
    )
    assert frame["temperature_2m"].tolist() == [10.0, 11.0, 12.0, 13.0]


def test_missing_hourly_raises():
    with pytest.raises(ValueError, match="missing hourly data"):
        parse_day(raw({"latitude": 52.5}), "forecast", tz=TZ)


def test_malformed_payload_raises_clean_error():
    with pytest.raises(ValueError, match="unparseable forecast"):
        parse_day({"forecast": "not a dict"}, "forecast", tz=TZ)
