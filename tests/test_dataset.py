"""Versioned point-in-time parts: availability stamps must never leak.

Why these: a wrong available_at leaks future data into the gate (inflated
skill) or hides known data (degraded forecasts). Guard test pins the loud
failure on schema drift.
"""

from datetime import date, timedelta
from datetime import time as dtime

import pandas as pd
import pytest


def _frame(idx, **cols):
    df = pd.DataFrame(cols, index=idx)
    df["timestamp_berlin"] = idx.tz_convert("Europe/Berlin")
    df["date"] = df["timestamp_berlin"].dt.date.astype(str)
    df["quarter"] = 1
    return df


def test_delayed_stamps_index_plus_delay(qindex):
    from delukit.dataset import _delayed

    df = _frame(qindex, load_actual_mw=[1.0, 2.0, 3.0, 4.0])
    part = _delayed(df, ["load_actual_mw"], timedelta(minutes=75))
    assert (part.data["available_at"] == part.data.index + timedelta(minutes=75)).all()


def test_published_lands_day_before_at_wall(qindex):
    from delukit.dataset import _published

    df = _frame(qindex, load_forecast_mw=[1.0, 2.0, 3.0, 4.0])
    part = _published(df, ["load_forecast_mw"], dtime(10, 30))
    avail = part.data["available_at"]
    # Berlin day 2026-01-05 published 2026-01-04 10:30 Berlin
    assert (avail.dt.tz_convert("Europe/Berlin").dt.date == date(2026, 1, 4)).all()
    assert (avail.dt.tz_convert("Europe/Berlin").dt.hour == 10).all()


def test_guard_unmapped_raises_on_drift(qindex):
    from delukit.dataset import _guard_unmapped

    df = _frame(qindex, load_actual_mw=[1.0] * 4, new_col=[1.0] * 4)
    with pytest.raises(ValueError, match="unmapped clean columns"):
        _guard_unmapped(df, ["load_actual_mw"])
    _guard_unmapped(df, ["load_actual_mw"], skipped=("new_col",))  # ok


def test_entsoe_parts_split_five_events(qindex):
    from delukit.dataset import _entsoe_parts

    df = _frame(
        qindex,
        load_actual_mw=[1.0] * 4,
        gen_actual_B01_mw=[1.0] * 4,
        load_forecast_mw=[1.0] * 4,
        gen_forecast_total_mw=[1.0] * 4,
        solar_forecast_mw=[1.0] * 4,
        wind_offshore_forecast_mw=[1.0] * 4,
        wind_onshore_forecast_mw=[1.0] * 4,
        price_exaa_eur_mwh=[1.0] * 4,
        price_sdac_seq1_eur_mwh=[1.0] * 4,
        price_sdac_seq2_eur_mwh=[1.0] * 4,
    )
    parts = _entsoe_parts(df)
    assert set(parts) == {
        "entsoe_actuals",
        "exaa",
        "sdac",
        "entsoe_day_ahead",
        "tso_day_ahead",
    }
    assert "load_actual_mw" in parts["entsoe_actuals"].feature_names


def test_smard_parts_derives_total_and_skips_price(qindex):
    from delukit.core.config.products import GEN_TOTAL_COLUMNS
    from delukit.dataset import _smard_parts

    cols = {
        "load_actual_mwh": [10.0] * 4,
        "load_forecast_mwh": [9.0] * 4,
        "gen_forecast_wind_onshore_mwh": [2.0] * 4,
        "price_day_ahead_eur_mwh": [50.0] * 4,  # restatement, skipped not mapped
    }
    cols.update({c: [1.0] * 4 for c in GEN_TOTAL_COLUMNS})
    df = _frame(qindex, **cols)
    parts = _smard_parts(df)
    assert set(parts) == {"smard_actuals", "smard_day_ahead"}
    assert (parts["smard_actuals"].data["gen_actual_total_mwh"] == 12.0).all()


def test_calendar_part_excludes_unproven_holiday_vintage(qindex):
    from delukit.dataset import _calendar_part

    df = _frame(
        qindex,
        is_holiday=[True] * 4,
        is_weekend=[False] * 4,
        school_subdivisions=["BY|BW"] * 4,  # identifier, not a feature
    )
    part = _calendar_part(df)
    assert "is_holiday_delu" not in part.feature_names
    assert "is_holiday" not in part.feature_names
    assert "is_weekend" in part.feature_names
    assert "day_of_week" in part.feature_names
    assert "school_subdivisions" not in part.feature_names


def test_weather_part_expands_hourly_to_quarters():
    import pandas as pd

    from delukit.core.clean import UTC
    from delukit.dataset import WEATHER_FFILL_LIMIT, _weather_part

    assert WEATHER_FFILL_LIMIT == 7
    idx = pd.date_range("2026-01-05 00:00", periods=3, freq="h", tz=UTC)
    df = pd.DataFrame(
        {
            "timestamp_utc": idx,
            "run_day": ["2026-01-04"] * 3,
            "location": ["frankfurt"] * 3,
            "temperature_2m": [1.0, 2.0, 3.0],
            "wind_speed_100m": [1.0, 1.0, 1.0],
            "wind_direction_100m": [0.0, 0.0, 0.0],
            "shortwave_radiation": [0.0, 0.0, 0.0],
            "cloud_cover": [0.0, 0.0, 0.0],
        }
    ).set_index("timestamp_utc")
    part = _weather_part(df)
    # 3 hourly points -> quarter grid covers 3h = 12 quarters minus edges
    assert len(part.data) >= 9
    assert "temperature_2m__frankfurt" in part.feature_names
    # run_day + WEATHER_RUN_PUBLISH_UTC (07:00 UTC), not midnight
    assert (part.data["available_at"] == pd.Timestamp("2026-01-04 07:00", tz=UTC)).all()


def test_visible_filters_by_gate(qindex):
    from datetime import datetime

    import pandas as pd

    from delukit.core.clean import BERLIN, UTC
    from delukit.dataset import _delayed, _gate, _visible

    df = _frame(qindex, load_actual_mw=[1.0] * 4)
    part = _delayed(df, ["load_actual_mw"], timedelta(minutes=75))
    gate = _gate(date(2026, 1, 5), dtime(5, 30))
    assert gate == pd.Timestamp(datetime(2026, 1, 5, 5, 30, tzinfo=BERLIN)).tz_convert(
        UTC
    )
    rows = _visible(part, date(2026, 1, 5), gate)
    assert not rows.empty
    # gate before any data -> nothing visible
    early = _gate(date(2026, 1, 4), dtime(5, 30))
    assert _visible(part, date(2026, 1, 5), early).empty


def test_post_gate_provider_fetch_cannot_enter_earlier_gate(tmp_dirs, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from openstef_core.datasets import TimeSeriesDataset

    from delukit.dataset import _observed_part
    from delukit.sources import observations

    class Clock(datetime):
        @classmethod
        def now(cls, _zone):
            return datetime(2026, 1, 5, 10, 45, tzinfo=UTC)

    monkeypatch.setattr(observations, "datetime", Clock)
    current = tmp_dirs["raw"] / "2026-01-06" / "entsoe" / "EXAA" / "data.xml"
    current.parent.mkdir(parents=True)
    current.write_bytes(b"<TimeSeries/>")
    observations.observe(current, current.read_bytes(), semantic=current.read_bytes())
    idx = pd.DatetimeIndex([pd.Timestamp("2026-01-06T00:00:00Z")])
    part = TimeSeriesDataset(
        pd.DataFrame(
            {
                "price_exaa_eur_mwh": [50.0],
                "available_at": [pd.Timestamp("2026-01-05T10:30:00Z")],
            },
            index=idx,
        ),
        sample_interval=timedelta(minutes=15),
    )
    observed = _observed_part(part, "entsoe", {"EXAA": ["price_exaa_eur_mwh"]})
    gate = pd.Timestamp("2026-01-05T10:30:00Z")
    assert observed.data["available_at"].iloc[0] == pd.Timestamp("2026-01-05T10:45:00Z")
    assert observed.filter_by_available_before(gate).data.empty
