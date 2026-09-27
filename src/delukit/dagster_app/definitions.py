from datetime import UTC, date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import pandas as pd

BERLIN = ZoneInfo("Europe/Berlin")

gate_partitions = dg.MultiPartitionsDefinition(
    {
        "date": dg.DailyPartitionsDefinition(
            start_date="2025-10-01", end_offset=1, timezone="Europe/Berlin"
        ),
        "gate": dg.StaticPartitionsDefinition(["0530", "1130"]),
    }
)

ALERTS_LOG = Path("data/ops/alerts.log")


def _partition_day_gate(partition_key: str) -> tuple[date, str]:
    day, _, gate = partition_key.partition("|")
    return date.fromisoformat(day), gate


@dg.asset(description="Sync providers into data/raw (incremental by design).")
def raw_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.sources.sync import main

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
    description="Clean tables -> availability-stamped versioned parts.",
)
def versioned_data(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.data.dataset import build, load

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
    from delukit.data.dataset import validate

    passed = validate() == 0
    return dg.AssetCheckResult(
        passed=passed,
        severity=dg.AssetCheckSeverity.ERROR,
        metadata={"failures": 0 if passed else 1},
    )


def _forecast_partition(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.core.config.products import TARGETS
    from delukit.models.forecast import run_gate
    from delukit.ops.alerts import deliver_pending
    from delukit.ops.monitor import report_fallbacks

    day, gate = _partition_day_gate(context.partition_key)
    products = run_gate(day, gate, TARGETS, registry=True)
    report_fallbacks(day, gate, products)
    try:
        deliver_pending()
    except OSError as exc:
        context.log.warning("alert delivery failed: %s", exc)
    return dg.MaterializeResult(
        metadata={
            "day": day.isoformat(),
            "gate": gate,
            "products": len(products),
            "fallbacks": sum(item["model"] != "xgboost" for item in products),
        }
    )


@dg.asset(
    partitions_def=gate_partitions,
    deps=[versioned_data],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="Both spans and every target, published after full validation.",
)
def forecast_gate(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    return _forecast_partition(context)


@dg.asset(
    partitions_def=gate_partitions,
    deps=[forecast_gate],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="Daily errors of stored forecasts vs arrived actuals.",
)
def forecast_scores(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.evaluation.backtest import score_gate

    day, gate = _partition_day_gate(context.partition_key)
    rows = score_gate(day, gate)
    mean_rmae = sum(r["rmae"] for r in rows) / len(rows) if rows else float("nan")
    return dg.MaterializeResult(
        metadata={"product_lead_days_scored": len(rows), "mean_rmae": mean_rmae}
    )


@dg.op(description="Rescore the previous eleven issue days as actuals mature.")
def reconcile_scores(context: dg.OpExecutionContext) -> dict:
    from delukit.evaluation.backtest import score_recent
    from delukit.ops.alerts import deliver_pending, record
    from delukit.ops.monitor import score_drift

    day = datetime.now(BERLIN).date()
    rows = score_recent(day)
    for condition, active, message in score_drift():
        record(condition, active, message)
    try:
        deliver_pending()
    except OSError as exc:
        context.log.warning("alert delivery failed: %s", exc)
    context.log.info("reconciled %d complete lead-day scores", len(rows))
    return {"scores": len(rows)}


@dg.job(name="daily_score_reconciliation")
def reconcile_job() -> None:
    reconcile_scores()


@dg.schedule(
    cron_schedule=["30 5 * * *", "30 11 * * *"],
    execution_timezone="Europe/Berlin",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    target=dg.AssetSelection.assets(forecast_gate).upstream(),
)
def gate_schedule(context: dg.ScheduleEvaluationContext) -> list[dg.RunRequest]:
    tick = context.scheduled_execution_time.astimezone(BERLIN)
    gate = "0530" if tick.hour == 5 else "1130"
    key = f"{tick.date().isoformat()}|{gate}"
    return [dg.RunRequest(partition_key=key)]


@dg.schedule(
    cron_schedule="30 15 * * *",
    execution_timezone="Europe/Berlin",
    default_status=dg.DefaultScheduleStatus.RUNNING,
    target=reconcile_job,
)
def scores_schedule() -> dg.RunRequest:
    return dg.RunRequest()


@dg.run_status_sensor(
    run_status=dg.DagsterRunStatus.FAILURE,
    default_status=dg.DefaultSensorStatus.RUNNING,
)
def ops_failure_alert(context: dg.RunStatusSensorContext) -> dg.SkipReason:
    from delukit.ops.alerts import deliver_pending, record

    try:
        event = getattr(context, "dagster_event", None)
        name = context.dagster_run.job_name
        run_id = context.dagster_run.run_id
        message = str(getattr(event, "message", "") or "")[:500]
        record(f"run/{run_id}", True, f"{name}: {message}", log_path=ALERTS_LOG)
        deliver_pending()
    except Exception as exc:
        context.log.exception("alert sink failed: %s", exc)
        return dg.SkipReason(f"alert sink failed: {exc}")
    context.log.error("run failed: %s (%s)", name, run_id)
    return dg.SkipReason("alert recorded")


@dg.sensor(minimum_interval_seconds=900, default_status=dg.DefaultSensorStatus.RUNNING)
def gate_health(context: dg.SensorEvaluationContext) -> dg.SkipReason:
    from delukit.ops.alerts import deliver_pending
    from delukit.ops.monitor import check_gates

    try:
        changed = check_gates(datetime.now(UTC))
        deliver_pending()
    except Exception as exc:
        context.log.exception("gate health check failed: %s", exc)
        return dg.SkipReason(f"gate health check failed: {exc}")
    return dg.SkipReason(f"{changed} gate alert transitions")


defs = dg.Definitions(
    assets=[
        raw_data,
        clean_data,
        versioned_data,
        forecast_gate,
        forecast_scores,
    ],
    asset_checks=[versioned_data_valid],
    schedules=[gate_schedule, scores_schedule],
    jobs=[reconcile_job],
    sensors=[ops_failure_alert, gate_health],
)
