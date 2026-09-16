"""Bronze stores: local parquet, Databricks Delta, Snowflake tables.

One record schema lands identically in all three backends; the registry
maps config storage names to store classes.
"""

from delukit.storages.base import BronzeStore
from delukit.storages.databricks import DatabricksStore
from delukit.storages.local import LocalStore
from delukit.storages.snowflake import SnowflakeStore

_STORES = {
    "local": LocalStore,
    "databricks": DatabricksStore,
    "snowflake": SnowflakeStore,
}


def build_store(name: str, **kwargs) -> BronzeStore:
    """Build a bronze store by config name."""
    try:
        store_class = _STORES[name]
    except KeyError:
        raise ValueError(f"unknown storage: {name!r}") from None
    return store_class(**kwargs)
