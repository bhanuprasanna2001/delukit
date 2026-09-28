import io
import json
import os
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

FORECASTS_DIR = Path(os.getenv("DELU_FORECASTS", "data/forecasts"))
ACTUALS_DIR = Path(os.getenv("DELU_ACTUALS", "data/clean"))

GATES = ("0530", "1130")
SPANS = ("d1", "d10")

LOOKBACK = {"d1": timedelta(days=1), "d10": timedelta(days=2)}

EXPORT_TIMEZONES = ("Europe/Berlin", "UTC")
EXPORT_FORMATS = ("csv", "parquet", "xlsx")
EXPORT_KINDS = ("point", "probabilistic")
MAX_EXPORT_DAYS = 75
PERCENTILES = tuple(range(10, 100, 10))
EXPORT_COLS = {f"p{level}": f"quantile_P{level}" for level in PERCENTILES}

ENTSOE_TARGETS = ("price_sdac_seq1_eur_mwh", "load_actual_mw")
SMARD_TARGETS = (
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
)
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


def _datetime_index(index: pd.Index) -> pd.DatetimeIndex:
    if not isinstance(index, pd.DatetimeIndex):
        raise ValueError("Forecast data must use a timestamp index.")
    return index


def _series_column(frame: pd.DataFrame, column: str) -> pd.Series:
    values = frame[column]
    if not isinstance(values, pd.Series):
        raise ValueError(f"Expected one column named {column}.")
    return values


def _published(day: str, gate: str, span: str) -> dict[str, Path] | None:
    day_dir = FORECASTS_DIR / day
    manifest = day_dir / f"{gate}.json"
    if not manifest.is_file():
        return None
    body = json.loads(manifest.read_text())
    if body["schema"] != 1 or body["day"] != day or body["gate"] != gate:
        raise Missing(f"Invalid publication for {day} at {gate}.")
    return {
        item["target"]: day_dir / item["path"]
        for item in body["products"]
        if item["span"] == span
    }


def _available_targets(day: str, gate: str, span: str) -> list[str]:
    published = _published(day, gate, span)
    if published is not None:
        return sorted(target for target, path in published.items() if path.is_file())
    return sorted(
        {
            path.stem.rpartition("__")[0]
            for path in (FORECASTS_DIR / day / f"{gate}_{span}").glob("*__*.parquet")
        }
    )


def _actual_series(target: str) -> pd.Series | None:
    if not ACTUALS_DIR.is_dir():
        return None
    if target in ENTSOE_TARGETS:
        frame = pd.read_parquet(ACTUALS_DIR / "entsoe.parquet", columns=[target])
        return _series_column(frame, target)
    if target in SMARD_TARGETS:
        frame = pd.read_parquet(ACTUALS_DIR / "smard.parquet", columns=[target])
        return _series_column(frame, target)
    if target == "gen_actual_total_mwh":
        frame = pd.read_parquet(
            ACTUALS_DIR / "smard.parquet", columns=list(GEN_TOTAL_COLUMNS)
        )
        return frame.sum(axis=1, min_count=1)
    return None


def options() -> dict:
    if not FORECASTS_DIR.is_dir():
        return {
            "dates": [],
            "gates": list(GATES),
            "spans": list(SPANS),
            "targets": [],
            "runs": {},
            "products": {},
        }
    targets: set[str] = set()
    runs: dict[str, dict[str, list[str]]] = {}
    products: dict[str, dict[str, dict[str, list[str]]]] = {}
    for day_dir in sorted(FORECASTS_DIR.iterdir()):
        if not day_dir.is_dir() or len(day_dir.name) != 10 or day_dir.name[4:5] != "-":
            continue
        day = day_dir.name
        for gate in GATES:
            for span in SPANS:
                available = _available_targets(day, gate, span)
                if available:
                    products.setdefault(day, {}).setdefault(gate, {})[span] = available
                    runs.setdefault(day, {}).setdefault(span, []).append(gate)
                    targets.update(available)
    return {
        "dates": sorted(products),
        "gates": list(GATES),
        "spans": list(SPANS),
        "targets": sorted(targets),
        "runs": runs,
        "products": products,
    }


def _newest(day: str, gate: str, span: str, target: str) -> Path:
    published = _published(day, gate, span)
    if published is not None:
        path = published.get(target)
        if path is None or not path.is_file():
            raise Missing(f"No {span} forecast for {target} on {day} at {gate}.")
        return path
    outdir = FORECASTS_DIR / day / f"{gate}_{span}"
    paths = list(outdir.glob(f"{target}__*.parquet"))
    if not paths:
        raise Missing(f"No {span} forecast for {target} on {day} at {gate}.")
    return max(paths, key=lambda p: p.stat().st_mtime)


def resolve(day: str | None, gate: str | None, span: str, target: str):
    opts = options()
    if not opts["dates"]:
        raise Missing("No forecasts published yet.")
    if span not in SPANS:
        raise Missing(f"Span must be one of {SPANS}.")
    if day is None:
        day = next(
            (
                candidate
                for candidate in reversed(opts["dates"])
                if any(
                    target
                    in opts["products"][candidate].get(candidate_gate, {}).get(span, [])
                    for candidate_gate in ((gate,) if gate else GATES)
                )
            ),
            None,
        )
        if day is None:
            raise Missing(f"No {span} forecast for {target}.")
    present = [
        candidate_gate
        for candidate_gate in GATES
        if target in opts["products"].get(day, {}).get(candidate_gate, {}).get(span, [])
    ]
    if not present:
        raise Missing(f"No {span} forecast for {target} on {day}.")
    gate = gate or ("1130" if "1130" in present else present[-1])
    if gate not in present:
        raise Missing(f"No {span} forecast for {target} on {day} at {gate}.")
    return day, gate


def download_files(days: int) -> list[tuple[Path, str]]:
    if not FORECASTS_DIR.is_dir():
        return []
    dates = options()["dates"][-days:]
    out: list[tuple[Path, str]] = []
    for day in dates:
        for gate in GATES:
            for span in SPANS:
                published = _published(day, gate, span)
                if published is not None:
                    for path in published.values():
                        out.append((path, f"{day}/{gate}_{span}/{path.name}"))
        for sub in (FORECASTS_DIR / day).iterdir():
            if (
                sub.is_dir()
                and sub.name in {f"{g}_{s}" for g in GATES for s in SPANS}
                and not (FORECASTS_DIR / day / f"{sub.name[:4]}.json").exists()
            ):
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
    days = [d for d in opts["dates"] if start <= d <= end]
    if not days:
        raise Missing("No forecasts in that date range.")

    zone = ZoneInfo(tz)
    cols = ["p50"] if kind == "point" else list(EXPORT_COLS)
    span = "d1" if horizon_days <= 1 else "d10"
    parts = []
    for day in days:
        path = None
        for sp in (span, "d10" if span == "d1" else "d1"):
            try:
                path = _newest(day, gate, sp, target)
                break
            except Missing:
                continue
        if path is None:
            continue
        frame = pd.read_parquet(path)
        if target not in frame.columns:
            continue
        index = _datetime_index(frame.index)
        origin = _origin_moment(day, gate)
        delivery_day = origin.date() + timedelta(days=1)
        delivery_start = datetime.combine(delivery_day, time.min, origin.tzinfo)
        delivery_end = datetime.combine(
            delivery_day + timedelta(days=horizon_days), time.min, origin.tzinfo
        )
        hours = (index - origin).total_seconds() / 3600.0
        keep = (index >= delivery_start) & (index < delivery_end)
        sub = frame.loc[keep]
        if sub.empty:
            continue
        sub_index = _datetime_index(sub.index)
        data: dict[str, list] = {
            "origin_date": [day] * len(sub),
            "origin_time": [f"{gate[:2]}:{gate[2:]}"] * len(sub),
            "target_time": [t.isoformat() for t in sub_index.tz_convert(zone)],
            "horizon_in_hours": [round(float(v), 2) for v in hours[keep]],
        }
        for c in cols:
            if EXPORT_COLS[c] not in sub.columns:
                data[c] = [None] * len(sub)
                continue
            values = _series_column(sub, EXPORT_COLS[c])
            data[c] = [None if pd.isna(v) else float(v) for v in values]
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
    if frame.empty:
        raise Missing(f"{target} forecast is empty for {day} at {gate}.")
    forecast_index = _datetime_index(frame.index)
    model = path.stem.rpartition("__")[2]

    start = forecast_index.min()
    end = forecast_index.max()
    if not isinstance(start, pd.Timestamp) or not isinstance(end, pd.Timestamp):
        raise Missing(f"{target} forecast has no valid timestamps for {day} at {gate}.")

    actual = _actual_series(target)
    if actual is not None:
        actual_index = _datetime_index(actual.index)
        actual = actual.loc[
            (actual_index >= start - LOOKBACK[span]) & (actual_index <= end)
        ].dropna()
        idx = forecast_index.union(_datetime_index(actual.index))
        frame = frame.reindex(idx)
        actual = actual.reindex(idx)
    else:
        idx = forecast_index
        actual = pd.Series(dtype="float64").reindex(idx)

    def qt(c):
        if c not in frame.columns:
            return None
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
    }
    out.update(
        {
            column: qt(source) if kind == "probabilistic" else None
            for column, source in EXPORT_COLS.items()
            if column != "p50"
        }
    )
    out["actual"] = av(actual)
    return out
