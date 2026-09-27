from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from delukit.core.config.products import FORECAST_DIR, SCORES_DIR
from delukit.ops.alerts import record

BERLIN = ZoneInfo("Europe/Berlin")
GATES = {"0530": time(5, 30), "1130": time(11, 30)}


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
