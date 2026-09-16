"""From APIs to Bronze.

Daily run: resolve the fetch window per source from bronze coverage in the
local store, fetch each configured method, and land the resulting records
into every configured storage. Each storage dedupes on
(source, day, key, payload_hash): refetched days whose payload did not
change write nothing, revised days append a fresh version, and days a
source could not serve leave no row behind — they stay inside the refresh
window and are retried on the next run.

The first run (empty coverage) backfills from config start; later runs
fetch only the refresh window plus new days. A source that fails does not
block the others; failures are collected and raised once every successful
source has landed.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from delukit.core.config import RawConfig, load_raw_config
from delukit.layers.bronze.records import make_records
from delukit.sources.build import build_source
from delukit.sources.data_source import DataSource
from delukit.storages import build_store
from delukit.storages.base import BronzeStore
from delukit.storages.local import LocalStore

log = logging.getLogger("delukit.raw")

_DEFAULT_REFRESH_DAYS = {
    "smard": 7,
    "entsoe": 7,
    "energy_charts": 7,
    "weather": 3,
}


class PipelineError(Exception):
    """One or more sources failed; every successful source still landed."""


def run(raw_config_path: str) -> RawConfig:
    """Fetch and land all sources from a raw config into its storages."""
    config = load_raw_config(raw_config_path)
    end = _resolve(config.end, config.timezone)
    begin = _resolve(config.start, config.timezone)
    log.info(
        "run start · sources=%s storages=%s window=%s..%s",
        ", ".join(sorted(config.sources)),
        ", ".join(config.storages),
        begin,
        end,
    )

    stores: dict[str, BronzeStore] = {
        name: build_store(name) for name in config.storages
    }
    anchor = stores.get("local")
    coverage = anchor.coverage() if isinstance(anchor, LocalStore) else set()
    log.debug("coverage anchor: %d (source, day) pairs", len(coverage))

    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    failures: list[str] = []
    for name, source_config in config.sources.items():
        window_start = _window_start(name, source_config, begin, coverage)
        if window_start > end:
            log.info("%s: nothing new to fetch", name)
            continue
        log.debug("%s: fetching %s..%s", name, window_start, end)
        source = build_source(name, source_config, config.timezone)
        try:
            records = _fetch_source(
                source, name, source_config, window_start, end, fetched_at
            )
        except Exception as error:  # noqa: BLE001 — a source may raise anything; isolate it
            log.error("%s failed: %s", name, error)
            failures.append(f"{name}: {error}")
            continue
        log.info("%s: %d records", name, len(records))
        for store_name, store in stores.items():
            try:
                written = store.write(records)
                log.info("  -> %s: %d rows", store_name, written)
            except Exception as error:  # noqa: BLE001 — a down store must not block the rest
                log.error("%s -> %s failed: %s", name, store_name, error)
                failures.append(f"{name} -> {store_name}: {error}")
    if failures:
        log.error("run failed: %s", "; ".join(failures))
        raise PipelineError("; ".join(failures))
    log.info("run complete")
    return config


def _resolve(value: date | str, timezone_name: str) -> date:
    if value == "latest":
        return _today(timezone_name)
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _today(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def _window_start(
    name: str,
    source_config: dict[str, Any],
    begin: date,
    coverage: set[tuple[str, date]],
) -> date:
    """First day to fetch for a source: refresh window before its latest day."""
    days = {day for source, day in coverage if source == name}
    if not days:
        return begin
    refresh_days = source_config.get("refresh_days", _DEFAULT_REFRESH_DAYS[name])
    return max(begin, max(days) - timedelta(days=refresh_days - 1))


def _fetch_source(
    source: DataSource,
    name: str,
    source_config: dict[str, Any],
    start: date,
    end: date,
    fetched_at: datetime,
) -> list[dict]:
    """Fetch every configured method of a source and build bronze records."""
    records: list[dict] = []
    entries = (
        [{"method": "forecast"}] if name == "weather" else source_config["methods"]
    )
    common = (
        {"area": source_config["area"], "resolution": source_config["resolution"]}
        if name == "smard"
        else {}
    )
    for entry in entries:
        method = entry["method"]
        params = {
            key: value
            for key, value in entry.items()
            if key not in ("method", "fetch_policy")
        }
        kwargs = {} if name == "weather" else {**common, "method": method, **params}
        log.debug("%s.%s: fetching", name, method)
        raws = source.fetch(start, end, **kwargs)
        records.extend(make_records(name, raws, fetched_at))
    return records
