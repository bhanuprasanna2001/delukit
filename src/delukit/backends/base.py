"""Backend mechanics shared by every layer: batched SQL execution.

No table names, no DDL, no domain paths here — callers (the layers) pass
fully-formed statements. A new backend (supabase, …) means connect() plus
one dialect row below; no layer changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd
from tqdm import tqdm

from delukit.core.log import BAR_FORMAT

# ponytail: row cap + byte cap; a batch flushes on whichever hits first.
# 800k chars sits under Databricks' 1M parameterized-query limit with room
# for connector overhead — a single bronze weather row (~490k) always fits
# alone. Callers with narrow rows (silver) raise max_rows instead.
DEFAULT_MAX_CHARS = 800_000

_MARKERS = {"databricks": "?", "snowflake": "%s"}
_LABEL_COLOURS: dict[str, str | None] = {"databricks": "blue", "snowflake": "cyan"}


@dataclass(frozen=True)
class SqlBackend:
    """A live SQL connection plus its dialect name."""

    connection: Any
    name: str  # one of _MARKERS; KeyError on unknown is intentional


def marker(name: str) -> str:
    """Parameter marker for the dialect; raises on unknown backends."""
    try:
        return _MARKERS[name]
    except KeyError:
        raise ValueError(f"unknown backend: {name!r}") from None


def quote(name: str, column: str) -> str:
    """Quote an identifier (timestamp/KEY are reserved words)."""
    if name == "databricks":
        return f"`{column}`"
    if name == "snowflake":
        return f'"{column.upper()}"'
    raise ValueError(f"unknown backend: {name!r}")


def label_colour(name: str) -> str | None:
    """Progress-bar colour per backend; unknown backends get none."""
    return _LABEL_COLOURS.get(name)


def run_batched(
    connection,
    ddl: tuple[str, ...],
    template: str,
    rows: list[list],
    *,
    marker: str,
    label: str,
    colour: str | None = None,
    max_rows: int = 20,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> int:
    """Run DDL once, then execute the template in chunked statements.

    template carries a {values} placeholder filled with one "(?, ?, …)"
    group per row. Chunks split on row count or estimated parameter size,
    whichever hits first, so giant payloads land alone while narrow rows
    still batch up. Progress is shown on a tty only.
    """
    cleaned = [[clean_param(value) for value in row] for row in rows]
    if not cleaned:
        return 0
    total = 0
    with connection.cursor() as cursor:
        for statement in ddl:
            cursor.execute(statement)
        with tqdm(
            total=len(cleaned),
            desc=label,
            bar_format=BAR_FORMAT,
            unit="rows",
            colour=colour,
            position=0,
            leave=False,
            dynamic_ncols=True,
            mininterval=0.5,
            disable=None,
        ) as bar:
            for chunk in _chunks(cleaned, max_rows, max_chars):
                groups = ", ".join(
                    f"({', '.join([marker] * len(chunk[0]))})" for _ in chunk
                )
                cursor.execute(
                    template.format(values=groups),
                    [value for row in chunk for value in row],
                )
                total += cursor.rowcount
                bar.update(len(chunk))
    return total


def clean_param(value):
    """Normalize one bound value: datetimes stay, NaN/NaT becomes None."""
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.to_pydatetime()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def normalize_day(value) -> date:
    """Normalize a stored DAY value to a date object."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def is_missing_table(error: Exception) -> bool:
    """True when an error means the queried table does not exist yet."""
    message = str(error).lower()
    return (
        "does not exist" in message
        or "not found" in message
        or "no such" in message
        or "table_or_view_not_found" in message
        or "002003" in message
    )


def _chunks(rows: list[list], max_rows: int, max_chars: int):
    """Yield chunks of at most max_rows rows or max_chars estimated chars."""
    batch, size = [], 0
    for row in rows:
        need = sum(len(value) if isinstance(value, str) else 16 for value in row)
        if batch and (len(batch) >= max_rows or size + need > max_chars):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += need
    if batch:
        yield batch
