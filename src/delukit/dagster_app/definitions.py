"""Dagster assets, checks, schedules and sensors for delukit.

Assets are thin: each one calls the existing delukit modules and records
what it did as materialization metadata. Files under data/ stay the system
of record (assets return metadata, not dataframes); the MLflow registry
hands models from training to prediction across processes.

Assets (upstream -> downstream):
  raw_data        sync providers into data/raw (delukit.main, incremental)
  clean_data      raw -> data/clean/*.parquet (per-source builders)
  versioned_data  clean -> data/versioned/*.parquet (point-in-time parts)
  forecast_d1     one gate run, day-ahead span (run_gate, fallback inside)
  forecast_d10    one gate run, 10-day span (same)
  forecast_scores daily errors of stored forecasts vs arrived actuals

Partitions are (date x gate): one partition is exactly one gate run, so a
backfill over a date range replays history gate by gate. Dagster caps
multi-partitions at two dimensions, hence separate d1/d10 assets sharing
one partitions definition. Everything written is idempotent (tmp+replace,
date-scoped paths, deduplicated scores), so retries and backfills are safe.

Checks: versioned_data_valid (blocking) replays the availability contract;
a forecast partition that fails its sanity check raises, which fails the
run and fires the failure sensor instead of publishing silently.

Schedules (Europe/Berlin; daemon included in `dagster dev`):
  gate_schedule    05:30 + 11:30 daily -> forecast_d1 + forecast_d10
  scores_schedule  15:30 daily   -> forecast_scores for completed gates
  retrain_schedule Sunday 04:00  -> forced weekly retrain (all products)
  tune_schedule    1st of month  -> monthly Optuna tuning (all products)

Alerting (no services needed): ops_failure_alert fires on any failed run,
appends JSON to data/ops/alerts.log and POSTs DELUKIT_ALERT_WEBHOOK when set.

Run:
  mkdir -p data/.dagster && export DAGSTER_HOME=$PWD/data/.dagster
  dagster dev -m delukit.dagster_app.definitions   # UI + daemon + schedules
  python -m delukit.dagster_app.run forecast --date 2026-09-21 --gate 0530
"""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import pandas as pd

BERLIN = ZoneInfo("Europe/Berlin")

# Static date keys, not time-window partitions: time windows exclude the
# incomplete current day, but gates run intraday for today. Extend the end
# date when it approaches; partitions are cheap (limit is 100k).
_gate_dates = pd.date_range("2025-10-01", "2027-12-31", freq="D").strftime("%Y-%m-%d")
gate_partitions = dg.MultiPartitionsDefinition(
    {
        "date": dg.StaticPartitionsDefinition(list(_gate_dates)),
        "gate": dg.StaticPartitionsDefinition(["0530", "1130"]),
    }
)

ALERTS_LOG = Path("data/ops/alerts.log")


def _partition_day_gate(partition_key: str) -> tuple[date, str]:
    """Split a 'date|gate' partition key (definition order, verified)."""
    day, _, gate = partition_key.partition("|")
    return date.fromisoformat(day), gate


@dg.asset(description="Sync providers into data/raw (incremental by design).")
def raw_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.main import main

    main()
    return dg.MaterializeResult(metadata={"synced": True})


@dg.asset(
    deps=[raw_data],
    description="Raw daily files -> data/clean/*.parquet.",
)
def clean_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.sources import calendar, entsoe, smard, weather

    counts = {}
    for name, module in (
        ("entsoe", entsoe),
        ("smard", smard),
        ("weather", weather),
        ("calendar", calendar),
    ):
        path = module.to_clean()
        counts[name] = len(pd.read_parquet(path))
    return dg.MaterializeResult(
        metadata={f"{name}_rows": n for name, n in counts.items()}
    )


@dg.asset(
    deps=[clean_data],
    description="Clean tables -> versioned point-in-time parts.",
)
def versioned_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.dataset import build, load

    build()
    parts = load()
    return dg.MaterializeResult(
        metadata={
            "parts": len(parts.data_parts),
            "features": len(parts.feature_names),
            "rows": sum(len(p.data) for p in parts.data_parts),
        }
    )


@dg.asset_check(asset=versioned_data, blocking=True)
def versioned_data_valid() -> dg.AssetCheckResult:
    """Replay the availability contract; block forecasts on bad data."""
    from delukit.dataset import validate

    passed = validate() == 0
    return dg.AssetCheckResult(
        passed=passed,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"failures": 0 if passed else 1},
    )


def _expected_rows(day: date, span: str) -> int:
    """Quarters in the Berlin days covered by the span (DST-aware)."""
    last = day + timedelta(days=1 if span == "d1" else 10)
    start = datetime.combine(day + timedelta(days=1), datetime.min.time(), BERLIN)
    end = datetime.combine(last + timedelta(days=1), datetime.min.time(), BERLIN)
    utc = ZoneInfo("UTC")
    return int((end.astimezone(utc) - start.astimezone(utc)).total_seconds() // 900)


def _check_forecast_files(day: date, gate: str, span: str) -> tuple[bool, dict]:
    """Every target file present, right row count, ordered quantiles."""
    from delukit.core.config.products import FORECAST_DIR, TARGETS

    expected = _expected_rows(day, span)
    problems = []
    rows = 0
    for target in TARGETS:
        paths = list(
            (FORECAST_DIR / day.isoformat() / f"{gate}_{span}").glob(
                f"{target}__*.parquet"
            )
        )
        if not paths:
            problems.append(f"missing {target}")
            continue
        frame = pd.read_parquet(max(paths, key=lambda p: p.stat().st_mtime))
        rows += len(frame)
        if len(frame) != expected:
            problems.append(f"{target}: {len(frame)} rows, want {expected}")
        qs = [c for c in frame.columns if c.startswith("quantile_P")]
        try:
            from openstef_core.types import Q

            qs = sorted(qs, key=Q.parse)
        except ValueError:
            pass
        ordered = all(
            (frame[qs[i]] <= frame[qs[i + 1]]).all() for i in range(len(qs) - 1)
        )
        if not ordered:
            problems.append(f"{target}: quantiles unordered")
    return not problems, {"rows": rows, "problems": "; ".join(problems)}


def _forecast_partition(
    context: dg.AssetExecutionContext, span: str
) -> dg.MaterializeResult:
    from delukit.core.config.products import TARGETS
    from delukit.forecast import run_gate

    day, gate = _partition_day_gate(context.partition_key)
    run_gate(day, gate, span, TARGETS, registry=True)
    passed, meta = _check_forecast_files(day, gate, span)
    if not passed:
        raise RuntimeError(
            f"forecast sanity failed for {day} {gate} {span}: {meta['problems']}"
        )
    return dg.MaterializeResult(metadata={"day": day.isoformat(), "gate": gate, **meta})


@dg.asset(
    partitions_def=gate_partitions,
    deps=[versioned_data],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="One gate run, day-ahead span (registry models, fallback inside).",
)
def forecast_d1(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    return _forecast_partition(context, "d1")


@dg.asset(
    partitions_def=gate_partitions,
    deps=[versioned_data],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="One gate run, 10-day span (registry models, fallback inside).",
)
def forecast_d10(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    return _forecast_partition(context, "d10")


@dg.asset(
    partitions_def=gate_partitions,
    deps=[forecast_d1, forecast_d10],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="Daily errors of stored forecasts vs arrived actuals.",
)
def forecast_scores(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.backtest import score_gate

    day, gate = _partition_day_gate(context.partition_key)
    rows = score_gate(day, gate)
    mean_rmae = sum(r["rmae"] for r in rows) / len(rows) if rows else float("nan")
    return dg.MaterializeResult(
        metadata={"products_scored": len(rows), "mean_rmae": mean_rmae}
    )


@dg.op(description="Retrain every product into the registry (promotion is automatic).")
def retrain_products(context: dg.OpExecutionContext) -> dict:
    from delukit.core.config.products import SPANS, TARGETS
    from delukit.forecast import GATE_WALL, fit_product

    fitted, skipped, failed = 0, 0, []
    for target in TARGETS:
        for gate in sorted(GATE_WALL):
            for span in SPANS:
                name = f"{target} {gate} {span}"
                try:
                    # Forced: reuse would otherwise skip every recent model
                    # and the "weekly retrain" would retrain nothing.
                    workflow = fit_product(
                        target, gate, span, registry=True, force_retrain=True
                    )
                except Exception as exc:  # noqa: BLE001 - one bad product must not stop the other 23
                    failed.append(f"{name}: {type(exc).__name__}: {exc}")
                    context.log.warning("retrain failed for %s: %s", name, exc)
                    continue
                if workflow is None:
                    skipped += 1
                else:
                    fitted += 1
    context.log.info("retrained %d products (%d skipped)", fitted, skipped)
    if failed:
        # Fail the run so the failure sensor alerts; already-fitted models
        # stay saved, so a retry only re-attempts the missing ones.
        raise RuntimeError(f"retrain failed for {len(failed)} products: {failed}")
    return {"fitted": fitted, "skipped": skipped}


@dg.op(description="Monthly Optuna tuning for every product (defaults: 10 trials).")
def tune_products(context: dg.OpExecutionContext) -> dict:
    from delukit.core.config.products import SPANS, TARGETS
    from delukit.tune import tune_product

    tuned = [
        str(tune_product(t, g, s))
        for t in TARGETS
        for g in ("0530", "1130")
        for s in SPANS
    ]
    return {"tuned": len(tuned)}


@dg.job(name="weekly_retrain")
def retrain_job() -> None:
    retrain_products()


@dg.job(name="monthly_tune")
def tune_job() -> None:
    tune_products()


@dg.schedule(
    cron_schedule=["30 5 * * *", "30 11 * * *"],
    execution_timezone="Europe/Berlin",
    # upstream() pulls raw -> clean -> versioned into the same run:
    # target=[forecasts] alone runs forecast-only on stale versioned data.
    target=dg.AssetSelection.assets(forecast_d1, forecast_d10).upstream(),
)
def gate_schedule(context: dg.ScheduleEvaluationContext) -> list[dg.RunRequest]:
    """Fire both spans for the gate whose wall-clock hour just ticked."""
    tick = context.scheduled_execution_time.astimezone(BERLIN)
    gate = "0530" if tick.hour == 5 else "1130"
    key = f"{tick.date().isoformat()}|{gate}"
    return [dg.RunRequest(partition_key=key)]


@dg.schedule(
    cron_schedule="30 15 * * *",
    execution_timezone="Europe/Berlin",
    target=[forecast_scores],
)
def scores_schedule(context: dg.ScheduleEvaluationContext) -> list[dg.RunRequest]:
    """Score yesterday's completed gates (actuals have arrived by 15:30)."""
    day = (
        context.scheduled_execution_time.astimezone(BERLIN) - timedelta(days=1)
    ).date()
    return [
        dg.RunRequest(
            partition_key=f"{day.isoformat()}|{gate}",
            run_key=f"scores-{day.isoformat()}-{gate}",
        )
        for gate in ("0530", "1130")
    ]


@dg.schedule(
    cron_schedule="0 4 * * 0", execution_timezone="Europe/Berlin", target=retrain_job
)
def retrain_schedule() -> list[dg.RunRequest]:
    """Sunday 04:00: force-retrain everything; the registry keeps the champion."""
    return [dg.RunRequest()]


@dg.schedule(
    cron_schedule="0 3 1 * *", execution_timezone="Europe/Berlin", target=tune_job
)
def tune_schedule() -> list[dg.RunRequest]:
    """1st of month 03:00: re-tune every product, then re-backtest to judge."""
    return [dg.RunRequest()]


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def ops_failure_alert(context: dg.RunStatusSensorContext) -> dg.SkipReason:
    """Any failed run -> local alert log + optional webhook. Never raises."""
    import urllib.request

    try:
        event = getattr(context, "dagster_event", None)
        record = {
            "time": datetime.now(BERLIN).isoformat(),
            "job": context.dagster_run.job_name,
            "run_id": context.dagster_run.run_id,
            "error": str(getattr(event, "message", "") or "")[:500],
        }
        ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ALERTS_LOG.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        webhook = os.getenv("DELUKIT_ALERT_WEBHOOK")
        if webhook:
            slack_payload = {
                "text": (
                    f"*delukit run failed*\n"
                    f"• Job: `{record['job']}`\n"
                    f"• Run: `{record['run_id']}`\n"
                    f"• Time: {record['time']}\n"
                    f"• Error: {record['error']}"
                )
            }
            urllib.request.urlopen(
                urllib.request.Request(
                    webhook,
                    data=json.dumps(slack_payload).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=10,
            )
    except Exception as exc:  # noqa: BLE001 - alerting must never break the sensor
        context.log.warning("alert sink failed: %s", exc)
        return dg.SkipReason(f"alert sink failed: {exc}")
    context.log.error("run failed: %s (%s)", record["job"], record["run_id"])
    return dg.SkipReason("alert recorded")


defs = dg.Definitions(
    assets=[
        raw_data,
        clean_data,
        versioned_data,
        forecast_d1,
        forecast_d10,
        forecast_scores,
    ],
    asset_checks=[versioned_data_valid],
    schedules=[gate_schedule, scores_schedule, retrain_schedule, tune_schedule],
    jobs=[retrain_job, tune_job],
    sensors=[ops_failure_alert],
)
