"""Shared helpers for optional live-backend tests."""

from __future__ import annotations

import os


def has_snowflake_creds() -> bool:
    return all(
        os.environ.get(name)
        for name in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD")
    )


def has_databricks_creds() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "DATABRICKS_SERVER_HOSTNAME",
            "DATABRICKS_HTTP_PATH",
            "DATABRICKS_TOKEN",
        )
    )
