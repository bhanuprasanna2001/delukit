from datetime import date, datetime, timedelta
from datetime import time as dtime
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

import pandas as pd
from openstef_beam.evaluation.metric_providers import (
    ObservedProbabilityProvider,
    R2Provider,
    RCRPSProvider,
)
from openstef_core.datasets import ForecastDataset, TimeSeriesDataset
from openstef_models.presets import (
    ForecastingWorkflowConfig,
    create_forecasting_workflow,
)
from openstef_models.utils.feature_selection import Exclude
from openstef_models.workflows.custom_forecasting_workflow import (
    CustomForecastingWorkflow,
)

from delukit.core.clean import BERLIN, UTC
from delukit.core.config.availability import GATES
from delukit.core.config.products import (
    CALIBRATE_QUANTILES,
    COMPLETENESS_THRESHOLD,
    DETECT_NON_ZERO_FLATLINER,
    FLATLINER_THRESHOLD,
    FLATLINER_THRESHOLDS,
    FORECAST_DIR,
    GATE_0530,
    GATE_1130,
    HORIZONS,
    LOCATION,
    N_JOBS,
    PREDICT_CONTEXT,
    PREDICT_LENGTH,
    QUANTILES,
    SPAN_D1,
    SPAN_D10,
    SPANS,
    TARGETS,
    TUNING_DIR,
    energy_price_column,
    feature_exclude,
    mlflow_storage,
    model_id,
    weather_ref,
)
from delukit.data.dataset import load, require_datetime_index
from delukit.ops.publication import begin_run, publish

GATE_WALL = {f"{wall:%H%M}": wall for wall in GATES}
PRIMARY_MODEL = "xgboost"
FALLBACK_MODELS = ("constant_quantile", "median", "flatliner")
ForecastModel = Literal[
    "xgboost",
    "gblinear",
    "flatliner",
    "median",
    "constant_quantile",
    "lgbm",
    "lgbmlinear",
]


class _ForecasterWithJobs(Protocol):
    n_jobs: int

    def model_post_init(self, context: object | None) -> None: ...


def _forecast_model(value: str) -> ForecastModel:
    match value:
        case "xgboost":
            return "xgboost"
        case "gblinear":
            return "gblinear"
        case "flatliner":
            return "flatliner"
        case "median":
            return "median"
        case "constant_quantile":
            return "constant_quantile"
        case "lgbm":
            return "lgbm"
        case "lgbmlinear":
            return "lgbmlinear"
        case _:
            raise ValueError(f"Unsupported forecast model: {value}")


def gate_datetime(day: date, gate: str) -> pd.Timestamp:
    stamp = pd.Timestamp(datetime.combine(day, GATE_WALL[gate], BERLIN).astimezone(UTC))
    if not isinstance(stamp, pd.Timestamp):
        raise ValueError(f"Could not construct a gate timestamp for {day} {gate}.")
    return stamp


def workflow_config(
    target: str,
    gate: str,
    span: str,
    *,
    model: str = PRIMARY_MODEL,
    registry: bool = False,
    use_tuned: bool = True,
    model_reuse_enable: bool = True,
) -> ForecastingWorkflowConfig:
    config = ForecastingWorkflowConfig(
        model_id=model_id(target, gate, span),
        model=_forecast_model(model),
        model_reuse_enable=model_reuse_enable,
        model_reuse_max_age=timedelta(days=36500) if registry else timedelta(days=7),
        model_selection_enable=False,
        quantiles=QUANTILES,
        horizons=HORIZONS[(gate, span)],
        target_column=target,
        energy_price_column=energy_price_column(target),
        temperature_column=weather_ref("temperature_2m"),
        wind_speed_column=weather_ref("wind_speed_100m"),
        radiation_column=weather_ref("shortwave_radiation"),
        location=LOCATION,
        predict_history=PREDICT_CONTEXT,
        cutoff_history=PREDICT_CONTEXT,
        completeness_threshold=COMPLETENESS_THRESHOLD,
        flatliner_threshold=FLATLINER_THRESHOLDS.get(target, FLATLINER_THRESHOLD),
        detect_non_zero_flatliner=target in DETECT_NON_ZERO_FLATLINER,
        evaluation_metrics=[
            R2Provider(),
            ObservedProbabilityProvider(),
            RCRPSProvider(),
        ],
        selected_features=Exclude(*feature_exclude(target, gate, span)),
        mlflow_storage=mlflow_storage() if registry else None,
        tags={"gate": gate, "span": span, "target": target},
    )
    if use_tuned and model == PRIMARY_MODEL:
        try:
            from openstef_models.models.forecasting.xgboost_forecaster import (
                XGBoostHyperParams,
            )

            path = TUNING_DIR / f"{target}__{gate}__{span}.json"
            if path.exists():
                config.xgboost_hyperparams = XGBoostHyperParams.model_validate_json(
                    path.read_text()
                )
        except (OSError, ValueError):
            pass
    return config


def create_workflow_from_config(
    config: ForecastingWorkflowConfig, *, calibrate: bool = True
) -> CustomForecastingWorkflow:
    from openstef_models.transforms.postprocessing import (
        IsotonicQuantileCalibrator,
        QuantileSorter,
    )

    workflow = create_forecasting_workflow(config)
    forecaster = getattr(workflow.model, "forecaster", None)
    if (
        forecaster is not None
        and hasattr(forecaster, "n_jobs")
        and hasattr(forecaster, "model_post_init")
    ):
        typed_forecaster = cast(_ForecasterWithJobs, forecaster)
        if typed_forecaster.n_jobs != N_JOBS:
            typed_forecaster.n_jobs = N_JOBS
            typed_forecaster.model_post_init(None)
    if calibrate and CALIBRATE_QUANTILES:
        postprocessing = workflow.model.postprocessing
        postprocessing.transforms = [
            *postprocessing.transforms,
            IsotonicQuantileCalibrator(
                quantiles=list(config.quantiles), use_local_quantile_estimation=True
            ),
            QuantileSorter(),
        ]
    return workflow


def create_workflow(
    target: str,
    gate: str,
    span: str,
    *,
    model: str = PRIMARY_MODEL,
    registry: bool = False,
    config: ForecastingWorkflowConfig | None = None,
    use_tuned: bool = True,
    force_retrain: bool = False,
) -> CustomForecastingWorkflow:
    calibrate = model == PRIMARY_MODEL
    config = config or workflow_config(
        target, gate, span, model=model, registry=registry, use_tuned=use_tuned
    )
    if force_retrain:
        config.model_reuse_enable = False
    return create_workflow_from_config(config, calibrate=calibrate)


def fit_product(
    target: str,
    gate: str,
    span: str,
    *,
    forecast_origin: datetime,
    model: str = PRIMARY_MODEL,
    train_days: int | None = None,
    registry: bool = False,
    force_retrain: bool = False,
) -> CustomForecastingWorkflow | None:
    ds = load()
    if train_days is not None:
        ds = ds.filter_by_range(
            forecast_origin - timedelta(days=train_days), forecast_origin
        )
    data = ds.filter_by_available_before(forecast_origin).select_version()
    workflow = create_workflow(
        target, gate, span, model=model, registry=registry, force_retrain=force_retrain
    )
    workflow.fit(data)
    return workflow if workflow.model.is_fitted else None


def slice_span(forecast: ForecastDataset, day: date, span: str) -> ForecastDataset:
    index = require_datetime_index(forecast.data.index)
    berlin_days = index.to_series().dt.tz_convert(BERLIN).dt.date
    last = day + timedelta(days=1 if span == SPAN_D1 else 10)
    keep = (berlin_days >= day + timedelta(days=1)) & (berlin_days <= last)
    selected = forecast.data.loc[keep]
    if not isinstance(selected, pd.DataFrame):
        raise TypeError("Expected a dataframe after selecting forecast rows.")
    return ForecastDataset(
        selected,
        sample_interval=forecast.sample_interval,
        forecast_start=forecast.forecast_start,
        target_column=forecast.target_column,
    )


def predict_product(
    workflow: CustomForecastingWorkflow,
    span: str,
    *,
    forecast_origin: datetime,
    data: TimeSeriesDataset | None = None,
) -> ForecastDataset:
    if data is None:
        data = (
            load()
            .filter_by_range(
                forecast_origin - PREDICT_CONTEXT,
                forecast_origin + PREDICT_LENGTH[span],
            )
            .filter_by_available_before(forecast_origin)
            .select_version()
        )
    else:
        data = data.filter_by_range(
            forecast_origin - PREDICT_CONTEXT,
            forecast_origin + PREDICT_LENGTH[span],
        )
    day = forecast_origin.astimezone(BERLIN).date()
    return slice_span(workflow.predict(data, forecast_start=forecast_origin), day, span)


def infer_gate(now: datetime | None = None) -> tuple[date, str]:
    berlin = (now or datetime.now(UTC)).astimezone(ZoneInfo("Europe/Berlin"))
    if berlin.time() >= dtime(11, 30):
        return berlin.date(), GATE_1130
    if berlin.time() >= dtime(5, 30):
        return berlin.date(), GATE_0530
    return berlin.date() - timedelta(days=1), GATE_1130


def write_gate_plots(
    day: date, gate: str, span: str | None = None, *, root=None
) -> None:
    from openstef_beam.analysis.plots import ForecastTimeSeriesPlotter

    spans = (span,) if span is not None else SPANS
    for s in spans:
        outdir = (
            root / s
            if root is not None
            else FORECAST_DIR / day.isoformat() / f"{gate}_{s}"
        )
        if not outdir.is_dir():
            continue
        for path in sorted(outdir.glob("*__*.parquet")):
            target, sep, used = path.stem.rpartition("__")
            if not sep or not target or not used:
                continue
            frame = pd.read_parquet(path)
            quantiles = [c for c in frame.columns if c.startswith("quantile_")]
            median = next((c for c in quantiles if "P50" in c), None)
            if median is None:
                continue
            forecast_series = frame[median]
            quantile_frame = frame[quantiles]
            if not isinstance(forecast_series, pd.Series) or not isinstance(
                quantile_frame, pd.DataFrame
            ):
                raise ValueError(f"Invalid quantile columns in {path}.")
            name = f"{target} {day} {gate} {s} [{used}]"
            ForecastTimeSeriesPlotter().add_model(
                model_name=name,
                forecast=forecast_series,
                quantiles=quantile_frame,
            ).plot(title=name).write_html(outdir / f"{target}__{used}.html")
            print(f"plot {day} {gate} {s} {target} -> {target}__{used}.html")


def run_gate(day: date, gate: str, targets: tuple[str, ...]) -> list[dict]:
    import os

    from delukit.models.registry import load_active

    selected = {
        (span, target): load_active(target, gate, span)
        for span in SPANS
        for target in targets
    }
    origin = gate_datetime(day, gate)
    input_data = (
        load()
        .filter_by_range(
            origin - PREDICT_CONTEXT,
            origin + PREDICT_LENGTH[SPAN_D10],
        )
        .filter_by_available_before(origin)
        .select_version()
    )

    run_dir = begin_run(day, gate)
    input_data.to_parquet(run_dir / "features.parquet")
    products = []
    for span in SPANS:
        outdir = run_dir / span
        outdir.mkdir()
        for target in targets:
            registered = selected[(span, target)]
            forecast = predict_product(
                registered.workflow, span, forecast_origin=origin, data=input_data
            )
            used = registered.model_type
            path = outdir / f"{target}__{used}.parquet"
            forecast.to_parquet(path)
            products.append(
                {
                    "span": span,
                    "target": target,
                    "model": used,
                    "model_version": registered.version,
                    "model_run_id": registered.run_id,
                }
            )
            print(
                f"forecast {day} {gate} {span} {target}: {used}, {len(forecast.data)} rows -> {path}"
            )
        if os.getenv("DELUKIT_WRITE_PLOTS") == "1":
            write_gate_plots(day, gate, span, root=run_dir)
    manifest = publish(day, gate, run_dir, products)
    print(f"published {day} {gate} -> {manifest}")
    return products


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Forecast one gate with active registered models."
    )
    parser.add_argument("--gate", choices=sorted(GATE_WALL), default=None)
    parser.add_argument(
        "--date", default=None, help="Berlin day YYYY-MM-DD (default: inferred)"
    )
    args = parser.parse_args()

    day, gate = (
        infer_gate()
        if args.gate is None
        else (
            date.fromisoformat(args.date) if args.date else infer_gate()[0],
            args.gate,
        )
    )
    run_gate(day, gate, TARGETS)


if __name__ == "__main__":
    main()
