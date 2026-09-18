"""Architecture seam: layers own table knowledge, backends own mechanics.

Layers must not import connector packages or per-backend modules;
backends must not import layer table knowledge. A new backend (supabase,
…) is a new backend module only — this test fails otherwise. Pipelines
are the composition root and may wire both sides.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).parents[1] / "src" / "delukit"

_CONNECTORS = {"databricks", "snowflake", "supabase"}
_LAYER_BACKEND_IMPORTS = {"delukit.backends", "delukit.backends.base"}


def _modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def _files(*parts: str) -> list[Path]:
    return sorted((SRC.joinpath(*parts)).rglob("*.py"))


def test_layers_know_no_backends():
    violations = []
    for path in _files("layers"):
        for module in _modules(path):
            root = module.split(".")[0]
            if root in _CONNECTORS:
                violations.append(f"{path.name} imports connector {module!r}")
            if module.startswith("delukit.backends") and module not in (
                _LAYER_BACKEND_IMPORTS
            ):
                violations.append(f"{path.name} imports backend {module!r}")
    assert violations == []


def test_backends_know_no_layers():
    violations = [
        f"{path.name} imports {module!r}"
        for path in _files("backends")
        for module in _modules(path)
        if module.startswith("delukit.layers")
    ]
    assert violations == []
