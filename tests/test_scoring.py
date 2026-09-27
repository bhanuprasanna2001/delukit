import json
import math
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
    assert rows[0]["quantiles"] == "quantile_P10,quantile_P50,quantile_P90"
    assert rows[0]["quantile_count"] == 3


def test_scoring_preserves_nine_quantiles_and_registered_version(tmp_dirs, monkeypatch):
    import delukit.evaluation.backtest as backtest
    from delukit.ops.publication import expected_index

    day = date(2026, 1, 5)
    target = "load_actual_mw"
    day_dir = tmp_dirs["forecasts"] / day.isoformat()
    run = day_dir / ".runs" / "trained" / "d1"
    run.mkdir(parents=True)
    index = expected_index(day, "d1")
    path = run / f"{target}__xgboost.parquet"
    pd.DataFrame(
        {f"quantile_P{q}": 40.0 + q / 5 for q in range(10, 100, 10)},
        index=index,
    ).to_parquet(path)
    (day_dir / "0530.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "day": day.isoformat(),
                "gate": "0530",
                "products": [
                    {
                        "span": "d1",
                        "target": target,
                        "model": "xgboost",
                        "model_version": "7",
                        "path": str(path.relative_to(day_dir)),
                    }
                ],
            }
        )
    )
    part = SimpleNamespace(
        feature_names=[target],
        select_version=lambda: SimpleNamespace(
            data=pd.DataFrame({target: 50.0}, index=index)
        ),
    )
    monkeypatch.setattr(backtest, "load", lambda: SimpleNamespace(data_parts=[part]))

    rows = backtest.score_gate(day, "0530", save=False)

    assert len(rows) == 1
    assert rows[0]["model_version"] == "7"
    assert rows[0]["quantiles"] == ",".join(
        f"quantile_P{q}" for q in range(10, 100, 10)
    )
    assert rows[0]["quantile_count"] == 9
    assert all(math.isfinite(rows[0][f"obs_p{q}"]) for q in range(10, 100, 10))


def test_daily_report_counts_only_past_incomplete_delivery_days(tmp_dirs):
    from delukit.ops.monitor import daily_score_report

    issue = date(2026, 1, 5)
    day_dir = tmp_dirs["forecasts"] / issue.isoformat()
    day_dir.mkdir()
    (day_dir / "1130.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "day": issue.isoformat(),
                "gate": "1130",
                "products": [
                    {
                        "span": span,
                        "target": "load_actual_mw",
                        "model": "xgboost",
                        "path": f"{span}/forecast.parquet",
                    }
                    for span in ("d1", "d10")
                ],
            }
        )
    )
    rows = [
        {
            "day": issue.isoformat(),
            "gate": "1130",
            "span": span,
            "target": "load_actual_mw",
            "lead_day": 1,
            "rmae": 0.8,
            "rcrps": 0.9,
            "model_version": "7",
        }
        for span in ("d1", "d10")
    ]

    report = daily_score_report(date(2026, 1, 8), rows)

    assert report.scored == 2
    assert report.pending_mature == 1
    assert "load_actual_mw (2026-01-05 v7): rMAE 0.800, rCRPS 0.900" in report.message
    assert "2026-01-05 1130 d10 load_actual_mw D+2" in report.message
