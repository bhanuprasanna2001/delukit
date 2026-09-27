from datetime import date
from types import SimpleNamespace

import pandas as pd


def test_scoring_waits_for_complete_delivery_days(tmp_dirs, monkeypatch):
    import delukit.evaluation.backtest as backtest
    from delukit.ops.publication import expected_index

    day = date(2026, 1, 5)
    target = "load_actual_mw"
    run = tmp_dirs["forecasts"] / day.isoformat() / "0530_d10"
    run.mkdir(parents=True)
    index = expected_index(day, "d10")
    pd.DataFrame(
        {
            "quantile_P10": 40.0,
            "quantile_P50": 50.0,
            "quantile_P90": 60.0,
        },
        index=index,
    ).to_parquet(run / f"{target}__xgboost.parquet")
    observed = pd.DataFrame({target: 50.0}, index=index[: 96 * 2 - 1])
    part = SimpleNamespace(
        feature_names=[target], select_version=lambda: SimpleNamespace(data=observed)
    )
    monkeypatch.setattr(backtest, "load", lambda: SimpleNamespace(data_parts=[part]))

    rows = backtest.score_gate(day, "0530", save=False)
    assert [(row["span"], row["lead_day"], row["n"]) for row in rows] == [
        ("d10", 1, 96)
    ]
