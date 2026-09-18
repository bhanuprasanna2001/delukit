"""Snowflake backend: connection mechanics only. No table knowledge.

Connection: snowflake-connector-python with SNOWFLAKE_ACCOUNT,
SNOWFLAKE_USER and SNOWFLAKE_PASSWORD env vars (SNOWFLAKE_ROLE and
SNOWFLAKE_WAREHOUSE optional); tests pass an explicit connection via
build_backend(name, connection=...).
"""

from __future__ import annotations

import os


def connect():
    import snowflake.connector

    return snowflake.connector.connect(**_connect_params())


def _connect_params() -> dict:
    params = {
        "account": _env("SNOWFLAKE_ACCOUNT"),
        "user": _env("SNOWFLAKE_USER"),
        "password": _env("SNOWFLAKE_PASSWORD"),
    }
    for name, key in (
        ("SNOWFLAKE_ROLE", "role"),
        ("SNOWFLAKE_WAREHOUSE", "warehouse"),
    ):
        if os.environ.get(name):
            params[key] = os.environ[name]
    return params


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"snowflake: {name} environment variable is not set")
    return value
