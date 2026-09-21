import logging
from pathlib import Path

from rich.logging import RichHandler

LOG_FILE = "data/delukit.log"


def setup_logging():
    Path("data").mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(), logging.FileHandler(LOG_FILE)],
    )

    return logging.getLogger("delukit")
