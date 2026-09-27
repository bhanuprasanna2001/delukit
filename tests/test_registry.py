import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from openstef_core.datasets import (
    ForecastDataset,
    TimeSeriesDataset,
    VersionedTimeSeriesDataset,
)
from openstef_core.exceptions import PredictError
from openstef_core.types import LeadTime, Q
from openstef_models.models.forecasting.constant_quantile_forecaster import (
    ConstantQuantileForecaster,
)
from openstef_models.models.forecasting_model import ForecastingModel
from openstef_models.workflows.custom_forecasting_workflow import (
    CustomForecastingWorkflow,
)

from delukit.core.clean import quarter_grid


def _trained_model(value: float) -> tuple[ForecastingModel, TimeSeriesDataset]:
    index = pd.date_range("2026-01-01", periods=96 * 15, freq="15min", tz="UTC")
    data = TimeSeriesDataset(
        pd.DataFrame({"load": [value] * len(index)}, index=index),
        sample_interval=timedelta(minutes=15),
    )
    workflow = CustomForecastingWorkflow(
        model=ForecastingModel(
            forecaster=ConstantQuantileForecaster(
                horizons=[LeadTime(timedelta(hours=24))],
                quantiles=[Q(level / 10) for level in range(1, 10)],
            ),
            target_column="load",
            tags={"model_type": "constant_quantile"},
        ),
        model_id="load__0530__d1",
    )
    workflow.fit(data)
    return workflow.model, data


def test_active_alias_selects_exact_registered_openstef_model(tmp_path, monkeypatch):
    from delukit.core.config import products
    from delukit.models.registry import _register_run, load_active

    monkeypatch.setattr(products, "MLFLOW_DIR", tmp_path / "mlflow")
    storage = products.mlflow_storage()
    client = MlflowClient(tracking_uri=storage.tracking_uri)
    name = "load__0530__d1"
    versions = []
    for value in (10.0, 30.0):
        model, data = _trained_model(value)
        run = storage.create_run(name)
        storage.save_run_model(name, run.info.run_id, model)
        storage.finalize_run(name, run.info.run_id)
        versions.append(_register_run(name, run.info.run_id))

    client.set_registered_model_alias(name, "active", versions[0])
    first = load_active("load", "0530", "d1")
    origin = data.data.index[-100].to_pydatetime()
    forecast = first.workflow.predict(data, forecast_start=origin)
    assert first.version == "1"
    assert {f"quantile_P{q}" for q in range(10, 100, 10)}.issubset(
        forecast.data.columns
    )
    assert set(forecast.data["quantile_P50"].dropna()) == {10.0}

    client.set_registered_model_alias(name, "active", versions[1])
    second = load_active("load", "0530", "d1")
    forecast = second.workflow.predict(data, forecast_start=origin)
    assert second.version == "2"
    assert set(forecast.data["quantile_P50"].dropna()) == {30.0}


def test_gate_cannot_publish_without_an_active_registered_model(tmp_path, monkeypatch):
    from delukit.core.config import products
    from delukit.models import forecast

    monkeypatch.setattr(products, "MLFLOW_DIR", tmp_path / "mlflow")
    monkeypatch.setattr(products, "FORECAST_DIR", tmp_path / "forecasts")
    with pytest.raises(MlflowException):
        forecast.run_gate(date(2026, 1, 5), "0530")
    assert not (tmp_path / "forecasts" / "2026-01-05" / "0530.json").exists()


def test_training_uses_last_complete_actual_day():
    from delukit.models.registry import _last_complete_day

    complete = quarter_grid(date(2026, 3, 29))
    partial = quarter_grid(date(2026, 3, 30))[:-1]
    data = TimeSeriesDataset(
        pd.DataFrame({"load": 1.0}, index=complete.append(partial)),
        sample_interval=timedelta(minutes=15),
    )
    assert len(complete) == 92
    assert _last_complete_day(data, "load", date(2026, 3, 31)) == date(2026, 3, 29)


def test_failed_refit_keeps_active_version(tmp_path, monkeypatch):
    from delukit.core.config import products
    from delukit.models import forecast, registry

    monkeypatch.setattr(products, "MLFLOW_DIR", tmp_path / "mlflow")
    monkeypatch.setitem(products.PRODUCTS_BY_GATE, "0530", (("d1", "load"),))
    monkeypatch.setitem(products.PRODUCTS_BY_GATE, "1130", ())
    storage = products.mlflow_storage()
    client = MlflowClient(tracking_uri=storage.tracking_uri)
    name = "load__0530__d1"
    model, data = _trained_model(10.0)
    run = storage.create_run(name)
    storage.save_run_model(name, run.info.run_id, model)
    storage.finalize_run(name, run.info.run_id)
    version = registry._register_run(name, run.info.run_id)
    client.set_registered_model_alias(name, "active", version)

    class AvailableData:
        def filter_by_available_before(self, cutoff):
            return self

        def select_version(self):
            return data

    monkeypatch.setattr(registry, "load", AvailableData)
    attempted = []

    class FailedWorkflow:
        run_name = None

        def fit(self, eligible):
            raise PredictError("failed refit")

    def create_workflow(target, gate, span, *, model, **kwargs):
        attempted.append((gate, model))
        return FailedWorkflow()

    monkeypatch.setattr(forecast, "create_workflow", create_workflow)
    with pytest.raises(RuntimeError, match="failed refit"):
        registry.train_all(datetime(2026, 1, 16, tzinfo=UTC))

    assert ("0530", "xgboost") in attempted
    assert [model for gate, model in attempted if gate == "0530"] == ["xgboost"]
    assert str(client.get_model_version_by_alias(name, "active").version) == version


def test_gate_publishes_pinned_version_and_input_snapshot(tmp_path, monkeypatch):
    from delukit.core.config import products
    from delukit.data.dataset import QUARTER
    from delukit.models import forecast, registry

    day = date(2026, 1, 5)
    gate = "0530"
    origin = forecast.gate_datetime(day, gate)
    frame = pd.DataFrame(
        {"load": [1.0], "available_at": [origin - timedelta(hours=1)]},
        index=pd.DatetimeIndex([origin - timedelta(hours=2)]),
    )
    data = VersionedTimeSeriesDataset(
        [TimeSeriesDataset(frame, sample_interval=QUARTER)]
    )
    monkeypatch.setattr(forecast, "load", lambda: data)
    monkeypatch.setitem(products.PRODUCTS_BY_GATE, gate, (("d1", "load"),))
    monkeypatch.setattr(products, "FORECAST_DIR", tmp_path / "forecasts")

    class Workflow:
        def predict(self, data, forecast_start):
            assert forecast_start == origin
            assert data.data["load"].dropna().tolist() == [1.0]
            grid = quarter_grid(day + timedelta(days=1))
            values = {
                f"quantile_P{q}": [float(q)] * len(grid) for q in range(10, 100, 10)
            }
            return ForecastDataset(
                pd.DataFrame(values, index=grid),
                sample_interval=QUARTER,
                forecast_start=forecast_start,
                target_column="load",
            )

    monkeypatch.setattr(
        registry,
        "load_active",
        lambda target, gate, span: SimpleNamespace(
            workflow=Workflow(), model_type="xgboost", version="7", run_id="run-7"
        ),
    )
    forecast.run_gate(day, gate)

    manifest = json.loads(
        (products.FORECAST_DIR / day.isoformat() / "0530.json").read_text()
    )
    assert manifest["products"][0]["model_version"] == "7"
    assert manifest["products"][0]["model_run_id"] == "run-7"
    snapshot = (
        products.FORECAST_DIR / day.isoformat() / manifest["input_snapshot"]["path"]
    )
    assert pd.read_parquet(snapshot)["load"].dropna().tolist() == [1.0]
