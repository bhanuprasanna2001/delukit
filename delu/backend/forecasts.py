import io
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

FORECASTS_DIR = Path(os.getenv("DELU_FORECASTS", "data/forecasts"))
ACTUALS_DIR = Path(os.getenv("DELU_ACTUALS", "data/clean"))

GATES = ("0530", "1130")
SPANS = ("d1", "d10")

# How much realised history to show alongside a forecast: one day for
# day-ahead, two days for the 10-day span.
LOOKBACK = {"d1": timedelta(days=1), "d10": timedelta(days=2)}

EXPORT_TIMEZONES = ("Europe/Berlin", "UTC")
EXPORT_FORMATS = ("csv", "parquet", "xlsx")
EXPORT_KINDS = ("point", "probabilistic")
MAX_EXPORT_DAYS = 75
EXPORT_COLS = {"p10": "quantile_P10", "p50": "quantile_P50", "p90": "quantile_P90"}

ENTSOE_TARGETS = ("price_sdac_seq1_eur_mwh", "load_actual_mw")
SMARD_TARGETS = (
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
)
# Mirrors delukit.core.config.products.GEN_TOTAL_COLUMNS: gen_actual_total_mwh
# is the sum of all SMARD generation types.
GEN_TOTAL_COLUMNS = (
    "gen_actual_biomass_mwh",
    "gen_actual_hydropower_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
    "gen_actual_other_renewable_mwh",
    "gen_actual_nuclear_mwh",
    "gen_actual_lignite_mwh",
    "gen_actual_hard_coal_mwh",
    "gen_actual_fossil_gas_mwh",
    "gen_actual_hydro_pumped_storage_mwh",
    "gen_actual_other_conventional_mwh",
)


class Missing(Exception):
    pass


def _actual_series(target: str) -> pd.Series | None:
    """Realised values for a target, quarter-hourly, UTC-indexed."""
    if not ACTUALS_DIR.is_dir():
        return None
    if target in ENTSOE_TARGETS:
        return pd.read_parquet(ACTUALS_DIR / "entsoe.parquet", columns=[target])[target]
    if target in SMARD_TARGETS:
        return pd.read_parquet(ACTUALS_DIR / "smard.parquet", columns=[target])[target]
    if target == "gen_actual_total_mwh":
        frame = pd.read_parquet(
            ACTUALS_DIR / "smard.parquet", columns=list(GEN_TOTAL_COLUMNS)
        )
        return frame.sum(axis=1, min_count=1)
    return None


def options() -> dict:
    if not FORECASTS_DIR.is_dir():
        return {"dates": [], "gates": list(GATES), "spans": list(SPANS), "targets": []}
    dates = sorted(p.name for p in FORECASTS_DIR.iterdir() if p.is_dir())
    targets: set[str] = set()
    runs: dict[str, dict[str, list[str]]] = {}
    for day in dates:
        for span in SPANS:
            gates = [g for g in GATES if (FORECASTS_DIR / day / f"{g}_{span}").is_dir()]
            if gates:
                runs.setdefault(day, {})[span] = gates
        for path in (FORECASTS_DIR / day).glob("*/*__*.parquet"):
            target, sep, _ = path.stem.rpartition("__")
            if sep and target:
                targets.add(target)
    return {
        "dates": dates,
        "gates": list(GATES),
        "spans": list(SPANS),
        "targets": sorted(targets),
        "runs": runs,
    }


def _newest(day: str, gate: str, span: str, target: str) -> Path:
    outdir = FORECASTS_DIR / day / f"{gate}_{span}"
    paths = list(outdir.glob(f"{target}__*.parquet"))
    if not paths:
        raise Missing(f"No {span} forecast for {target} on {day} at {gate}.")
    return max(paths, key=lambda p: p.stat().st_mtime)


def resolve(day: str | None, gate: str | None, span: str, target: str):
    opts = options()
    if not opts["dates"]:
        raise Missing("No forecasts published yet.")
    day = day or opts["dates"][-1]
    if span not in SPANS:
        raise Missing(f"Span must be one of {SPANS}.")
    present = [g for g in GATES if (FORECASTS_DIR / day / f"{g}_{span}").is_dir()]
    if not present:
        raise Missing(f"No {span} forecast for {day}.")
    gate = gate or ("1130" if "1130" in present else present[-1])
    if gate not in present:
        raise Missing(f"No {span} forecast for {day} at {gate}.")
    return day, gate


def download_files(days: int) -> list[tuple[Path, str]]:
    """Parquet files from the newest `days` run days, as (path, archive name)."""
    if not FORECASTS_DIR.is_dir():
        return []
    dates = sorted(p.name for p in FORECASTS_DIR.iterdir() if p.is_dir())[-days:]
    out: list[tuple[Path, str]] = []
    for day in dates:
        for sub in (FORECASTS_DIR / day).iterdir():
            if sub.is_dir():
                for f in sub.glob("*.parquet"):
                    out.append((f, f"{day}/{sub.name}/{f.name}"))
    return out


def _origin_moment(day: str, gate: str) -> datetime:
    hh, mm = int(gate[:2]), int(gate[2:])
    try:
        return datetime.strptime(day, "%Y-%m-%d").replace(
            hour=hh, minute=mm, tzinfo=ZoneInfo("Europe/Berlin")
        )
    except ValueError as exc:
        raise ValueError("Dates are YYYY-MM-DD.") from exc


def export_frame(
    start: str,
    end: str,
    target: str,
    gate: str,
    kind: str,
    tz: str,
    horizon_days: int,
) -> pd.DataFrame:
    """One tidy table of forecast runs: one overlapping series per origin day."""
    if gate not in GATES:
        raise ValueError(f"Run is one of {GATES}.")
    if kind not in EXPORT_KINDS:
        raise ValueError("Type is point or probabilistic.")
    if tz not in EXPORT_TIMEZONES:
        raise ValueError(f"Time zone is one of {EXPORT_TIMEZONES}.")
    if not 1 <= horizon_days <= 10:
        raise ValueError("Horizon is 1 to 10 days ahead.")
    try:
        s, e = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("Dates are YYYY-MM-DD.") from exc
    if e < s:
        raise ValueError("End is before start.")
    if (e - s).days > MAX_EXPORT_DAYS:
        raise ValueError(f"At most {MAX_EXPORT_DAYS} days between start and end.")
    opts = options()
    if target not in opts["targets"]:
        raise ValueError("Unknown forecast quantity.")
    days = [(s + timedelta(days=i)).isoformat() for i in range((e - s).days + 1)]
    if not any(day in opts["dates"] for day in days):
        raise Missing("No forecasts in that date range.")

    zone = ZoneInfo(tz)
    cols = ["p50"] if kind == "point" else ["p10", "p50", "p90"]
    span = "d1" if horizon_days <= 1 else "d10"
    parts = []
    for day in days:
        path = None
        candidates = ("d1", "d10") if span == "d1" else ("d10",)
        for sp in candidates:
            outdir = FORECASTS_DIR / day / f"{gate}_{sp}"
            files = list(outdir.glob(f"{target}__*.parquet")) if outdir.is_dir() else []
            if files:
                path = max(files, key=lambda p: p.stat().st_mtime)
                break
        if path is None:
            raise Missing(f"No {span} forecast for {target} on {day} at {gate}.")
        frame = pd.read_parquet(path)
        if target not in frame.columns:
            raise Missing(f"{target} is not in the {day} forecast file.")
        if not all(EXPORT_COLS[column] in frame.columns for column in cols):
            raise Missing(f"Requested quantiles are missing for {target} on {day}.")
        origin = _origin_moment(day, gate)
        delivery_day = origin.date() + timedelta(days=1)
        delivery_start = datetime.combine(delivery_day, time.min, origin.tzinfo)
        delivery_end = datetime.combine(
            delivery_day + timedelta(days=horizon_days), time.min, origin.tzinfo
        )
        hours = (frame.index - origin).total_seconds() / 3600.0
        keep = (frame.index >= delivery_start) & (frame.index < delivery_end)
        sub = frame[keep]
        expected = pd.date_range(
            delivery_start, delivery_end, freq="15min", inclusive="left"
        ).tz_convert("UTC")
        if not sub.index.equals(expected):
            raise Missing(
                f"Incomplete {horizon_days}-day forecast for {target} on {day} at {gate}."
            )
        if sub[[EXPORT_COLS[c] for c in cols]].isna().any().any():
            raise Missing(f"Missing forecast values for {target} on {day} at {gate}.")
        data: dict[str, list] = {
            "origin_date": [day] * len(sub),
            "origin_time": [f"{gate[:2]}:{gate[2:]}"] * len(sub),
            "target_time": [t.isoformat() for t in sub.index.tz_convert(zone)],
            "horizon_in_hours": [round(float(v), 2) for v in hours[keep]],
        }
        for c in cols:
            data[c] = [None if pd.isna(v) else float(v) for v in sub[EXPORT_COLS[c]]]
        parts.append(pd.DataFrame(data))
    if not parts:
        raise Missing("No forecasts in that date range.")
    return pd.concat(parts, ignore_index=True)


def export_file(
    start: str,
    end: str,
    target: str,
    gate: str,
    kind: str,
    tz: str,
    horizon_days: int,
    format: str,
) -> tuple[str, str, bytes]:
    if format not in EXPORT_FORMATS:
        raise ValueError(f"Format is one of {EXPORT_FORMATS}.")
    frame = export_frame(start, end, target, gate, kind, tz, horizon_days)
    stem = f"delu_{target}_{start}_{end}_{gate}_{kind}_h{horizon_days}d"
    buf = io.BytesIO()
    if format == "csv":
        frame.to_csv(buf, index=False)
        media = "text/csv"
    elif format == "parquet":
        frame.to_parquet(buf, index=False)
        media = "application/octet-stream"
    else:
        frame.to_excel(buf, index=False, sheet_name="forecasts")
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return f"{stem}.{format}", media, buf.getvalue()


def load(day: str, gate: str, span: str, target: str, kind: str) -> dict:
    day, gate = resolve(day, gate, span, target)
    path = _newest(day, gate, span, target)
    frame = pd.read_parquet(path)
    if target not in frame.columns:
        raise Missing(f"{target} is not in this forecast file.")
    model = path.stem.rpartition("__")[2]

    start = frame.index.min()
    end = frame.index.max()

    # Realised history: LOOKBACK before the gate, plus anything published
    # inside the horizon since the run (drawn over the forecast).
    actual = _actual_series(target)
    if actual is not None:
        actual = actual[
            (actual.index >= start - LOOKBACK[span]) & (actual.index <= end)
        ].dropna()
        idx = frame.index.union(actual.index)
        frame = frame.reindex(idx)
    else:
        idx = frame.index
        actual = pd.Series(dtype="float64").reindex(idx)

    def qt(c):
        return [None if pd.isna(v) else float(v) for v in frame[c]]

    def av(s):
        return [None if pd.isna(v) else float(v) for v in s]

    out = {
        "meta": {
            "date": day,
            "gate": gate,
            "span": span,
            "target": target,
            "model": model,
            "rows": len(idx),
            "generated_at": datetime.fromtimestamp(
                path.stat().st_mtime, UTC
            ).isoformat(),
        },
        "timestamps": [t.isoformat() for t in idx],
        "p50": qt("quantile_P50"),
        "p10": qt("quantile_P10") if kind == "probabilistic" else None,
        "p90": qt("quantile_P90") if kind == "probabilistic" else None,
        "actual": av(actual),
    }
    return out
