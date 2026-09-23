"""Backtest per (target x gate x span): replay, evaluate, plot.

One BacktestPipeline per gate (predict events at the gate, daily) with a
shared weekly retrain schedule. Evaluation scores one band per lead day
(d1..d10) by Berlin target day: per-day buckets are required because the
evaluation keeps only the freshest forecast per timestamp.

Strict replay requires reconstructed source vintages. The dataset guard
rejects windows whose historical information set cannot be reproduced.
"""

import uuid
from datetime import date, datetime, time, timedelta
from math import isfinite

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

from delukit.core.clean import BERLIN, UTC, day_bounds, quarter_grid
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
    from delukit.dataset import assert_replayable

    assert_replayable(start, end)
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


def score_delivery_day(delivery_day: date, as_of: datetime) -> list[dict]:
    """Score complete Berlin delivery days using only truth available by as_of.

    One row represents one target, gate, span and lead day. Incomplete inputs
    produce a status row without metrics. Each delivery day has its own atomic
    output file, so retries cannot append duplicate rows or rewrite an original
    evaluation after later source revisions. Truth uses the latest observed
    revision at first evaluation. Old 15:30 truth vintages are not reconstructed.
    """
    from openstef_core.datasets import ForecastDataset

    from delukit.core.config.products import FORECAST_DIR, SCORES_DIR, TARGETS
    from delukit.dataset import QUARTER

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = pd.Timestamp(as_of).tz_convert(UTC)
    if cutoff > pd.Timestamp(datetime.now(UTC)):
        raise ValueError("evaluation cutoff has not occurred")
    _, delivery_end, _ = day_bounds(delivery_day)
    if cutoff < delivery_end:
        raise ValueError("delivery day has not ended at evaluation cutoff")
    score_dir = SCORES_DIR / "delivery"
    score_path = score_dir / f"{delivery_day.isoformat()}.parquet"
    if score_path.exists():
        saved = pd.read_parquet(score_path)
        if (
            not saved.empty
            and saved["as_of"].nunique() == 1
            and saved["as_of"].iloc[0] == cutoff.isoformat()
        ):
            return [
                {key: None if pd.isna(value) else value for key, value in row.items()}
                for row in saved.to_dict(orient="records")
            ]
        raise ValueError(
            f"existing score has a different evaluation cutoff: {score_path}"
        )
    grid = quarter_grid(delivery_day)
    quantiles = ["quantile_P10", "quantile_P50", "quantile_P90"]
    ds = load()
    parts = {
        target: next((p for p in ds.data_parts if target in p.feature_names), None)
        for target in TARGETS
    }
    rows = []
    for gate in ("0530", "1130"):
        for span, leads in (("d1", (1,)), ("d10", range(1, 11))):
            for lead in leads:
                origin_day = delivery_day - timedelta(days=lead)
                outdir = FORECAST_DIR / origin_day.isoformat() / f"{gate}_{span}"
                for target in TARGETS:
                    paths = list(outdir.glob(f"{target}__*.parquet"))
                    path = (
                        max(paths, key=lambda p: p.stat().st_mtime) if paths else None
                    )
                    row = {
                        "delivery_day": delivery_day.isoformat(),
                        "origin_day": origin_day.isoformat(),
                        "gate": gate,
                        "span": span,
                        "lead_day": lead,
                        "target": target,
                        "model": path.stem.rpartition("__")[2] if path else None,
                        "as_of": cutoff.isoformat(),
                        "truth_basis": "latest_observed_vintage_at_evaluation",
                        "status": "incomplete",
                        "reason": None,
                        "expected_n": len(grid),
                        "forecast_n": 0,
                        "truth_n": 0,
                        "n": 0,
                        "rmae": None,
                        "rcrps": None,
                        "obs_p10": None,
                        "obs_p50": None,
                        "obs_p90": None,
                    }
                    if path is None:
                        row["reason"] = "forecast_missing"
                        rows.append(row)
                        continue
                    frame = pd.read_parquet(path)
                    delivery_frame = frame[frame.index.isin(grid)].sort_index()
                    row["forecast_n"] = len(delivery_frame)
                    if not delivery_frame.index.equals(grid) or not set(
                        quantiles
                    ).issubset(delivery_frame.columns):
                        row["reason"] = "forecast_grid_or_schema"
                        rows.append(row)
                        continue
                    if delivery_frame[quantiles].isna().any().any():
                        row["reason"] = "forecast_values_missing"
                        rows.append(row)
                        continue
                    part = parts[target]
                    if part is None:
                        row["reason"] = "truth_source_missing"
                        rows.append(row)
                        continue
                    versions = part.data.loc[
                        part.data.index.isin(grid), [target, "available_at"]
                    ]
                    versions = versions[versions["available_at"] <= cutoff]
                    versions = versions.sort_values("available_at")
                    versions = versions[~versions.index.duplicated(keep="last")]
                    truth = versions[target].reindex(grid)
                    row["truth_n"] = int(truth.notna().sum())
                    row["n"] = row["truth_n"]
                    if row["truth_n"] != len(grid):
                        row["reason"] = "truth_unavailable_at_cutoff"
                        rows.append(row)
                        continue
                    joined = delivery_frame[quantiles].assign(**{target: truth})
                    subset = ForecastDataset(
                        joined, sample_interval=QUARTER, target_column=target
                    )

                    def pick(out: dict, key: str, name: str) -> float:
                        return float(
                            next(v[name] for k, v in out.items() if str(k) == key)
                        )

                    row["rmae"] = pick(
                        RMAEProvider(quantiles=[Q(0.5)])(subset), "0.5", "rMAE"
                    )
                    row["rcrps"] = pick(RCRPSProvider()(subset), "global", "rCRPS")
                    observed = {
                        str(k): v["observed_probability"]
                        for k, v in ObservedProbabilityProvider()(subset).items()
                    }
                    for quantile, column in (
                        ("0.1", "obs_p10"),
                        ("0.5", "obs_p50"),
                        ("0.9", "obs_p90"),
                    ):
                        row[column] = float(observed[quantile])
                    if not all(
                        isfinite(row[key])
                        for key in ("rmae", "rcrps", "obs_p10", "obs_p50", "obs_p90")
                    ):
                        row.update(
                            status="incomplete",
                            reason="metrics_unavailable",
                            rmae=None,
                            rcrps=None,
                            obs_p10=None,
                            obs_p50=None,
                            obs_p90=None,
                        )
                    else:
                        row["status"] = "complete"
                    rows.append(row)
    score_dir.mkdir(parents=True, exist_ok=True)
    tmp = score_path.with_name(f".{score_path.stem}.{uuid.uuid4().hex}.tmp")
    pd.DataFrame(rows).to_parquet(tmp, index=False)
    tmp.replace(score_path)
    complete = sum(row["status"] == "complete" for row in rows)
    print(f"scores {delivery_day}: {complete}/{len(rows)} complete")
    return rows


if __name__ == "__main__":
    main()
