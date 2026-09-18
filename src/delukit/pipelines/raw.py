"""From APIs to Bronze.

Daily run: resolve the fetch window per source from bronze coverage in the
anchor store, fetch each configured method, land into local first, then
relay every local identity missing remotely. Each storage dedupes on
(source, day, key, payload_hash): refetched days whose payload did not
change write nothing, revised days append a fresh version, and days a
source could not serve leave no row behind — they stay inside the refresh
window and are retried on the next run.

Sync (`delukit sync`) replays the same relay without fetching: any
(source, day, key, payload_hash) present locally but missing in a remote
is written there. Relay is at-least-once and idempotent, so a failed
remote heals on the next run or the next sync, even outside the refresh
window.

The first run (empty coverage) backfills from config start; later runs
fetch only the refresh window plus new days. A source that fails does not
block the others; failures are collected and raised once every successful
source has landed.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from delukit.core.config import RawConfig, load_raw_config
from delukit.layers.bronze.records import make_records
from delukit.layers.bronze.store import BronzeStore, build_bronze_store
from delukit.sources.build import build_source
from delukit.sources.data_source import DataSource

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
    t0 = time.perf_counter()
    log.info(
        "┌ run start · window=%s..%s · sources=%s · storages=%s",
        begin,
        end,
        ", ".join(sorted(config.sources)),
        ", ".join(config.storages),
    )

    stores: dict[str, BronzeStore] = {
        name: build_bronze_store(name) for name in config.storages
    }
    # ponytail: local anchor is a free parquet read; a remote anchor costs
    # one SELECT DISTINCT per run — prefer local when configured.
    anchor_name = "local" if "local" in stores else config.storages[0]
    coverage = stores[anchor_name].coverage()
    log.debug(
        "coverage anchor (%s): %d (source, day) pairs", anchor_name, len(coverage)
    )

    fetched_at = datetime.now(UTC).replace(tzinfo=None)
    failures: list[str] = []
    total_records = 0
    use_relay = "local" in stores
    for name, source_config in config.sources.items():
        window_start = _window_start(name, source_config, begin, coverage)
        if window_start > end:
            log.info("├─ %s: nothing new", name)
            continue
        log.debug("%s: fetching %s..%s", name, window_start, end)
        source = build_source(name, source_config, config.timezone)
        t1 = time.perf_counter()
        try:
            records = _fetch_source(
                source, name, source_config, window_start, end, fetched_at
            )
        except Exception as error:  # noqa: BLE001 — a source may raise anything; isolate it
            log.error("├─ %s failed: %s", name, error)
            failures.append(f"{name}: {error}")
            continue
        total_records += len(records)
        targets = {"local": stores["local"]} if use_relay else stores
        parts: list[str] = []
        for store_name, store in targets.items():
            try:
                written = store.write(records)
                parts.append(f"{store_name} +{written}")
            except Exception as error:  # noqa: BLE001 — a down store must not block the rest
                log.error("├─ %s → %s failed: %s", name, store_name, error)
                failures.append(f"{name} -> {store_name}: {error}")
        if parts:
            log.info(
                "├─ %s: %d fetched · %s · %s",
                name,
                len(records),
                _fmt_elapsed(time.perf_counter() - t1),
                " · ".join(parts),
            )
    sync_failures, synced = _sync_from_local(stores)
    failures.extend(sync_failures)
    elapsed = _fmt_elapsed(time.perf_counter() - t0)
    if failures:
        log.error(
            "└ run failed · %d fetched · %s · %d synced · %d failed: %s",
            total_records,
            elapsed,
            synced,
            len(failures),
            "; ".join(failures),
        )
        raise PipelineError("; ".join(failures))
    log.info(
        "└ run complete · %d fetched · %s · %d synced",
        total_records,
        elapsed,
        synced,
    )
    return config


def sync(raw_config_path: str) -> RawConfig:
    """Replay local bronze into every remote without fetching."""
    config = load_raw_config(raw_config_path)
    stores: dict[str, BronzeStore] = {
        name: build_bronze_store(name) for name in config.storages
    }
    t0 = time.perf_counter()
    log.info("┌ sync start · storages=%s", ", ".join(config.storages))
    failures, synced = _sync_from_local(stores)
    elapsed = _fmt_elapsed(time.perf_counter() - t0)
    if failures:
        log.error(
            "└ sync failed · %s · %d synced · %d failed: %s",
            elapsed,
            synced,
            len(failures),
            "; ".join(failures),
        )
        raise PipelineError("; ".join(failures))
    log.info("└ sync complete · %s · %d synced", elapsed, synced)
    return config


def _sync_from_local(stores: dict[str, BronzeStore]) -> tuple[list[str], int]:
    """Write every local identity missing remotely; return (failures, synced)."""
    if "local" not in stores or len(stores) < 2:
        return [], 0
    local = stores["local"]
    if not hasattr(local, "records_for"):
        return ["sync: local store cannot serve records_for()"], 0
    try:
        local_idents = local.identities()
    except Exception as error:  # noqa: BLE001 — unreadable local parquet
        log.error("├─ local sync failed: %s", error)
        return [f"sync -> local: {error}"], 0
    if not local_idents:
        return [], 0
    failures: list[str] = []
    synced = 0
    for name, store in stores.items():
        if name == "local":
            continue
        try:
            missing = local_idents - store.identities()
        except Exception as error:  # noqa: BLE001 — a down store must not block the rest
            log.error("├─ %s sync failed: %s", name, error)
            failures.append(f"sync -> {name}: {error}")
            continue
        if not missing:
            log.info("├─ %s: in sync", name)
            continue
        try:
            written = store.write(local.records_for(missing))
            synced += written
            log.info("├─ %s: +%d synced", name, written)
        except Exception as error:  # noqa: BLE001 — a down store must not block the rest
            log.error("├─ %s sync failed: %s", name, error)
            failures.append(f"sync -> {name}: {error}")
    return failures, synced


def _fmt_elapsed(seconds: float) -> str:
    """Compact duration: 12s, 5m42s, 1h02m03s."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{secs:02d}s"


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
        log.debug("%s %s fetching", name, method)
        raws = source.fetch(start, end, **kwargs)
        records.extend(make_records(name, raws, fetched_at))
    return records
