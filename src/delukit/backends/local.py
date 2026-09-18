"""Local backend: filesystem root mechanics only. No table knowledge."""

from __future__ import annotations

from pathlib import Path

DEFAULT_ROOT = "delukit_store"


def resolve(root: str | Path = DEFAULT_ROOT) -> Path:
    """Resolve the store root every local layer table lives under."""
    return Path(root)
