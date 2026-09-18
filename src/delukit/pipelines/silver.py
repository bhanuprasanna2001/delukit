"""From bronze to silver: latest payload per (day, key), parsed, upserted.

Daily run: for each configured source, collapse bronze versions in the
refresh window to the latest payload, parse each day with the existing
silver parsers (untouched), and upsert one table per source+method at
native grain under silver/<domain>/. Upserts are idempotent, so
reprocessing unchanged bronze is a no-op and revised payloads overwrite
by natural key — history stays in bronze only.

No cross-source fallback here: an entsoe SDAC gap and its energy_charts
mirror land side by side; gold decides. Silver reads only the local
bronze store (the only backend serving full records).

Known limitation: unlike bronze `sync`, silver has no relay — an upsert
failure older than the refresh window is never retried. Rerun within
refresh_days after a store outage.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

import pandas as pd

from delukit.core.config import PipelineConfig, load_pipeline_config
from delukit.layers.bronze.store import build_bronze_store
from delukit.layers.silver.loader import load_latest
from delukit.layers.silver.parsers import energy_charts as ec_parser
from delukit.layers.silver.parsers import entsoe as entsoe_parser
from delukit.layers.silver.parsers import smard as smard_parser
from delukit.layers.silver.parsers import weather as weather_parser
from delukit.layers.silver.store import SilverStore, build_silver_store
from delukit.layers.silver.tables import table_for
from delukit.pipelines import (
    PipelineError,
    fmt_elapsed,
    resolve_day,
    window_start,
)

log = logging.getLogger("delukit.silver")


def run(config_path: str) -> PipelineConfig:
    """Parse bronze into every configured silver table and store."""
    config = load_pipeline_config(config_path)
    end = resolve_day(config.end, config.timezone)
    begin = resolve_day(config.start, config.timezone)
    t0 = time.perf_counter()
    log.info(
        "┌ silver start · window=%s..%s · sources=%s · storages=%s",
        begin,
        end,
        ", ".join(sorted(config.sources)),
        ", ".join(config.storages),
    )

    bronze = build_bronze_store("local")
    coverage = bronze.coverage()
    if not coverage:
        log.warning(
            "├─ no local bronze rows — run `delukit bronze` before `delukit silver`"
        )
    log.debug("bronze anchor (local): %d (source, day) pairs", len(coverage))
    stores: dict[str, SilverStore] = {
        name: build_silver_store(name) for name in config.storages
    }

    failures: list[str] = []
    total_rows = 0
    for name, source_config in config.sources.items():
        first_day = window_start(name, source_config, begin, coverage)
        if first_day > end:
            log.info("├─ %s: nothing new", name)
            continue
        t1 = time.perf_counter()
        try:
            raws = load_latest(bronze.root, name, first_day, end)
        except Exception as error:  # noqa: BLE001 — unreadable bronze isolates here
            log.error("├─ %s load failed: %s", name, error)
            failures.append(f"{name}: {error}")
            continue
        entries = (
            [{"method": "forecast"}] if name == "weather" else source_config["methods"]
        )
        for entry in entries:
            table = table_for(name, entry["method"])
            frame, parse_failures = _parse_table(
                name, entry, raws, first_day, end, config.timezone
            )
            failures.extend(parse_failures)
            if frame.empty:
                log.debug("%s: no rows in window", table)
                continue
            parts: list[str] = []
            for store_name, store in stores.items():
                try:
                    parts.append(f"{store_name} +{store.upsert(table, frame)}")
                except Exception as error:  # noqa: BLE001 — a down store blocks none
                    log.error("├─ %s → %s failed: %s", table, store_name, error)
                    failures.append(f"{table} -> {store_name}: {error}")
            if parts:
                total_rows += len(frame)
                log.info(
                    "├─ %s: %d rows · %s · %s",
                    table,
                    len(frame),
                    fmt_elapsed(time.perf_counter() - t1),
                    " · ".join(parts),
                )
    elapsed = fmt_elapsed(time.perf_counter() - t0)
    if failures:
        log.error(
            "└ silver failed · %d rows · %s · %d failed: %s",
            total_rows,
            elapsed,
            len(failures),
            "; ".join(failures),
        )
        raise PipelineError("; ".join(failures))
    log.info("└ silver complete · %d rows · %s", total_rows, elapsed)
    return config


def _parse_table(
    source: str,
    entry: dict[str, Any],
    raws: dict[date, dict[str, Any]],
    start: date,
    end: date,
    tz: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Parse every bronze day in the window; a bad day fails, never blocks."""
    table = table_for(source, entry["method"])
    failures: list[str] = []
    frames: list[pd.DataFrame] = []
    day = start
    while day <= end:
        day_raws = raws.get(day)
        if day_raws:
            try:
                frame = _parse_day(source, entry, day_raws, tz)
            except Exception as error:  # noqa: BLE001 — one corrupt day skips
                log.error("├─ %s %s failed: %s", table, day, error)
                failures.append(f"{table} {day.isoformat()}: {error}")
            else:
                if not frame.empty:
                    frames.append(frame)
        day += timedelta(days=1)
    if not frames:
        return pd.DataFrame(), failures
    return pd.concat(frames, ignore_index=True), failures


def _parse_day(
    source: str, entry: dict[str, Any], day_raws: dict[str, Any], tz: str
) -> pd.DataFrame:
    """Dispatch one day's payloads to its source parser (fetch_policy ignored)."""
    method = entry["method"]
    if source == "smard":
        return smard_parser.parse_day(
            day_raws, method, generation_types=entry.get("generation_types"), tz=tz
        )
    if source == "entsoe":
        return entsoe_parser.parse_day(
            day_raws,
            method,
            sequences=tuple(entry.get("sequences", (1,))),
            psr_types=entry.get("psr_types"),
            tz=tz,
        )
    if source == "energy_charts":
        return ec_parser.parse_day(day_raws, method, tz=tz)
    if source == "weather":
        return weather_parser.parse_day(day_raws, "forecast", tz=tz)
    raise ValueError(f"unknown source: {source!r}")
