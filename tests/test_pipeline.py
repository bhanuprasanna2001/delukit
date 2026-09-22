"""Gate math, fallback chain, bands, dagster guards.

Why these: wrong gate/horizon leaks future lags; fallback returning nothing
is an outage; multi-day bands without bucketing silently re-score d1 skill.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo


def test_gate_datetime_is_berlin_gate_in_utc():
    import pandas as pd

    from delukit.forecast import gate_datetime

    got = gate_datetime(date(2026, 1, 5), "0530")
    want = pd.Timestamp(
        datetime(2026, 1, 5, 5, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    ).tz_convert("UTC")
    assert got == want


def test_infer_gate_boundaries():
    from delukit.forecast import infer_gate

    berlin = ZoneInfo("Europe/Berlin")
    assert infer_gate(datetime(2026, 1, 5, 5, 29, tzinfo=berlin)) == (
        date(2026, 1, 4),
        "1130",
    )
    assert infer_gate(datetime(2026, 1, 5, 5, 30, tzinfo=berlin)) == (
        date(2026, 1, 5),
        "0530",
    )
    assert infer_gate(datetime(2026, 1, 5, 11, 29, tzinfo=berlin)) == (
        date(2026, 1, 5),
        "0530",
    )
    assert infer_gate(datetime(2026, 1, 5, 11, 30, tzinfo=berlin)) == (
        date(2026, 1, 5),
        "1130",
    )


def test_slice_span_cuts_d1_vs_d10():
    import pandas as pd
    from openstef_core.datasets import ForecastDataset

    from delukit.core.clean import UTC
    from delukit.dataset import QUARTER
    from delukit.forecast import slice_span

    idx = pd.date_range("2026-01-05 23:00", periods=96 * 11, freq="15min", tz=UTC)
    fc = ForecastDataset(
        pd.DataFrame({"quantile_P50": range(len(idx))}, index=idx),
        sample_interval=QUARTER,
        target_column="load_actual_mw",
    )
    d1 = slice_span(fc, date(2026, 1, 5), "d1")
    d10 = slice_span(fc, date(2026, 1, 5), "d10")
    assert len(d1.data) == 96
    assert len(d10.data) == 960


def test_workflow_config_horizons_and_excludes():
    from delukit.core.config.products import HORIZONS
    from delukit.forecast import workflow_config

    cfg = workflow_config("load_actual_mw", "0530", "d1", use_tuned=False)
    assert cfg.target_column == "load_actual_mw"
    assert cfg.horizons == HORIZONS[("0530", "d1")]
    excluded = cfg.selected_features.exclude
    assert "load_actual_mw" not in excluded  # target itself always kept
    assert "load_actual_mwh" in excluded  # sister-source actuals never features
    assert "price_exaa_eur_mwh" in excluded  # 0530 sees no published curves
    day_cfg = workflow_config("load_actual_mw", "1130", "d1", use_tuned=False)
    assert "price_exaa_eur_mwh" not in day_cfg.selected_features.exclude


def test_predict_with_fallback_degrades_and_reports(monkeypatch):
    from openstef_core.exceptions import InsufficientlyCompleteError, PredictError

    import delukit.forecast as F

    calls = []

    def fake_fit(target, gate, span, **kw):
        calls.append(kw.get("model"))
        raise InsufficientlyCompleteError("nope")

    def fake_predict(workflow, target, gate, span, day):
        raise AssertionError("should not reach predict when fit fails")

    monkeypatch.setattr(F, "fit_product", fake_fit)
    monkeypatch.setattr(F, "predict_product", fake_predict)
    try:
        F.predict_with_fallback("t", "0530", "d1", date(2026, 1, 5))
        assert False, "must raise"
    except PredictError as e:
        assert "all models failed" in str(e)
        assert "xgboost" in str(e)
    assert calls[0] == "xgboost"


def test_predict_with_fallback_uses_first_success(monkeypatch):
    import delukit.forecast as F

    sentinel = object()
    monkeypatch.setattr(F, "fit_product", lambda *a, **k: "wf")
    monkeypatch.setattr(F, "predict_product", lambda *a, **k: sentinel)
    out, model = F.predict_with_fallback("t", "0530", "d1", date(2026, 1, 5))
    assert out is sentinel and model == "xgboost"


def test_backtest_split_target_and_bands():
    import pandas as pd
    from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset

    from delukit.backtest import split_bands, split_target
    from delukit.core.clean import BERLIN, UTC
    from delukit.dataset import QUARTER

    idx = pd.date_range("2026-01-06 00:00", periods=96, freq="15min", tz=UTC)
    avail = pd.Series([pd.Timestamp("2026-01-05 04:00", tz=UTC)] * len(idx), index=idx)
    part = TimeSeriesDataset(
        pd.DataFrame(
            {
                "load_actual_mw": [1.0] * 96,
                "x": [2.0] * 96,
                "available_at": avail.values,
            },
            index=idx,
        ),
        sample_interval=QUARTER,
    )
    ds = VersionedTimeSeriesDataset([part])
    truth, preds = split_target(ds, "load_actual_mw")
    assert truth.feature_names == ["load_actual_mw"]
    assert "load_actual_mw" not in preds.feature_names

    # bands: exactly the Berlin day 2026-01-06 -> d1 only
    from delukit.core.clean import quarter_grid

    gate_ts = pd.Timestamp(datetime(2026, 1, 5, 5, 30, tzinfo=BERLIN)).tz_convert(UTC)
    grid = quarter_grid(date(2026, 1, 6))
    frame = pd.DataFrame({"available_at": [gate_ts] * len(grid)}, index=grid)
    bands = split_bands(TimeSeriesDataset(frame, sample_interval=QUARTER), "0530")
    assert list(bands) == ["d1"]
    assert len(bands["d1"].data) == 96


def test_dagster_partition_and_expected_rows():
    from delukit.dagster_app.definitions import _expected_rows, _partition_day_gate

    assert _partition_day_gate("2026-01-05|0530") == (date(2026, 1, 5), "0530")
    assert _expected_rows(date(2026, 1, 5), "d1") == 96
    assert _expected_rows(date(2026, 1, 5), "d10") == 960
    # DST spring-forward D+1 has 92 quarters
    assert _expected_rows(date(2026, 3, 28), "d1") == 92


def test_dagster_check_forecast_files(tmp_dirs):
    import pandas as pd

    from delukit.core.clean import UTC
    from delukit.core.config.products import TARGETS
    from delukit.dagster_app.definitions import _check_forecast_files

    day = date(2026, 1, 5)
    fdir = tmp_dirs["forecasts"] / "2026-01-05" / "0530_d1"
    fdir.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2026-01-06 00:00", periods=96, freq="15min", tz=UTC)
    for t in TARGETS:
        pd.DataFrame(
            {
                "quantile_P10": [1.0] * 96,
                "quantile_P50": [2.0] * 96,
                "quantile_P90": [3.0] * 96,
            },
            index=idx,
        ).to_parquet(fdir / f"{t}__xgboost.parquet")
    ok, meta = _check_forecast_files(day, "0530", "d1")
    assert ok, meta
    # break one file -> fails
    next(iter(fdir.glob("*__*.parquet"))).unlink()
    ok2, meta2 = _check_forecast_files(day, "0530", "d1")
    assert not ok2 and "missing" in meta2["problems"]


def test_ops_failure_alert_never_raises(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from dagster._core.definitions.run_status_sensor_definition import (
        RunStatusSensorContext,
    )

    from delukit.dagster_app import definitions as D

    monkeypatch.setattr(D, "ALERTS_LOG", tmp_path / "alerts.log")
    monkeypatch.setenv("DELUKIT_ALERT_WEBHOOK", "")

    ctx = MagicMock(spec=RunStatusSensorContext)
    ctx.dagster_run.job_name = "j"
    ctx.dagster_run.run_id = "r"
    ctx.dagster_event = None
    D.ops_failure_alert(ctx)  # must not raise
    assert (tmp_path / "alerts.log").exists()
