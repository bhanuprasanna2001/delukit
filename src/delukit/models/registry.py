"""Registered OpenSTEF models used by scheduled forecasts."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pandas as pd
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException
from mlflow.models import Model
from openstef_core.datasets import TimeSeriesDataset
from openstef_core.exceptions import (
    FlatlinerDetectedError,
    InsufficientlyCompleteError,
    PredictError,
)
from openstef_models.integrations.joblib import JoblibModelSerializer
from openstef_models.models.forecasting_model import BaseForecastingModel
from openstef_models.workflows.custom_forecasting_workflow import (
    CustomForecastingWorkflow,
)

from delukit.core.clean import BERLIN, quarter_grid
from delukit.core.config.products import SPANS, TARGETS, mlflow_storage, model_id
from delukit.data.dataset import load
from delukit.ops.publication import validate_product

FLAVOR = "delukit_openstef"
ACTIVE_ALIAS = "active"


@dataclass(frozen=True)
class RegisteredForecast:
    name: str
    version: str
    run_id: str
    workflow: CustomForecastingWorkflow

    @property
    def model_type(self) -> str:
        return self.workflow.model.tags["model_type"]


def _client() -> MlflowClient:
    storage = mlflow_storage()
    return MlflowClient(
        tracking_uri=storage.tracking_uri, registry_uri=storage.registry_uri
    )


def _register_run(name: str, run_id: str) -> str:
    storage = mlflow_storage()
    client = _client()
    run = client.get_run(run_id)
    if run.info.status != "FINISHED":
        raise ValueError(f"Training run {run_id} did not finish successfully.")
    artifact_dir = storage.get_artifacts_path(name, run_id) / storage.model_path
    model_file = artifact_dir / f"model.{storage.model_serializer.extension}"
    if not model_file.is_file():
        raise FileNotFoundError(model_file)

    descriptor = artifact_dir / "MLmodel"
    Model(
        run_id=run_id,
        artifact_path=storage.model_path,
        flavors={FLAVOR: {"data": model_file.name}},
    ).save(descriptor)
    client.log_artifact(run_id, str(descriptor), artifact_path=storage.model_path)

    try:
        client.create_registered_model(name)
    except MlflowException as exc:
        if exc.error_code != "RESOURCE_ALREADY_EXISTS":
            raise
    versions = client.search_model_versions(f"name = '{name}'")
    existing = next((item for item in versions if item.run_id == run_id), None)
    if existing is not None:
        return str(existing.version)
    created = client.create_model_version(
        name=name,
        source=f"runs:/{run_id}/{storage.model_path}",
        run_id=run_id,
    )
    return str(created.version)


def load_version(name: str, version: str) -> RegisteredForecast:
    storage = mlflow_storage()
    client = _client()
    metadata = client.get_model_version(name, version)
    run_id = metadata.run_id
    if not run_id:
        raise ValueError(f"Registered model {name} v{version} has no training run.")
    source = f"runs:/{run_id}/{storage.model_path}"
    if metadata.source != source:
        raise ValueError(f"Registered model {name} v{version} has unexpected source.")
    local = Path(client.download_artifacts(run_id, storage.model_path))
    flavor = Model.load(local).flavors.get(FLAVOR)
    if flavor is None:
        raise ValueError(
            f"Registered model {name} v{version} is not an OpenSTEF model."
        )
    with (local / flavor["data"]).open("rb") as stream:
        model = JoblibModelSerializer().deserialize(file=stream)
    if not isinstance(model, BaseForecastingModel) or not model.is_fitted:
        raise ValueError(f"Registered model {name} v{version} is not fitted.")
    return RegisteredForecast(
        name=name,
        version=version,
        run_id=run_id,
        workflow=CustomForecastingWorkflow(model=model, model_id=name),
    )


def load_active(target: str, gate: str, span: str) -> RegisteredForecast:
    name = model_id(target, gate, span)
    version = _client().get_model_version_by_alias(name, ACTIVE_ALIAS)
    return load_version(name, str(version.version))


def _last_complete_day(data: TimeSeriesDataset, target: str, as_of: date) -> date:
    series = data.data[target]
    if not isinstance(series, pd.Series):
        raise ValueError(f"Expected one actual series for {target}.")
    for age in range(1, 15):
        day = as_of - timedelta(days=age)
        if bool(series.reindex(quarter_grid(day)).notna().all()):
            return day
    raise ValueError(f"{target} has no complete actual day in the past 14 days.")


def train_all(as_of: datetime) -> list[dict]:
    from delukit.models.forecast import (
        FALLBACK_MODELS,
        PRIMARY_MODEL,
        create_workflow,
        gate_datetime,
        predict_product,
    )

    if as_of.tzinfo is None:
        raise ValueError("Training cutoff must be timezone aware.")
    local_day = as_of.astimezone(BERLIN).date()
    data = load().filter_by_available_before(as_of).select_version()
    outcomes: list[dict] = []
    failures: list[str] = []
    client = _client()
    storage = mlflow_storage()

    for gate in ("0530", "1130"):
        for span in SPANS:
            for target in TARGETS:
                name = model_id(target, gate, span)
                try:
                    complete_day = _last_complete_day(data, target, local_day)
                    training_end = datetime.combine(
                        complete_day + timedelta(days=1), time.min, BERLIN
                    ) - timedelta(minutes=15)
                    eligible = data.filter_by_range(end=training_end)
                    run_name = uuid4().hex
                    try:
                        client.get_model_version_by_alias(name, ACTIVE_ALIAS)
                    except MlflowException as exc:
                        if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
                            raise
                        algorithms = (PRIMARY_MODEL, *FALLBACK_MODELS)
                    else:
                        algorithms = (PRIMARY_MODEL,)
                    for algorithm in algorithms:
                        workflow = create_workflow(
                            target,
                            gate,
                            span,
                            model=algorithm,
                            registry=True,
                            force_retrain=True,
                        )
                        workflow.run_name = run_name
                        try:
                            workflow.fit(eligible)
                            if not workflow.model.is_fitted:
                                raise PredictError(f"{name} did not fit")
                            break
                        except (
                            FlatlinerDetectedError,
                            InsufficientlyCompleteError,
                            PredictError,
                        ):
                            if algorithm == algorithms[-1]:
                                raise
                    run = storage.search_run(name, run_name)
                    if run is None:
                        raise ValueError(f"OpenSTEF did not record a run for {name}.")
                    version = _register_run(name, run.info.run_id)
                    registered = load_version(name, version)
                    origin = gate_datetime(local_day, gate)
                    forecast = predict_product(
                        registered.workflow, span, forecast_origin=origin
                    )

                    with TemporaryDirectory() as tmp:
                        sample = Path(tmp) / "forecast.parquet"
                        forecast.to_parquet(sample)
                        validate_product(sample, local_day, span)
                    client.set_registered_model_alias(name, ACTIVE_ALIAS, version)
                    outcomes.append(
                        {
                            "target": target,
                            "gate": gate,
                            "span": span,
                            "model": registered.model_type,
                            "model_version": version,
                            "model_run_id": run.info.run_id,
                            "training_end": complete_day.isoformat(),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    failures.append(f"{name}: {type(exc).__name__}: {exc}")
    if failures:
        raise RuntimeError("Training failed for:\n" + "\n".join(failures))
    return outcomes
