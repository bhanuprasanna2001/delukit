"""Backends: connection mechanics with zero layer knowledge.

Layers own table names, DDL and statements; these builders only open the
pipe. A new backend (supabase, …) adds connect() plus one branch below —
layers stay untouched.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from delukit.backends.base import SqlBackend
from delukit.backends.local import resolve


def build_backend(name: str, **kwargs: Any) -> Path | SqlBackend:
    """Open a backend handle: root Path for local, SqlBackend for SQL."""
    if name == "local":
        return resolve(kwargs.get("root", "delukit_store"))
    if name == "databricks":
        from delukit.backends.databricks import connect

        connection = kwargs.get("connection")
        return SqlBackend(connection if connection is not None else connect(), name)
    if name == "snowflake":
        from delukit.backends.snowflake import connect

        connection = kwargs.get("connection")
        return SqlBackend(connection if connection is not None else connect(), name)
    raise ValueError(f"unknown backend: {name!r}")
