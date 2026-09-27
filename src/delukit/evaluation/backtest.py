import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
from openstef_beam.backtesting import BacktestConfig, BacktestPipeline
from openstef_beam.backtesting.backtest_forecaster import BacktestForecasterConfig
from openstef_beam.benchmarking.baselines.openstef4 import OpenSTEF4BacktestForecaster
from openstef_beam.evaluation import EvaluationConfig, EvaluationPipeline, Window
from openstef_beam.evaluation.metric_providers import (
    ObservedProbabilityProvider,
    RCRPSProvider,
    RelativePinballLossProvider,
    RMAEProvider,
)
from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset
from openstef_core.types import LeadTime, Q

from delukit.core.clean import BERLIN
from delukit.core.config.products import (
    BACKTEST_DIR,
    GATE_0530,
    PREDICT_CONTEXT,
    PREDICT_LENGTH,
    QUANTILES,
    SPAN_D1,
    SPANS,
    TRAIN_INTERVAL,
    TRAINING_DAYS,
    TUNING_DIR,
)
from delukit.data.dataset import load, require_datetime_index
from delukit.models.forecast import GATE_WALL, create_workflow, workflow_config

ALL_HISTORY = timedelta(days=365 * 30)

PREDICT_MIN_LENGTH = timedelta(minutes=15)
COVERAGE = 0.5
SCORE_LOOKBACK_DAYS = 11
EVAL_WINDOW = Window(lag=timedelta(hours=0), size=timedelta(days=21))
BAND_FLOOR = {
    GATE_0530: timedelta(hours=18, minutes=30),
    "1130": timedelta(hours=12, minutes=30),
}


def split_target(
    ds: VersionedTimeSeriesDataset, target: str
) -> tuple[VersionedTimeSeriesDataset, VersionedTimeSeriesDataset]:
    target_part = next(p for p in ds.data_parts if target in p.feature_names)
    ground_truth = VersionedTimeSeriesDataset([target_part.select_features([target])])
    predictors = VersionedTimeSeriesDataset(
        [
            p.select_features([c for c in p.feature_names if c != target])
            if target in p.feature_names
            else p
            for p in ds.data_parts
        ]
    )
    return ground_truth, predictors


def run_backtest(
    target: str,
    gate: str,
    span: str,
    start: datetime,
    end: datetime,
    *,
    train_interval: timedelta = TRAIN_INTERVAL,
    training_days: int | None = TRAINING_DAYS,
    tuned: bool = False,
) -> TimeSeriesDataset:
    ds = load()
    ground_truth, predictors = split_target(ds, target)

    config = workflow_config(target, gate, span, use_tuned=False)
    candidate_path = TUNING_DIR / "candidates" / f"{target}__{gate}__{span}.json"
    if tuned:
        from openstef_models.models.forecasting.xgboost_forecaster import (
            XGBoostHyperParams,
        )

        config.xgboost_hyperparams = XGBoostHyperParams.model_validate_json(
            candidate_path.read_text()
        )
        print(
            f"backtest {target} {gate} {span}: tuned hyperparams from {candidate_path}"
        )

    forecaster = OpenSTEF4BacktestForecaster(
        config=BacktestForecasterConfig(
            requires_training=True,
            predict_length=PREDICT_LENGTH[span],
            predict_min_length=PREDICT_MIN_LENGTH,
            predict_context_length=PREDICT_CONTEXT,
            predict_context_min_coverage=COVERAGE,
            training_context_length=timedelta(days=training_days)
            if training_days is not None
            else ALL_HISTORY,
            training_context_min_coverage=COVERAGE,
        ),
        workflow_template=create_workflow(target, gate, span, config=config),
        cache_dir=BACKTEST_DIR / f"{target}__{gate}__{span}" / "cache",
    )
    wall = GATE_WALL[gate]
    pipeline = BacktestPipeline(
        config=BacktestConfig(
            predict_interval=timedelta(days=1),
            train_interval=train_interval,
            align_time=time(wall.hour, wall.minute),
        ),
        forecaster=forecaster,
    )
    predictions = pipeline.run(
        ground_truth=ground_truth, predictors=predictors, start=start, end=end
    )
    outdir = BACKTEST_DIR / f"{target}__{gate}__{span}"
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / "predictions.parquet"
    tmp = path.with_suffix(".tmp")
    predictions.to_parquet(tmp)
    tmp.replace(path)
    print(
        f"backtest {target} {gate} {span}: {len(predictions.data)} prediction rows -> {path}"
    )
    return predictions


def split_bands(
    predictions: TimeSeriesDataset, gate: str
) -> dict[str, TimeSeriesDataset]:
    frame = predictions.data
    available_at = frame["available_at"]
    if not isinstance(available_at, pd.Series):
        raise TypeError("Expected one available_at column.")
    gate_day = available_at.dt.tz_convert(BERLIN).dt.date
    index = require_datetime_index(frame.index)
    target_day = index.to_series().dt.tz_convert(BERLIN).dt.date
    one = pd.Timedelta(days=1)
    bands: dict[str, TimeSeriesDataset] = {}
    for k in range(1, 11):
        mask = target_day == gate_day + k * one
        if bool(mask.any()):
            selected = frame.loc[mask]
            if not isinstance(selected, pd.DataFrame):
                raise TypeError("Expected a dataframe after selecting forecast rows.")
            bands[f"d{k}"] = TimeSeriesDataset(
                selected, sample_interval=predictions.sample_interval
            )
    return bands


def evaluate(
    target: str,
    gate: str,
    span: str,
    predictions: TimeSeriesDataset,
    ground_truth: VersionedTimeSeriesDataset,
) -> dict[str, object]:
    from openstef_beam.analysis.plots import (
        ForecastTimeSeriesPlotter,
        QuantileProbabilityPlotter,
        WindowedMetricPlotter,
    )

    outdir = BACKTEST_DIR / f"{target}__{gate}__{span}"
    pipeline = EvaluationPipeline(
        config=EvaluationConfig(
            available_ats=[],
            lead_times=[LeadTime(BAND_FLOOR[gate])],
            windows=[EVAL_WINDOW],
        ),
        quantiles=QUANTILES,
        window_metric_providers=[RMAEProvider(quantiles=[Q(0.5)]), RCRPSProvider()],
        global_metric_providers=[
            RMAEProvider(quantiles=[Q(0.5)]),
            RCRPSProvider(),
            RelativePinballLossProvider(),
        ],
    )
    summaries = {}
    bands = split_bands(predictions, gate)
    wanted = ("d1",) if span == SPAN_D1 else tuple(f"d{k}" for k in range(1, 11))
    for band in wanted:
        preds = bands.get(band)
        if preds is None or preds.data.empty:
            print(f"evaluate {target} {gate} {band}: no predictions, skipped")
            continue
        report = pipeline.run(
            predictions=preds, ground_truth=ground_truth, target_column=target
        )
        if not report.subset_reports:
            print(f"evaluate {target} {gate} {band}: no overlapping data, skipped")
            continue
        subset = report.subset_reports[0]
        print(f"evaluate {target} {gate} {band}: filtering {subset.filtering}")
        metric_frames = []
        for metric in subset.metrics:
            frame = metric.to_dataframe()
            print(frame.to_string(index=False))
            frame = frame.assign(
                quantile=frame["quantile"].astype(str),
                window=str(metric.window),
                timestamp=metric.timestamp,
            )
            metric_frames.append(frame)
            if metric.window == "global":
                summaries[band] = frame
        pd.concat(metric_frames).to_parquet(outdir / f"metrics_{band}.parquet")
        subset.subset.data.to_parquet(outdir / f"subset_{band}.parquet")

        subset_data = subset.subset
        name = f"{target} {gate} {band}"
        measurements = subset_data.target_series
        if measurements is None:
            raise ValueError(f"No measurements available for {name}.")
        ForecastTimeSeriesPlotter().add_measurements(
            measurements=measurements
        ).add_model(
            model_name=name,
            forecast=subset_data.median_series,
            quantiles=subset_data.quantiles_data,
        ).plot(title=name).write_html(outdir / f"timeseries_{band}.html")

        observed = summaries[band].dropna(subset=["observed_probability"])
        if not observed.empty:
            QuantileProbabilityPlotter().add_model(
                model_name=name,
                forecasted_probs=observed["quantile"].tolist(),
                observed_probs=observed["observed_probability"].tolist(),
            ).plot(title=f"{name} calibration").write_html(
                outdir / f"calibration_{band}.html"
            )

        rmae_windows = [
            m
            for m in subset.metrics
            if m.window != "global" and "rMAE" in m.to_dataframe().columns
        ]
        if rmae_windows:
            plotter = WindowedMetricPlotter().set_window_size("21 days")
            values = []
            for m in rmae_windows:
                frame = m.to_dataframe().set_index(
                    m.to_dataframe()["quantile"].astype(str)
                )
                values.append(frame.loc["0.5", "rMAE"])
            plotter.add_model(
                model_name=name,
                timestamps=[m.timestamp for m in rmae_windows],
                metric_values=values,
            ).plot(title=f"{name} rMAE", metric_name="rMAE").write_html(
                outdir / f"windowed_{band}.html"
            )
        print(f"plots -> {outdir}")
    return summaries


def default_window(target: str, span: str) -> tuple[datetime, datetime]:
    ds = load()
    part = next(p for p in ds.data_parts if target in p.feature_names)
    stamps = require_datetime_index(part.data[target].dropna().index).tz_convert(BERLIN)
    lookahead = 2 if span == SPAN_D1 else 11
    last_stamp = stamps.max()
    if not isinstance(last_stamp, pd.Timestamp):
        raise ValueError(f"No measurements available for {target}.")
    end = (last_stamp.to_pydatetime() - timedelta(days=lookahead)).date()
    start = end - timedelta(days=42)
    berlin_start = datetime.combine(start, datetime.min.time(), BERLIN)
    berlin_end = datetime.combine(end, datetime.min.time(), BERLIN)
    return berlin_start, berlin_end


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Backtest one product, evaluate bands, plot."
    )
    parser.add_argument("--target", default="load_actual_mw")
    parser.add_argument("--gate", choices=sorted(GATE_WALL), default=GATE_0530)
    parser.add_argument("--span", choices=list(SPANS), default=SPAN_D1)
    parser.add_argument("--start", default=None, help="Berlin day YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Berlin day YYYY-MM-DD")
    parser.add_argument("--train-interval-days", type=int, default=7)
    parser.add_argument(
        "--training-days",
        type=int,
        default=None,
        help="bound the refit window (default: all history, like production)",
    )
    parser.add_argument(
        "--from-predictions",
        action="store_true",
        help="skip refit, reuse saved predictions",
    )
    parser.add_argument(
        "--tuned", action="store_true", help="use data/tuning hyperparams"
    )
    args = parser.parse_args()

    berlin = BERLIN
    if args.start and args.end:
        start = datetime.combine(
            date.fromisoformat(args.start), datetime.min.time(), berlin
        )
        end = datetime.combine(
            date.fromisoformat(args.end), datetime.min.time(), berlin
        )
    else:
        start, end = default_window(args.target, args.span)
    outdir = BACKTEST_DIR / f"{args.target}__{args.gate}__{args.span}"
    pred_path = outdir / "predictions.parquet"

    if args.from_predictions:
        predictions = TimeSeriesDataset.read_parquet(
            pred_path, sample_interval=timedelta(minutes=15)
        )
    else:
        predictions = run_backtest(
            args.target,
            args.gate,
            args.span,
            start,
            end,
            train_interval=timedelta(days=args.train_interval_days),
            training_days=args.training_days,
            tuned=args.tuned,
        )
    ground_truth, _ = split_target(load(), args.target)
    evaluate(args.target, args.gate, args.span, predictions, ground_truth)


def score_gate(day: date, gate: str, *, save: bool = True, ds=None) -> list[dict]:
    from openstef_core.datasets import ForecastDataset

    from delukit.core.config.products import FORECAST_DIR, SPANS
    from delukit.data.dataset import QUARTER
    from delukit.ops.publication import expected_index, published_products

    ds = ds or load()
    manifest = FORECAST_DIR / day.isoformat() / f"{gate}.json"
    versions = {}
    if manifest.is_file():
        for item in json.loads(manifest.read_text())["products"]:
            versions[(item["span"], item["target"])] = item.get("model_version")
    rows = []
    for span in SPANS:
        for target, used, path in published_products(day, gate, span):
            frame = pd.read_parquet(path)
            quantile_cols = sorted(
                (c for c in frame.columns if c.startswith("quantile_P")),
                key=lambda name: int(name.removeprefix("quantile_P")),
            )
            try:
                part = next(p for p in ds.data_parts if target in p.feature_names)
            except StopIteration:
                continue
            truth = part.select_version().data[[target]].dropna()
            for lead_day in range(1, 2 if span == "d1" else 11):
                delivery_day = day + timedelta(days=lead_day)
                expected = expected_index(day + timedelta(days=lead_day - 1), "d1")
                actual = truth[target]
                if not isinstance(actual, pd.Series):
                    raise TypeError(f"Expected one measurements column for {target}.")
                actual = actual.reindex(expected)
                if actual.isna().any() or len(
                    frame.index.intersection(expected)
                ) != len(expected):
                    continue
                joined = (
                    frame.loc[expected, quantile_cols]
                    .join(actual.rename(target))
                    .dropna()
                )
                if len(joined) != len(expected):
                    continue
                subset = ForecastDataset(
                    joined, sample_interval=QUARTER, target_column=target
                )

                def _pick(out: dict, key: str, name: str) -> float:
                    return float(next(v[name] for k, v in out.items() if str(k) == key))

                rmae = _pick(RMAEProvider(quantiles=[Q(0.5)])(subset), "0.5", "rMAE")
                rcrps = _pick(RCRPSProvider()(subset), "global", "rCRPS")
                observed = {
                    str(k): v["observed_probability"]
                    for k, v in ObservedProbabilityProvider()(subset).items()
                }
                truth_json = actual.to_json(date_format="iso")
                if truth_json is None:
                    raise ValueError("Could not serialize measurements for scoring.")
                truth_hash = hashlib.sha256(truth_json.encode()).hexdigest()
                row = {
                    "day": day.isoformat(),
                    "gate": gate,
                    "span": span,
                    "target": target,
                    "model": used,
                    "model_version": versions.get((span, target)),
                    "lead_day": lead_day,
                    "delivery_day": delivery_day.isoformat(),
                    "expected_n": len(expected),
                    "n": len(joined),
                    "quantiles": ",".join(quantile_cols),
                    "quantile_count": len(quantile_cols),
                    "forecast_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "truth_sha256": truth_hash,
                    "evaluated_at": datetime.now(UTC).isoformat(),
                    "rmae": float(rmae),
                    "rcrps": float(rcrps),
                }
                row.update(
                    {
                        f"obs_p{percent}": float(
                            observed.get(f"{percent / 100:.1f}", float("nan"))
                        )
                        for percent in range(10, 100, 10)
                    }
                )
                rows.append(row)
    if save:
        save_scores(rows)
    print(f"scores {day} {gate}: {len(rows)} product-lead days scored")
    return rows


def save_scores(rows: list[dict]) -> None:
    if not rows:
        return
    from delukit.core.config.products import SCORES_DIR

    SCORES_DIR.mkdir(parents=True, exist_ok=True)
    path = SCORES_DIR / "scores_v2.parquet"
    table = pd.DataFrame(rows)
    if path.exists():
        table = pd.concat([pd.read_parquet(path), table], ignore_index=True)
    table = table.drop_duplicates(
        subset=[
            "day",
            "gate",
            "span",
            "target",
            "lead_day",
            "forecast_sha256",
            "truth_sha256",
        ],
        keep="first",
    ).sort_values(["day", "gate", "span", "target", "lead_day", "evaluated_at"])
    temporary = path.with_suffix(".tmp")
    table.to_parquet(temporary, index=False)
    temporary.replace(path)


def score_recent(as_of: date) -> list[dict]:
    ds = load()
    rows = []
    for age in range(1, SCORE_LOOKBACK_DAYS + 1):
        day = as_of - timedelta(days=age)
        for gate in GATE_WALL:
            rows.extend(score_gate(day, gate, save=False, ds=ds))
    save_scores(rows)
    return rows


if __name__ == "__main__":
    main()
