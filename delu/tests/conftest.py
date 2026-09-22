"""Shared fixtures: tmp forecast/actual dirs + isolated sqlite + clean throttles."""

import pytest


@pytest.fixture
def tmp_dirs(monkeypatch, tmp_path):
    """Point backend dirs at tmp; fresh DB; reset in-memory throttles."""
    forecasts = tmp_path / "forecasts"
    clean = tmp_path / "clean"
    forecasts.mkdir()
    clean.mkdir()

    from backend import forecasts as be_forecasts

    monkeypatch.setattr(be_forecasts, "FORECASTS_DIR", forecasts)
    monkeypatch.setattr(be_forecasts, "ACTUALS_DIR", clean)

    from backend import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "app.db")
    db.init()

    from backend import auth

    auth._fails.clear()
    from backend import app as be_app

    be_app._ip_hits.clear()
    be_app._contact_hits.clear()

    return {"forecasts": forecasts, "clean": clean, "tmp": tmp_path}


@pytest.fixture
def actuals(tmp_dirs):
    """Minimal realised-history sidecar so forecast load() can join actuals."""
    import pandas as pd

    idx = pd.date_range("2026-01-05 00:00", periods=200, freq="15min", tz="UTC")
    pd.DataFrame({"load_actual_mw": [5.0] * 200}, index=idx).to_parquet(
        tmp_dirs["clean"] / "entsoe.parquet"
    )
    return tmp_dirs["clean"] / "entsoe.parquet"
