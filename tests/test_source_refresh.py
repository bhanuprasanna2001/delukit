"""Scheduled refreshes stay bounded and propagate provider failures."""

from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest


def test_source_refresh_uses_recent_window_and_fails_on_fetch_error(
    monkeypatch, tmp_path
):
    import delukit.main as pipeline

    calls = []

    def sync(start, end, on_each):
        calls.append((start, end))
        on_each("load", start, "failed")
        return {"fetched": 0, "updated": 0, "unchanged": 0, "no_data": 0, "failed": 1}

    @contextmanager
    def progress(_totals):
        yield lambda *_args: None

    monkeypatch.setattr(
        pipeline, "SOURCES", {"entsoe": (SimpleNamespace(sync=sync), ("load",))}
    )
    monkeypatch.setattr(pipeline, "BASE_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "bootstrap_legacy", lambda _base: 0)
    monkeypatch.setattr(pipeline, "end_date", lambda: date(2026, 1, 11))
    monkeypatch.setattr(pipeline, "sync_progress", progress)
    monkeypatch.setattr(
        pipeline, "setup_logging", lambda: SimpleNamespace(info=lambda *_args: None)
    )
    monkeypatch.setattr(pipeline, "show_header", lambda *_args: None)
    monkeypatch.setattr(pipeline, "show_summary", lambda *_args: None)

    with pytest.raises(RuntimeError, match="source fetch failures"):
        pipeline.main()
    assert calls == [(date(2026, 1, 3), date(2026, 1, 11))]
