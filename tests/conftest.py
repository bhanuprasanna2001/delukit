"""Shared fixtures: tmp data dirs for delukit sources/pipeline."""

import pytest


@pytest.fixture
def tmp_dirs(monkeypatch, tmp_path):
    """Point every delukit data dir at tmp (config + imported names)."""
    raw = tmp_path / "raw"
    clean = tmp_path / "clean"
    versioned = tmp_path / "versioned"
    forecasts = tmp_path / "forecasts"
    for p in (raw, clean, versioned, forecasts):
        p.mkdir()

    import delukit.core.clean as core_clean
    from delukit.core import config
    from delukit.sources import calendar, energy_charts, entsoe, smard, weather

    monkeypatch.setattr(config, "BASE_DIR", raw)
    monkeypatch.setattr(config, "CLEAN_DIR", clean)
    monkeypatch.setattr(config, "VERSIONED_DIR", versioned)
    monkeypatch.setattr(core_clean, "BASE_DIR", raw)
    monkeypatch.setattr(core_clean, "CLEAN_DIR", clean)
    for mod in (calendar, energy_charts, entsoe, smard, weather):
        monkeypatch.setattr(mod, "BASE_DIR", raw, raising=False)
    monkeypatch.setattr(
        calendar, "OPENHOLIDAYS_CACHE_DIR", tmp_path / "cache", raising=False
    )

    from delukit.core.config import products

    monkeypatch.setattr(products, "FORECAST_DIR", forecasts)
    monkeypatch.setattr(products, "BACKTEST_DIR", tmp_path / "backtests")
    monkeypatch.setattr(products, "SCORES_DIR", tmp_path / "scores")
    monkeypatch.setattr(products, "TUNING_DIR", tmp_path / "tuning")
    monkeypatch.setattr(products, "MLFLOW_DIR", tmp_path / "mlflow")

    return {
        "raw": raw,
        "clean": clean,
        "versioned": versioned,
        "forecasts": forecasts,
        "tmp": tmp_path,
    }


@pytest.fixture
def qindex():
    """4 UTC quarters starting midnight Berlin 2026-01-05 (a Monday)."""
    from datetime import datetime

    import pandas as pd

    from delukit.core.clean import BERLIN, UTC

    start = datetime(2026, 1, 5, 0, 0, tzinfo=BERLIN).astimezone(UTC)
    return pd.date_range(start, periods=4, freq="15min")
