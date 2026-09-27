from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from delukit.core.config.products import FORECAST_DIR, SCORES_DIR, SPANS
from delukit.ops.alerts import record
from delukit.ops.publication import published_products

BERLIN = ZoneInfo("Europe/Berlin")
GATES = {"0530": time(5, 30), "1130": time(11, 30)}


@dataclass(frozen=True)
class DailyScoreReport:
    scored: int
    pending_mature: int
    message: str


def daily_score_report(as_of: date, rows: list[dict]) -> DailyScoreReport:
    from delukit.evaluation.backtest import SCORE_LOOKBACK_DAYS

    scored = {
        (r["day"], r["gate"], r["span"], r["target"], r["lead_day"]) for r in rows
    }
    mature = set()
    for age in range(1, SCORE_LOOKBACK_DAYS + 1):
        day = as_of - timedelta(days=age)
        for gate in GATES:
            for span in SPANS:
                lead_days = min(age - 1, 1 if span == "d1" else 10)
                for target, _, _ in published_products(day, gate, span):
                    mature.update(
                        (day.isoformat(), gate, span, target, lead_day)
                        for lead_day in range(1, lead_days + 1)
                    )
    pending = sorted(mature - scored)
    lines = [
        f"{as_of} forecast scores: {len(scored)} complete product/lead days; "
        f"{len(pending)} past delivery days await complete actuals."
    ]
    latest = {}
    for row in rows:
        if row["gate"] == "1130" and row["span"] == "d1":
            target = row["target"]
            if target not in latest or row["day"] > latest[target]["day"]:
                latest[target] = row
    for target, row in sorted(latest.items()):
        version = row.get("model_version")
        used = f" v{version}" if version is not None else ""
        lines.append(
            f"{target} ({row['day']}{used}): "
            f"rMAE {row['rmae']:.3f}, rCRPS {row['rcrps']:.3f}"
        )
    if pending:
        preview = ", ".join(
            f"{day} {gate} {span} {target} D+{lead}"
            for day, gate, span, target, lead in pending[:3]
        )
        lines.append(f"Oldest pending: {preview}")
    return DailyScoreReport(
        scored=len(scored), pending_mature=len(pending), message="\n".join(lines)
    )


def check_gates(now: datetime, *, grace: timedelta = timedelta(minutes=90)) -> int:
    local = now.astimezone(BERLIN)
    changed = 0
    for day in (local.date() - timedelta(days=1), local.date()):
        for gate, wall in GATES.items():
            deadline = datetime.combine(day, wall, BERLIN) + grace
            if local < deadline:
                continue
            manifest = FORECAST_DIR / day.isoformat() / f"{gate}.json"
            active = not manifest.is_file()
            changed += record(
                f"gate/{day}/{gate}",
                active,
                f"{day} {gate} has no validated publication after {deadline.isoformat()}"
                if active
                else f"{day} {gate} publication is available",
            )
    return changed


def score_drift(
    path: Path | None = None, *, ratio: float = 1.5
) -> list[tuple[str, bool, str]]:
    source = path or SCORES_DIR / "scores_v2.parquet"
    if not source.is_file():
        return []
    table = pd.read_parquet(source)
    identity = ["day", "gate", "span", "target", "lead_day"]
    latest = table.sort_values("evaluated_at").drop_duplicates(identity, keep="last")
    events = []
    for key, group in latest.groupby(["gate", "span", "target", "lead_day"]):
        if not isinstance(key, tuple) or len(key) != 4:
            raise ValueError(f"Unexpected score identity: {key!r}")
        gate, span, target, lead_day = key
        if not (
            isinstance(gate, str)
            and isinstance(span, str)
            and isinstance(target, str)
            and isinstance(lead_day, int)
        ):
            raise TypeError(f"Unexpected score identity values: {key!r}")
        values = group.sort_values("day")["rmae"].dropna()
        if len(values) < 17:
            continue
        baseline = float(values.iloc[-17:-3].median())
        recent = float(values.iloc[-3:].median())
        if baseline <= 0:
            continue
        condition = f"score-drift/{gate}/{span}/{target}/d{lead_day}"
        active = recent > baseline * ratio
        message = (
            f"mature rMAE median {recent:.3f} over 3 origins; "
            f"prior 14 origins {baseline:.3f}; threshold {ratio:.2f}x"
        )
        events.append((condition, active, message))
    return events


def report_fallbacks(day: date, gate: str, products: list[dict]) -> int:
    changed = 0
    for item in products:
        condition = f"fallback/{gate}/{item['span']}/{item['target']}"
        active = item["model"] != "xgboost"
        changed += record(
            condition,
            active,
            f"{day} {gate} {item['span']} {item['target']} used {item['model']}",
        )
    return changed
