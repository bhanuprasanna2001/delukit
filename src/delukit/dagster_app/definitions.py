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
  forecast_scores complete delivery-day errors of stored forecasts

Forecast partitions are (date x gate). Score partitions are completed Berlin
delivery days, independent of forecast partitions. Score files are written by
delivery day, so retries and parallel backfills do not append rows.

Checks: versioned_data_valid (blocking) replays the availability contract;
a forecast partition that fails its sanity check raises, which fails the
run and fires the failure sensor instead of publishing silently.

Schedules (Europe/Berlin; daemon included in `dagster dev`):
  source_refresh_schedule 05:00 + 11:00 + 15:00 -> raw/clean/versioned
  gate_schedule    05:30 + 11:30 daily -> forecast_d1 + forecast_d10
  scores_schedule  15:30 daily   -> yesterday's completed delivery day
  retrain_schedule Sunday 04:00  -> forced weekly retrain (all products)
  tune_schedule    1st of month  -> monthly Optuna tuning (all products)

Alerting: ops_failure_alert records failed runs and POSTs the configured
webhook. Completed evaluation runs POST a digest to the same webhook.

Run:
  mkdir -p data/.dagster && export DAGSTER_HOME=$PWD/data/.dagster
  dagster dev -m delukit.dagster_app.definitions   # UI + daemon + schedules
  python -m delukit.dagster_app.run forecast --date 2026-09-21 --gate 0530
"""

import hashlib
import json
import os
import urllib.request
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import dagster as dg
import pandas as pd
from dotenv import load_dotenv

BERLIN = ZoneInfo("Europe/Berlin")
load_dotenv()

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
score_partitions = dg.DailyPartitionsDefinition(
    start_date="2025-10-01", timezone="Europe/Berlin"
)

ALERTS_LOG = Path("data/ops/alerts.log")
SCORE_NOTIFICATIONS_LOG = Path("data/ops/score_notifications.jsonl")


def _partition_day_gate(partition_key: str) -> tuple[date, str]:
    """Split a 'date|gate' partition key (definition order, verified)."""
    day, _, gate = partition_key.partition("|")
    return date.fromisoformat(day), gate


REQUIRED_VERSIONED_PARTS = {
    "entsoe_actuals",
    "exaa",
    "sdac",
    "entsoe_day_ahead",
    "tso_day_ahead",
    "smard_actuals",
    "smard_day_ahead",
    "calendar",
    "weather",
}


def _require_prepared_snapshot(day: date, refresh_hour: int, cutoff: time) -> None:
    """Require a complete dataset build committed in the scheduled window."""
    from delukit.core.config import VERSIONED_DIR

    manifest = VERSIONED_DIR / "_READY.json"
    if not manifest.exists():
        raise RuntimeError("versioned snapshot has no validated commit marker")
    state = json.loads(manifest.read_text())
    start = datetime.combine(day, time(refresh_hour), BERLIN)
    end = datetime.combine(day, cutoff, BERLIN)
    committed = datetime.fromisoformat(state["committed_at"]).astimezone(BERLIN)
    if not start <= committed <= end:
        raise RuntimeError("versioned snapshot not committed in pre-run refresh window")
    paths = {path.stem: path for path in VERSIONED_DIR.glob("*.parquet")}
    if not REQUIRED_VERSIONED_PARTS.issubset(paths):
        missing = sorted(REQUIRED_VERSIONED_PARTS - paths.keys())
        raise RuntimeError(f"versioned snapshot incomplete: missing {missing}")
    changed = [
        name
        for name in sorted(REQUIRED_VERSIONED_PARTS)
        if state["parts"].get(name) != _file_identity(paths[name])
    ]
    if changed:
        raise RuntimeError(f"versioned snapshot changed after validation: {changed}")


def _file_identity(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _commit_snapshot(when: datetime | None = None) -> None:
    """Publish a readiness marker only after every part validates."""
    from delukit.core.config import VERSIONED_DIR

    paths = {path.stem: path for path in VERSIONED_DIR.glob("*.parquet")}
    if not REQUIRED_VERSIONED_PARTS.issubset(paths):
        raise RuntimeError("cannot commit incomplete versioned snapshot")
    state = {
        "committed_at": (when or datetime.now(BERLIN)).isoformat(),
        "parts": {
            name: _file_identity(paths[name])
            for name in sorted(REQUIRED_VERSIONED_PARTS)
        },
    }
    path = VERSIONED_DIR / "_READY.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n")
    tmp.replace(path)


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
    from delukit.dataset import build, load, validate

    build()
    if validate() != 0:
        raise RuntimeError("versioned dataset failed availability validation")
    _commit_snapshot()
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
    wall = time(5, 30) if gate == "0530" else time(11, 30)
    _require_prepared_snapshot(day, wall.hour, wall)
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
    partitions_def=score_partitions,
    deps=[versioned_data],
    retry_policy=dg.RetryPolicy(max_retries=2, delay=60),
    backfill_policy=dg.BackfillPolicy.multi_run(),
    description="Complete delivery-day scores using truth known by 15:30 the next day.",
)
def forecast_scores(context: dg.AssetExecutionContext) -> dg.MaterializeResult:
    from delukit.backtest import score_delivery_day
    from delukit.core.config.products import SCORES_DIR

    day = date.fromisoformat(context.partition_key)
    cutoff = datetime.combine(day + timedelta(days=1), time(15, 30), BERLIN)
    if datetime.now(BERLIN) < cutoff:
        raise RuntimeError(f"delivery day {day} is not ready for its 15:30 evaluation")
    _require_prepared_snapshot(day + timedelta(days=1), 15, time(15, 30))
    rows = score_delivery_day(day, cutoff)
    path = SCORES_DIR / "delivery" / f"{day.isoformat()}.parquet"
    send_score_digest(day, rows, path)
    complete = [r for r in rows if r["status"] == "complete"]
    mean_rmae = sum(r["rmae"] for r in complete) / len(complete) if complete else None
    return dg.MaterializeResult(
        metadata={
            "delivery_day": day.isoformat(),
            "complete": len(complete),
            "incomplete": len(rows) - len(complete),
            "mean_rmae": mean_rmae,
            "scores_path": str(path),
        }
    )


def score_digest(day: date, rows: list[dict], path: Path) -> str:
    """One operational Slack message for both gates and all lead days."""
    complete = [row for row in rows if row["status"] == "complete"]
    lines = [
        f"*delukit evaluation {day.isoformat()}*",
        f"Complete {len(complete)}/{len(rows)}; incomplete {len(rows) - len(complete)}",
    ]
    if rows:
        lines.append(f"Truth cutoff: {rows[0]['as_of']}")
    lines.append("*Day ahead by gate and target*")
    for row in rows:
        if row["span"] != "d1":
            continue
        label = f"{row['gate']} {row['target']}"
        if row["status"] == "complete":
            interval_coverage = 100 * (row["obs_p90"] - row["obs_p10"])
            lines.append(
                f"{label}: rMAE {row['rmae']:.3f}, rCRPS {row['rcrps']:.3f}, "
                f"P10-P90 coverage {interval_coverage:.1f}%"
            )
        else:
            lines.append(f"{label}: incomplete ({row['reason']})")
    lines.append("*10-day lead summary*")
    for lead in range(1, 11):
        group = [r for r in rows if r["span"] == "d10" and r["lead_day"] == lead]
        scored = [r for r in group if r["status"] == "complete"]
        if scored:
            mean_rmae = sum(r["rmae"] for r in scored) / len(scored)
            mean_rcrps = sum(r["rcrps"] for r in scored) / len(scored)
            mean_coverage = (
                100 * sum(r["obs_p90"] - r["obs_p10"] for r in scored) / len(scored)
            )
            lines.append(
                f"D+{lead}: {len(scored)}/{len(group)} complete, "
                f"rMAE {mean_rmae:.3f}, rCRPS {mean_rcrps:.3f}, "
                f"P10-P90 coverage {mean_coverage:.1f}%"
            )
        else:
            lines.append(f"D+{lead}: 0/{len(group)} complete")
    fallback = sum(r["model"] not in (None, "xgboost") for r in rows)
    lines.append(f"Fallback forecasts: {fallback}")
    lines.append(f"Full scores: `{path}`")
    return "\n".join(lines)


def send_score_digest(day: date, rows: list[dict], path: Path) -> bool:
    """POST changed digests; a crash after POST may send one duplicate."""
    text = score_digest(day, rows, path)
    digest = hashlib.sha256(text.encode()).hexdigest()
    key = f"{day.isoformat()}:{digest}"
    if SCORE_NOTIFICATIONS_LOG.exists():
        with SCORE_NOTIFICATIONS_LOG.open() as log:
            if any(json.loads(line).get("key") == key for line in log if line.strip()):
                return False
    webhook = os.getenv("DELUKIT_ALERT_WEBHOOK")
    if not webhook:
        return False
    request = urllib.request.Request(
        webhook,
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (OSError, ValueError):
        raise RuntimeError("evaluation webhook delivery failed") from None
    SCORE_NOTIFICATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SCORE_NOTIFICATIONS_LOG.open("a") as log:
        log.write(json.dumps({"key": key, "day": day.isoformat()}) + "\n")
    return True


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
    cron_schedule=["0 5 * * *", "0 11 * * *", "0 15 * * *"],
    execution_timezone="Europe/Berlin",
    target=dg.AssetSelection.assets(raw_data, clean_data, versioned_data),
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def source_refresh_schedule() -> list[dg.RunRequest]:
    """Refresh published inputs before gate and evaluation runs."""
    return [dg.RunRequest()]


@dg.schedule(
    cron_schedule=["30 5 * * *", "30 11 * * *"],
    execution_timezone="Europe/Berlin",
    target=dg.AssetSelection.assets(forecast_d1, forecast_d10),
    default_status=dg.DefaultScheduleStatus.RUNNING,
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
    target=dg.AssetSelection.assets(forecast_scores),
    default_status=dg.DefaultScheduleStatus.RUNNING,
)
def scores_schedule(context: dg.ScheduleEvaluationContext) -> list[dg.RunRequest]:
    """Refresh truth and evaluate yesterday's completed Berlin delivery day."""
    day = (
        context.scheduled_execution_time.astimezone(BERLIN) - timedelta(days=1)
    ).date()
    return [
        dg.RunRequest(
            partition_key=day.isoformat(), run_key=f"scores-{day.isoformat()}"
        )
    ]


@dg.schedule(
    cron_schedule="0 4 * * 0",
    execution_timezone="Europe/Berlin",
    target=retrain_job,
)
def retrain_schedule() -> list[dg.RunRequest]:
    """Sunday 04:00: force-retrain everything; the registry keeps the champion."""
    return [dg.RunRequest()]


@dg.schedule(
    cron_schedule="0 3 1 * *",
    execution_timezone="Europe/Berlin",
    target=tune_job,
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
            "step": getattr(event, "step_key", None) or "unknown",
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
                    f"• Step: `{record['step']}`\n"
                    "• Details: Dagster run logs"
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
        context.log.warning("alert sink failed: %s", type(exc).__name__)
        return dg.SkipReason(f"alert sink failed: {type(exc).__name__}")
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
    schedules=[
        source_refresh_schedule,
        gate_schedule,
        scores_schedule,
        retrain_schedule,
        tune_schedule,
    ],
    jobs=[retrain_job, tune_job],
    sensors=[ops_failure_alert],
)
