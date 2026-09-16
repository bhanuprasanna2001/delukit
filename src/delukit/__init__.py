"""delukit: German energy data pipeline.

Usage: delukit [raw_config_path]   (default: configs/raw.json)
"""

import sys


def main() -> None:
    from delukit.core.log import setup_logging
    from delukit.pipelines.raw import run

    setup_logging()
    path = sys.argv[1] if len(sys.argv) > 1 else "configs/raw.json"
    run(path)
