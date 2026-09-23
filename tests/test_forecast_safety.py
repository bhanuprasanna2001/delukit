"""Operational forecasts must use the gate's information set."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset


def test_historical_gate_cannot_publish_operational_forecast(tmp_dirs, monkeypatch):
    import delukit.forecast as forecast

    monkeypatch.setattr(forecast, "FORECAST_DIR", tmp_dirs["forecasts"])

    origin = date(2026, 1, 5)
    with pytest.raises(ValueError, match="historical replay"):
        forecast.assert_live_gate(
            origin, "0530", datetime(2026, 1, 6, tzinfo=ZoneInfo("UTC"))
        )
    with pytest.raises(ValueError, match="historical replay"):
        forecast.run_gate(origin, "0530", "d1", (), registry=False)
    assert not (tmp_dirs["forecasts"] / origin.isoformat()).exists()


def test_gate_fit_excludes_later_truth_and_reused_models(monkeypatch):
    import delukit.forecast as forecast

    idx = pd.date_range("2026-01-05 00:00", periods=3, freq="h", tz="UTC")
    part = TimeSeriesDataset(
        pd.DataFrame(
            {
                "load_actual_mw": [1, 2, 3],
                "available_at": pd.to_datetime(
                    [
                        "2026-01-04T00:00Z",
                        "2026-01-05T01:00Z",
                        "2026-01-05T03:00Z",
                    ]
                ),
            },
            index=idx,
        ),
        sample_interval=timedelta(hours=1),
    )
    monkeypatch.setattr(forecast, "load", lambda: VersionedTimeSeriesDataset([part]))
    captured = {}

    class Model:
        is_fitted = True

    class Workflow:
        model = Model()

        def fit(self, data):
            captured["values"] = data.data["load_actual_mw"].tolist()

    def fake_create(*args, **kwargs):
        config = kwargs["config"]
        captured["reuse"] = config.model_reuse_enable
        captured["selection"] = config.model_selection_enable
        return Workflow()

    monkeypatch.setattr(forecast, "create_workflow", fake_create)
    cutoff = datetime(2026, 1, 5, 1, 30, tzinfo=ZoneInfo("UTC"))
    forecast.fit_product("load_actual_mw", "0530", "d1", as_of=cutoff)
    assert captured == {"values": [1, 2], "reuse": False, "selection": False}
