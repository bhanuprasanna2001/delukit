"""Product workflows: build, fit, predict with fallback.

One workflow per (target x gate) from the openstef preset. Reliability
comes from the preset's own checks (FlatlineChecker, CompletenessChecker)
plus a fallback chain: on data-driven failures the run degrades through
constant_quantile -> median -> flatliner instead of emitting nothing.
"""

from datetime import date, datetime, timedelta
from datetime import time as dtime
from zoneinfo import ZoneInfo

import pandas as pd
from openstef_beam.evaluation.metric_providers import (
    ObservedProbabilityProvider,
    R2Provider,
    RCRPSProvider,
)
from openstef_core.datasets import ForecastDataset
from openstef_core.exceptions import (
    FlatlinerDetectedError,
    InsufficientlyCompleteError,
    ModelNotFoundError,
    PredictError,
)
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
    SPANS,
    TARGETS,
    TUNING_DIR,
    energy_price_column,
    feature_exclude,
    mlflow_storage,
    model_id,
    weather_ref,
)
from delukit.dataset import load

GATE_WALL = {f"{wall:%H%M}": wall for wall in GATES}
PRIMARY_MODEL = "xgboost"
# constant_quantile first: it needs only 3% target history, no lag pipeline.
FALLBACK_MODELS = ("constant_quantile", "median", "flatliner")


def gate_datetime(day: date, gate: str) -> pd.Timestamp:
    """Gate moment in UTC for a Berlin day."""
    return pd.Timestamp(datetime.combine(day, GATE_WALL[gate], BERLIN)).tz_convert(UTC)


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
    """Preset config for one (target x gate x span) product."""
    config = ForecastingWorkflowConfig(
        model_id=model_id(target, gate, span),
        model=model,  # ty: ignore[invalid-argument-type]
        model_reuse_enable=model_reuse_enable,
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
        # ponytail: silent fallback to preset defaults; a missing/corrupt
        # tuning file must never fail a gate run.
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
    """Preset assembly plus real thread count (used by the tuner per trial)."""
    from openstef_models.transforms.postprocessing import (
        IsotonicQuantileCalibrator,
        QuantileSorter,
    )

    workflow = create_forecasting_workflow(config)
    forecaster = workflow.model.forecaster
    if hasattr(forecaster, "n_jobs") and forecaster.n_jobs != N_JOBS:
        forecaster.n_jobs = N_JOBS
        # The preset hardcodes n_jobs=1; rebuild the booster with real threads.
        forecaster.model_post_init(None)
    if calibrate and CALIBRATE_QUANTILES:
        # Per the probabilistic-forecasting guide: isotonic mapping fitted
        # on train predictions during fit. The per-quantile maps can cross
        # where the raw model is flat (e.g. PV at night), so sort last to
        # restore the P10 <= P50 <= P90 invariant.
        workflow.model.postprocessing.transforms.append(
            IsotonicQuantileCalibrator(
                quantiles=list(config.quantiles), use_local_quantile_estimation=True
            )
        )
        workflow.model.postprocessing.transforms.append(QuantileSorter())
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
    """Assemble one product workflow; XGBoost gets real thread count."""
    # Only the primary forecaster is calibrated: fallback outputs are
    # constant by design, and calibrating them adds failure modes for nothing.
    calibrate = model == PRIMARY_MODEL
    config = config or workflow_config(
        target, gate, span, model=model, registry=registry, use_tuned=use_tuned
    )
    if force_retrain:
        # Scheduled retraining must actually fit: ignore the 7-day reuse rule.
        # Gate runs keep the default (reuse recent models, predict fast).
        config.model_reuse_enable = False
    return create_workflow_from_config(config, calibrate=calibrate)


def fit_product(
    target: str,
    gate: str,
    span: str,
    *,
    model: str = PRIMARY_MODEL,
    train_days: int | None = None,
    registry: bool = False,
    force_retrain: bool = False,
) -> CustomForecastingWorkflow | None:
    """Fit on all history as known now. None when the registry skips.

    force_retrain disables model reuse so the fit really runs (weekly
    retrain); gate runs leave it off to reuse recent models.
    """
    now = datetime.now(UTC)
    ds = load()
    if train_days is not None:
        ds = ds.filter_by_range(now - timedelta(days=train_days), now)
    data = ds.filter_by_available_before(now).select_version()
    workflow = create_workflow(
        target, gate, span, model=model, registry=registry, force_retrain=force_retrain
    )
    workflow.fit(data)
    return workflow if workflow.model.is_fitted else None


def slice_span(forecast: ForecastDataset, day: date, span: str) -> ForecastDataset:
    """Cut the raw gate forecast to the product span (D+1 / D+1..D+10)."""
    berlin_days = forecast.data.index.tz_convert(BERLIN).date
    last = day + timedelta(days=1 if span == SPAN_D1 else 10)
    keep = (berlin_days >= day + timedelta(days=1)) & (berlin_days <= last)
    return ForecastDataset(
        forecast.data[keep],
        sample_interval=forecast.sample_interval,
        forecast_start=forecast.forecast_start,
        target_column=forecast.target_column,
    )


def predict_product(
    workflow: CustomForecastingWorkflow, target: str, gate: str, span: str, day: date
) -> ForecastDataset:
    """Forecast the span from the gate using only data known at the gate."""
    gate_dt = gate_datetime(day, gate)
    data = (
        load()
        .filter_by_range(gate_dt - PREDICT_CONTEXT, gate_dt + PREDICT_LENGTH[span])
        .filter_by_available_before(gate_dt)
        .select_version()
    )
    return slice_span(workflow.predict(data, forecast_start=gate_dt), day, span)


def predict_with_fallback(
    target: str,
    gate: str,
    span: str,
    day: date,
    *,
    registry: bool = False,
    models: tuple[str, ...] = (PRIMARY_MODEL, *FALLBACK_MODELS),
) -> tuple[ForecastDataset, str]:
    """Fit primary, predict; degrade through the fallback chain on failure.

    The winning model is returned alongside the forecast and encoded in the
    output filename: downstream must treat non-primary models (especially
    flatliner) as degraded output, not business as usual.
    """
    tried = []
    for model in models:
        try:
            workflow = fit_product(
                target,
                gate,
                span,
                model=model,
                registry=registry and model == PRIMARY_MODEL,
            )
            if workflow is None:  # registry skipped the re-fit; load the stored model
                workflow = create_workflow(target, gate, span, registry=True)
            return predict_product(workflow, target, gate, span, day), model
        except (
            FlatlinerDetectedError,
            InsufficientlyCompleteError,
            PredictError,
            ModelNotFoundError,
        ) as e:
            tried.append(f"{model} ({type(e).__name__})")
    raise PredictError(f"all models failed for {target} {gate} {span} {day}: {tried}")


def infer_gate(now: datetime | None = None) -> tuple[date, str]:
    """Most recent gate at `now` (Berlin)."""
    berlin = (now or datetime.now(UTC)).astimezone(ZoneInfo("Europe/Berlin"))
    if berlin.time() >= dtime(11, 30):
        return berlin.date(), GATE_1130
    if berlin.time() >= dtime(5, 30):
        return berlin.date(), GATE_0530
    return berlin.date() - timedelta(days=1), GATE_1130


def write_gate_plots(day: date, gate: str, span: str | None = None) -> None:
    """Model-band plots next to the forecast parquets (no truth needed)."""
    from openstef_beam.analysis.plots import ForecastTimeSeriesPlotter

    spans = (span,) if span is not None else SPANS
    for s in spans:
        outdir = FORECAST_DIR / day.isoformat() / f"{gate}_{s}"
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
            name = f"{target} {day} {gate} {s} [{used}]"
            ForecastTimeSeriesPlotter().add_model(
                model_name=name,
                forecast=frame[median],
                quantiles=frame[quantiles],
            ).plot(title=name).write_html(outdir / f"{target}__{used}.html")
            print(f"plot {day} {gate} {s} {target} -> {target}__{used}.html")


def run_gate(
    day: date, gate: str, span: str, targets: tuple[str, ...], *, registry: bool
) -> None:
    """Fit + predict every target at the gate; write data/forecasts/<day>/<gate>_<span>/."""
    outdir = FORECAST_DIR / day.isoformat() / f"{gate}_{span}"
    outdir.mkdir(parents=True, exist_ok=True)
    for target in targets:
        forecast, used = predict_with_fallback(
            target, gate, span, day, registry=registry
        )
        for stale in outdir.glob(f"{target}__*.parquet"):
            if stale.name != f"{target}__{used}.parquet":
                stale.unlink()
        path = outdir / f"{target}__{used}.parquet"
        tmp = path.with_suffix(".tmp")
        forecast.to_parquet(tmp)
        tmp.replace(path)
        print(
            f"forecast {day} {gate} {span} {target}: {used}, {len(forecast.data)} rows -> {path}"
        )
    write_gate_plots(day, gate, span)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Forecast one gate (fit + predict + fallback)."
    )
    parser.add_argument("--gate", choices=sorted(GATE_WALL), default=None)
    parser.add_argument("--span", choices=list(SPANS), default=SPAN_D1)
    parser.add_argument(
        "--date", default=None, help="Berlin day YYYY-MM-DD (default: inferred)"
    )
    parser.add_argument("--targets", default=",".join(TARGETS))
    parser.add_argument(
        "--no-registry", action="store_true", help="skip the MLflow model registry"
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
    run_gate(
        day,
        gate,
        args.span,
        tuple(args.targets.split(",")),
        registry=not args.no_registry,
    )


if __name__ == "__main__":
    main()
