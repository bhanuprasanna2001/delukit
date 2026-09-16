"""From APIs to Bronze."""

from delukit.core.config import Config, load_config


def run(config_path: str) -> Config:
    return load_config(config_path)
