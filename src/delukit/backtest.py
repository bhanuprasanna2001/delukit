"""Backtest per (target x gate x span): replay, evaluate, plot.

One BacktestPipeline per gate (predict events at the gate, daily) with a
shared weekly retrain schedule. Evaluation scores one band per lead day
(d1..d10) by Berlin target day: per-day buckets are required because the
evaluation keeps only the freshest forecast per timestamp.
"""

from datetime import date, datetime, time, timedelta

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
from delukit.dataset import load
from delukit.forecast import GATE_WALL, create_workflow, workflow_config

# Unbounded training for the event generator (timedelta-only field): clamped
# to the data start inside BacktestEventGenerator, i.e. all history.
ALL_HISTORY = timedelta(days=365 * 30)

# Shortest forecast the event generator still schedules (gates near `end`
# emit partial predictions; missing truth simply drops out of the join).
PREDICT_MIN_LENGTH = timedelta(minutes=15)
# Minimum fraction of expected quarters in the train/predict context windows.
COVERAGE = 0.5
# Rolling window for the windowed metrics (plus one global metric per band).
EVAL_WINDOW = Window(lag=timedelta(hours=0), size=timedelta(days=21))
# Shortest lead per gate: every row of every band satisfies it by construction.
BAND_FLOOR = {
    GATE_0530: timedelta(hours=18, minutes=30),
    "1130": timedelta(hours=12, minutes=30),
}


def split_target(
    ds: VersionedTimeSeriesDataset, target: str
) -> tuple[VersionedTimeSeriesDataset, VersionedTimeSeriesDataset]:
    """Ground truth (target column only) + predictors (everything else)."""
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
    """Replay the gate daily; return predictions with available_at = gate.

    Each weekly refit trains on all history (like production fits); pass
    training_days to bound the window for experiments.
    """
    ds = load()
    ground_truth, predictors = split_target(ds, target)

    config = workflow_config(target, gate, span, use_tuned=tuned)
    if tuned and (TUNING_DIR / f"{target}__{gate}__{span}.json").exists():
        print(
            f"backtest {target} {gate} {span}: tuned hyperparams from "
            f"{TUNING_DIR / f'{target}__{gate}__{span}.json'}"
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
    # Naive wall time + Berlin-aware start aligns events to the gate daily.
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
    """One band per lead day: rows whose Berlin target day is gate_day + k.

    Per-day buckets are required because EvaluationPipeline.select_version()
    dedups each timestamp to a single forecast: a multi-day band would
    silently re-score the day-ahead version of every timestamp instead of
    the 2-10-day-ahead skill it claims to measure. Bucketing first makes
    every timestamp unique per band, so the dedup is a no-op.
    """
    frame = predictions.data
    gate_day = frame["available_at"].dt.tz_convert(BERLIN).dt.date
    target_day = pd.Series(frame.index.tz_convert(BERLIN), index=frame.index).dt.date
    one = pd.Timedelta(days=1)
    bands = {}
    for k in range(1, 11):
        mask = target_day == gate_day + k * one
        if mask.any():
            bands[f"d{k}"] = TimeSeriesDataset(
                frame[mask], sample_interval=predictions.sample_interval
            )
    return bands


def evaluate(
    target: str,
    gate: str,
    span: str,
    predictions: TimeSeriesDataset,
    ground_truth: VersionedTimeSeriesDataset,
) -> dict[str, object]:
    """Evaluate each band; save reports + plots; return global metric frames."""
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
    # The d1 workflow only owns its band; the d10 workflow owns d1..d10, so
    # its d1 band measures exactly what separate models would buy us.
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
        # Plain-frame persistence: EvaluationReport.read_parquet cannot reload
        # subsets with a non-default target column (upstream from_pandas gap).
        pd.concat(metric_frames).to_parquet(outdir / f"metrics_{band}.parquet")
        subset.subset.data.to_parquet(outdir / f"subset_{band}.parquet")

        subset_data = subset.subset
        name = f"{target} {gate} {band}"
        ForecastTimeSeriesPlotter().add_measurements(
            measurements=subset_data.target_series
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
    """Last 6 weeks with target truth (predictions need truth through the span)."""
    ds = load()
    part = next(p for p in ds.data_parts if target in p.feature_names)
    stamps = part.data[target].dropna().index.tz_convert(BERLIN)
    lookahead = 2 if span == SPAN_D1 else 11
    end = (stamps.max() - pd.Timedelta(days=lookahead)).date()
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


def score_gate(day: date, gate: str) -> list[dict]:
    """Score stored gate forecasts against arrived actuals; append to scores.

    Reads data/forecasts/<day>/<gate>_<span>/*.parquet, joins each target
    with ground truth, and appends one row per (span, target) to the running
    data/scores/scores.parquet table (deduplicated, so re-runs are safe).
    Rows whose target days are not yet complete simply have no truth to join
    and are skipped.
    """
    from openstef_core.datasets import ForecastDataset

    from delukit.core.config.products import FORECAST_DIR, SCORES_DIR, SPANS
    from delukit.dataset import QUARTER

    ds = load()
    rows = []
    for span in SPANS:
        outdir = FORECAST_DIR / day.isoformat() / f"{gate}_{span}"
        if not outdir.is_dir():
            continue
        # One file per (target x model); re-runs with a different fallback
        # leave stale files behind, so score only the newest per target.
        newest = {}
        for path in sorted(outdir.glob("*__*.parquet")):
            target, sep, _ = path.stem.rpartition("__")
            if not sep or not target:
                continue
            cur = newest.get(target)
            if cur is None or path.stat().st_mtime > cur.stat().st_mtime:
                newest[target] = path
        for target, path in sorted(newest.items()):
            _, _, used = path.stem.rpartition("__")
            frame = pd.read_parquet(path)
            quantile_cols = [c for c in frame.columns if "quantile_" in c]
            try:
                part = next(p for p in ds.data_parts if target in p.feature_names)
            except StopIteration:
                continue
            truth = part.select_version().data[[target]].dropna()
            joined = frame[quantile_cols].join(truth, how="inner").dropna()
            if joined.empty:
                continue
            subset = ForecastDataset(
                joined, sample_interval=QUARTER, target_column=target
            )

            def _pick(out: dict, key: str, name: str) -> float:
                # Providers return {quantile: {metric: value}} keyed by
                # Quantile objects (repr "0.5") or "global".
                return float(next(v[name] for k, v in out.items() if str(k) == key))

            rmae = _pick(RMAEProvider(quantiles=[Q(0.5)])(subset), "0.5", "rMAE")
            rcrps = _pick(RCRPSProvider()(subset), "global", "rCRPS")
            observed = {
                str(k): v["observed_probability"]
                for k, v in ObservedProbabilityProvider()(subset).items()
            }
            rows.append(
                {
                    "day": day.isoformat(),
                    "gate": gate,
                    "span": span,
                    "target": target,
                    "model": used,
                    "n": len(joined),
                    "rmae": float(rmae),
                    "rcrps": float(rcrps),
                    "obs_p10": float(observed.get("0.1", float("nan"))),
                    "obs_p50": float(observed.get("0.5", float("nan"))),
                    "obs_p90": float(observed.get("0.9", float("nan"))),
                }
            )
    if rows:
        SCORES_DIR.mkdir(parents=True, exist_ok=True)
        table_path = SCORES_DIR / "scores.parquet"
        table = pd.concat(
            [
                pd.read_parquet(table_path)
                if table_path.exists()
                else pd.DataFrame(rows).iloc[0:0],
                pd.DataFrame(rows),
            ]
        )
        table = table.drop_duplicates(
            subset=["day", "gate", "span", "target"], keep="last"
        ).sort_values(["day", "gate", "span", "target"])
        tmp = table_path.with_suffix(".tmp")
        table.to_parquet(tmp)
        tmp.replace(table_path)
    print(f"scores {day} {gate}: {len(rows)} products scored")
    return rows


if __name__ == "__main__":
    main()
