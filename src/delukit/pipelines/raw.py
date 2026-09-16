"""From APIs to Bronze."""

from delukit.core.config import RawConfig, load_raw_config


def run(raw_config_path: str) -> RawConfig:
    return load_raw_config(raw_config_path)
