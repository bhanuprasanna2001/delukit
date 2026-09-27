import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd

from delukit.core.config import products as config

BERLIN = ZoneInfo("Europe/Berlin")
QUANTILES = tuple(quantile.format() for quantile in config.QUANTILES)


def expected_index(day: date, span: str) -> pd.DatetimeIndex:
    first = datetime.combine(day + timedelta(days=1), datetime.min.time(), BERLIN)
    last_day = day + timedelta(days=2 if span == "d1" else 11)
    end = datetime.combine(last_day, datetime.min.time(), BERLIN)
    return pd.date_range(
        first.astimezone(UTC), end.astimezone(UTC), freq="15min", inclusive="left"
    )


def validate_product(path: Path, day: date, span: str) -> int:
    frame = pd.read_parquet(path)
    expected = expected_index(day, span)
    if not frame.index.equals(expected):
        raise ValueError(f"{path}: forecast timestamps differ from delivery grid")
    if not set(QUANTILES).issubset(frame.columns):
        raise ValueError(f"{path}: missing forecast quantiles")
    values = frame[list(QUANTILES)].to_numpy(dtype=float)
    if not all(math.isfinite(float(value)) for value in values.flat):
        raise ValueError(f"{path}: non-finite forecast quantile")
    if not (values[:, :-1] <= values[:, 1:]).all():
        raise ValueError(f"{path}: unordered forecast quantiles")
    return len(frame)


def begin_run(day: date, gate: str) -> Path:
    path = config.FORECAST_DIR / day.isoformat() / ".runs" / uuid4().hex
    path.mkdir(parents=True)
    return path


def publish(day: date, gate: str, run_dir: Path, products: list[dict]) -> Path:
    expected = set(config.PRODUCTS_BY_GATE[gate])
    actual = {(item["span"], item["target"]) for item in products}
    if actual != expected or len(products) != len(expected):
        raise ValueError(
            "gate publication requires every configured product exactly once"
        )
    for item in products:
        path = run_dir / item["span"] / f"{item['target']}__{item['model']}.parquet"
        validate_product(path, day, item["span"])
        item["path"] = str(path.relative_to(run_dir.parent.parent))
        item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {
        "schema": 1,
        "day": day.isoformat(),
        "gate": gate,
        "run_id": run_dir.name,
        "published_at": datetime.now(UTC).isoformat(),
        "products": products,
    }
    snapshot = run_dir / "features.parquet"
    if snapshot.is_file():
        manifest["input_snapshot"] = {
            "path": str(snapshot.relative_to(run_dir.parent.parent)),
            "sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        }
    destination = config.FORECAST_DIR / day.isoformat() / f"{gate}.json"
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, separators=(",", ":")) + "\n")
    temporary.replace(destination)
    return destination


def published_products(day: date, gate: str, span: str) -> list[tuple[str, str, Path]]:
    day_dir = config.FORECAST_DIR / day.isoformat()
    manifest = day_dir / f"{gate}.json"
    if manifest.exists():
        body = json.loads(manifest.read_text())
        if (
            body["schema"] != 1
            or body["day"] != day.isoformat()
            or body["gate"] != gate
        ):
            raise ValueError(f"invalid gate manifest: {manifest}")
        return [
            (item["target"], item["model"], day_dir / item["path"])
            for item in body["products"]
            if item["span"] == span
        ]
    legacy = day_dir / f"{gate}_{span}"
    newest = {}
    for path in legacy.glob("*__*.parquet"):
        target, model = path.stem.rsplit("__", 1)
        if (
            target not in newest
            or path.stat().st_mtime > newest[target][1].stat().st_mtime
        ):
            newest[target] = (model, path)
    return [(target, model, path) for target, (model, path) in sorted(newest.items())]
