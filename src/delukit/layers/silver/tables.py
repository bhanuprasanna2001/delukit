"""Silver tables: domain folders, one table per source+method, native grain.

silver/
    prices/<source>_day_ahead_price.parquet
    load/<source>_load_{actual,forecast}.parquet
    generation/<source>_generation_*.parquet
    weather/weather_forecast.parquet

No cross-source merging here: overlapping providers (entsoe SDAC vs
energy_charts mirror, smard types vs entsoe psr types) land side by side
and gold decides. Native grain is preserved too — pre-cutover hourly days
and post-2025-10-01 quarter-hourly days share one table; parsers emit
whatever the payload held.
"""

from __future__ import annotations

import pandas as pd

from delukit.backends.base import quote

_DOMAIN = {
    "day_ahead_price": "prices",
    "load_actual": "load",
    "load_forecast": "load",
    "generation_actual": "generation",
    "generation_forecast": "generation",
    "generation_forecast_day_ahead": "generation",
    "forecast": "weather",
}


def table_for(source: str, method: str) -> str:
    """Silver table name for one source+method (weather has only forecast)."""
    return f"{source}_{method}"


_SOURCES = ("energy_charts", "smard", "entsoe", "weather")


def split_table(table: str) -> tuple[str, str]:
    """Split a silver table back into (source, method)."""
    for source in _SOURCES:
        if table.startswith(source + "_"):
            return source, table[len(source) + 1 :]
    raise ValueError(f"unknown silver table: {table!r}")


def domain_for(method: str) -> str:
    """Domain folder for a method; raises on unknown methods."""
    try:
        return _DOMAIN[method]
    except KeyError:
        raise ValueError(f"unknown silver method: {method!r}") from None


def keys_for(source: str, method: str) -> list[str]:
    """Natural (upsert) key: native type column, never harmonized here."""
    if method == "day_ahead_price":
        return ["timestamp", "sequence"]
    if method in ("load_actual", "load_forecast"):
        return ["timestamp"]
    if method in ("generation_actual", "generation_forecast"):
        if source == "smard":
            return ["timestamp", "generation_type"]
        return ["timestamp", "psr_type"]
    if method == "generation_forecast_day_ahead":
        return ["timestamp", "generation_type"]
    if source == "weather" and method == "forecast":
        return ["run_time", "location", "valid_time"]
    raise ValueError(f"unknown silver table: {source}_{method}")


def keys_for_table(table: str) -> list[str]:
    """Natural key without callers splitting source off the table name."""
    source, method = split_table(table)
    return keys_for(source, method)


def table_name(backend: str, prefix: str, table: str) -> str:
    """Physical silver table: as-is on Databricks, upper on Snowflake."""
    if backend == "snowflake":
        return f"{prefix}.{table.upper()}"
    if backend == "databricks":
        return f"{prefix}.{table}"
    raise ValueError(f"unknown backend: {backend!r}")


def columns_ddl(frame: pd.DataFrame, backend: str) -> str:
    """Column definitions from frame dtypes; instants stay exact per dialect."""
    if backend not in ("databricks", "snowflake"):
        raise ValueError(f"unknown backend: {backend!r}")
    names = (
        [column.upper() for column in frame.columns]
        if backend == "snowflake"
        else list(frame.columns)
    )
    return ", ".join(
        f"{quote(backend, name)} {_sql_type(name.lower(), frame[column], backend)}"
        for column, name in zip(frame.columns, names)
    )


def merge_sql(backend: str, table: str, columns: list[str], keys: list[str]) -> str:
    """Natural-key MERGE; {values} filled per batch."""
    if backend == "databricks":
        names = list(columns)
        using = (
            f"(SELECT * FROM VALUES {{values}} AS v("
            f"{', '.join(quote(backend, name) for name in names)}))"
        )
    elif backend == "snowflake":
        names = [column.upper() for column in columns]
        keys = [key.upper() for key in keys]
        inner = ", ".join(
            f"${i + 1} AS {quote(backend, name)}" for i, name in enumerate(names)
        )
        using = f"(SELECT {inner} FROM VALUES {{values}})"
    else:
        raise ValueError(f"unknown backend: {backend!r}")
    quoted = [quote(backend, name) for name in names]
    keyed = [quote(backend, key) for key in keys]
    on = " AND ".join(f"target.{name} = s.{name}" for name in keyed)
    return (
        f"MERGE INTO {table} AS target USING {using} AS s ON {on} "
        f"WHEN MATCHED THEN UPDATE SET "
        f"{', '.join(f'target.{name} = s.{name}' for name in quoted if name not in keyed)} "
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(quoted)}) "
        f"VALUES ({', '.join(f's.{name}' for name in quoted)})"
    )


_TS_COLUMNS = {"timestamp", "run_time", "valid_time"}


def _sql_type(column: str, series: pd.Series, backend: str) -> str:
    if column in _TS_COLUMNS:
        return "TIMESTAMP_TZ" if backend == "snowflake" else "TIMESTAMP"
    if series.dtype.kind == "b":
        return "BOOLEAN"
    if series.dtype.kind in "iu":
        return "INT"
    if series.dtype.kind == "f":
        return "DOUBLE"
    return "STRING"
