from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest


def test_sync_fails_when_a_provider_reports_failed_fetches(monkeypatch):
    import logging
    from contextlib import nullcontext

    from delukit.sources import sync

    class Provider:
        @staticmethod
        def sync(*args, **kwargs):
            return {
                "fetched": 0,
                "updated": 0,
                "unchanged": 0,
                "no_data": 0,
                "failed": 1,
            }

    monkeypatch.setattr(sync, "SOURCES", {"provider": (Provider, ["series"])})
    monkeypatch.setattr(
        sync, "sync_progress", lambda totals: nullcontext(lambda *a: None)
    )
    monkeypatch.setattr(sync, "setup_logging", lambda: logging.getLogger("test-sync"))
    monkeypatch.setattr(sync, "show_header", lambda end: None)
    monkeypatch.setattr(sync, "show_summary", lambda counts: None)

    with pytest.raises(RuntimeError, match="source sync failed"):
        sync.main()


def test_gate_datetime_is_berlin_gate_in_utc():
    import pandas as pd

    from delukit.models.forecast import gate_datetime

    got = gate_datetime(date(2026, 1, 5), "0530")
    want = pd.Timestamp(
        datetime(2026, 1, 5, 5, 30, tzinfo=ZoneInfo("Europe/Berlin"))
    ).tz_convert("UTC")
    assert got == want


def test_infer_gate_boundaries():
    from delukit.models.forecast import infer_gate

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
    from delukit.data.dataset import QUARTER
    from delukit.models.forecast import slice_span

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
    from delukit.models.forecast import workflow_config

    cfg = workflow_config("load_actual_mw", "0530", "d1", use_tuned=False)
    assert cfg.target_column == "load_actual_mw"
    assert cfg.horizons == HORIZONS[("0530", "d1")]
    excluded = cfg.selected_features.exclude
    assert "load_actual_mw" not in excluded
    assert "load_actual_mwh" in excluded
    assert "price_exaa_eur_mwh" in excluded
    day_cfg = workflow_config("load_actual_mw", "1130", "d1", use_tuned=False)
    assert "price_exaa_eur_mwh" not in day_cfg.selected_features.exclude


def test_predict_with_fallback_degrades_and_reports(monkeypatch):
    from openstef_core.exceptions import InsufficientlyCompleteError, PredictError

    import delukit.models.forecast as F

    calls = []

    def fake_fit(target, gate, span, **kw):
        calls.append(kw.get("model"))
        raise InsufficientlyCompleteError("nope")

    def fake_predict(workflow, target, gate, span, day):
        raise AssertionError("should not reach predict when fit fails")

    monkeypatch.setattr(F, "fit_product", fake_fit)
    monkeypatch.setattr(F, "predict_product", fake_predict)
    with pytest.raises(PredictError) as exc_info:
        F.predict_with_fallback("t", "0530", "d1", date(2026, 1, 5))
    assert "all models failed" in str(exc_info.value)
    assert "xgboost" in str(exc_info.value)
    assert calls[0] == "xgboost"


def test_predict_with_fallback_uses_first_success(monkeypatch):
    import delukit.models.forecast as F

    sentinel = object()
    monkeypatch.setattr(F, "fit_product", lambda *a, **k: "wf")
    monkeypatch.setattr(F, "predict_product", lambda *a, **k: sentinel)
    out, model = F.predict_with_fallback("t", "0530", "d1", date(2026, 1, 5))
    assert out is sentinel and model == "xgboost"


def test_missing_registry_model_stays_unregistered(monkeypatch):
    from openstef_core.exceptions import ModelNotFoundError

    import delukit.models.forecast as F

    sentinel = object()
    fit_kwargs = []
    monkeypatch.setattr(F, "create_workflow", lambda *a, **k: "registry")

    def fake_predict(workflow, *args, **kwargs):
        if workflow == "registry":
            raise ModelNotFoundError(model_id="missing")
        return sentinel

    def fake_fit(*args, **kwargs):
        fit_kwargs.append(kwargs)
        return "local"

    monkeypatch.setattr(F, "predict_product", fake_predict)
    monkeypatch.setattr(F, "fit_product", fake_fit)

    out, model = F.predict_with_fallback(
        "load_actual_mw", "0530", "d1", date(2026, 1, 5), registry=True
    )
    assert out is sentinel
    assert model == "xgboost_unregistered"
    assert fit_kwargs == [
        {
            "forecast_origin": F.gate_datetime(date(2026, 1, 5), "0530"),
            "model": "xgboost",
            "registry": False,
        }
    ]


def test_fitting_and_prediction_share_forecast_origin(monkeypatch):
    import pandas as pd
    from openstef_core.datasets import (
        ForecastDataset,
        TimeSeriesDataset,
        VersionedTimeSeriesDataset,
    )

    import delukit.models.forecast as F
    from delukit.core.clean import UTC, quarter_grid
    from delukit.data.dataset import QUARTER

    day = date(2026, 1, 5)
    origin = F.gate_datetime(day, "0530")
    index = pd.date_range("2026-01-05 00:00", periods=3, freq="h", tz=UTC)
    available_at = pd.to_datetime(
        ["2026-01-05 03:00Z", "2026-01-05 04:30Z", "2026-01-05 05:00Z"]
    )
    part = TimeSeriesDataset(
        pd.DataFrame(
            {"feature": [1.0, 2.0, 3.0], "available_at": available_at},
            index=index,
        ),
        sample_interval=QUARTER,
    )
    dataset = VersionedTimeSeriesDataset([part])
    captured = {}

    class Model:
        is_fitted = True

    class Workflow:
        model = Model()

        def fit(self, data):
            captured["fit"] = data.data["feature"].dropna().tolist()

        def predict(self, data, forecast_start):
            captured["predict"] = data.data["feature"].dropna().tolist()
            captured["forecast_start"] = forecast_start
            grid = quarter_grid(day + timedelta(days=1))
            return ForecastDataset(
                pd.DataFrame({"quantile_P50": [1.0] * len(grid)}, index=grid),
                sample_interval=QUARTER,
                forecast_start=forecast_start,
                target_column="target",
            )

    monkeypatch.setattr(F, "load", lambda: dataset)
    monkeypatch.setattr(F, "create_workflow", lambda *args, **kwargs: Workflow())

    forecast, model = F.predict_with_fallback(
        "target", "0530", "d1", day, models=("xgboost",)
    )

    assert captured == {
        "fit": [1.0, 2.0],
        "predict": [1.0, 2.0],
        "forecast_start": origin,
    }
    assert model == "xgboost"
    assert forecast.forecast_start == origin


def test_fit_product_anchors_training_window_to_forecast_origin(monkeypatch):
    import pandas as pd
    from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset

    import delukit.models.forecast as F
    from delukit.data.dataset import QUARTER

    origin = F.gate_datetime(date(2026, 1, 5), "0530")
    index = pd.DatetimeIndex(
        [
            origin - timedelta(hours=36),
            origin - timedelta(hours=24),
            origin - timedelta(hours=12),
            origin,
        ]
    )
    part = TimeSeriesDataset(
        pd.DataFrame(
            {
                "feature": [1.0, 2.0, 3.0, 4.0],
                "available_at": [origin - timedelta(days=2)] * 4,
            },
            index=index,
        ),
        sample_interval=QUARTER,
    )
    captured = {}

    class Model:
        is_fitted = True

    class Workflow:
        model = Model()

        def fit(self, data):
            captured["fit"] = data.data["feature"].dropna().tolist()

    monkeypatch.setattr(F, "load", lambda: VersionedTimeSeriesDataset([part]))
    monkeypatch.setattr(F, "create_workflow", lambda *args, **kwargs: Workflow())

    F.fit_product(
        "target",
        "0530",
        "d1",
        forecast_origin=origin,
        train_days=1,
    )

    assert captured["fit"] == [2.0, 3.0]


def test_backtest_split_target_and_bands():
    import pandas as pd
    from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset

    from delukit.core.clean import BERLIN, UTC
    from delukit.data.dataset import QUARTER
    from delukit.evaluation.backtest import split_bands, split_target

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

    from delukit.core.clean import quarter_grid

    gate_ts = pd.Timestamp(datetime(2026, 1, 5, 5, 30, tzinfo=BERLIN)).tz_convert(UTC)
    grid = quarter_grid(date(2026, 1, 6))
    frame = pd.DataFrame({"available_at": [gate_ts] * len(grid)}, index=grid)
    bands = split_bands(TimeSeriesDataset(frame, sample_interval=QUARTER), "0530")
    assert list(bands) == ["d1"]
    assert len(bands["d1"].data) == 96


def test_dagster_partition_and_expected_rows():
    from delukit.dagster_app.definitions import _partition_day_gate
    from delukit.ops.publication import expected_index

    assert _partition_day_gate("2026-01-05|0530") == (date(2026, 1, 5), "0530")
    assert len(expected_index(date(2026, 1, 5), "d1")) == 96
    assert len(expected_index(date(2026, 1, 5), "d10")) == 960
    assert len(expected_index(date(2026, 3, 28), "d1")) == 92


def test_ops_failure_alert_never_raises(monkeypatch, tmp_path):
    from unittest.mock import MagicMock

    from dagster._core.definitions.run_status_sensor_definition import (
        RunStatusSensorContext,
    )

    from delukit.dagster_app import definitions as D
    from delukit.ops import alerts

    monkeypatch.setattr(D, "ALERTS_LOG", tmp_path / "alerts.log")
    monkeypatch.setattr(alerts, "ALERT_DB", tmp_path / "alerts.db")
    monkeypatch.setenv("DELUKIT_ALERT_WEBHOOK", "")

    ctx = MagicMock(spec=RunStatusSensorContext)
    ctx.dagster_run.job_name = "j"
    ctx.dagster_run.run_id = "r"
    ctx.dagster_event = None
    D.ops_failure_alert(ctx)
    assert (tmp_path / "alerts.log").exists()
