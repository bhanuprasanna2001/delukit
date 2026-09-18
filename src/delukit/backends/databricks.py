"""Databricks backend: connection mechanics only. No table knowledge.

Connection: databricks-sql-connector with DATABRICKS_SERVER_HOSTNAME,
DATABRICKS_HTTP_PATH and DATABRICKS_TOKEN env vars; tests pass an
explicit connection via build_backend(name, connection=...).
"""

from __future__ import annotations

import os


def connect():
    from databricks import sql as databricks_sql

    return databricks_sql.connect(
        server_hostname=_env("DATABRICKS_SERVER_HOSTNAME"),
        http_path=_env("DATABRICKS_HTTP_PATH"),
        access_token=_env("DATABRICKS_TOKEN"),
    )


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"databricks: {name} environment variable is not set")
    return value
