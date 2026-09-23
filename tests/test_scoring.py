"""Delivery-day scoring and the 15:30 notification contract."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from delukit.core.clean import BERLIN, quarter_grid


@pytest.mark.parametrize(
    ("delivery_day", "expected_n"),
    [(date(2026, 3, 29), 92), (date(2025, 10, 26), 100)],
)
def test_score_delivery_day_exact_grid_cutoff_and_idempotence(
    tmp_dirs, monkeypatch, delivery_day, expected_n
):
    import delukit.backtest as backtest
    from delukit.core.config import products

    target = "load_actual_mw"
    monkeypatch.setattr(products, "TARGETS", (target,))
    grid = quarter_grid(delivery_day)
    assert len(grid) == expected_n
    known = pd.Series([100.0 + i % 7 for i in range(len(grid))], index=grid)
    cutoff = datetime.combine(
        delivery_day + timedelta(days=1), datetime.min.time(), BERLIN
    ).replace(hour=15, minute=30)
    versions = pd.DataFrame(
        {
            target: [*known, *[v + 50 for v in known]],
            "available_at": [
                *[cutoff - timedelta(hours=1)] * len(grid),
                *[cutoff + timedelta(hours=1)] * len(grid),
            ],
        },
        index=grid.append(grid),
    )
    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(
            data_parts=[SimpleNamespace(feature_names=[target], data=versions)]
        ),
    )
    origin = delivery_day - timedelta(days=1)
    path = (
        tmp_dirs["forecasts"]
        / origin.isoformat()
        / "0530_d1"
        / f"{target}__xgboost.parquet"
    )
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "quantile_P10": known - 10,
            "quantile_P50": known,
            "quantile_P90": known + 10,
        },
        index=grid,
    ).to_parquet(path)

    rows = backtest.score_delivery_day(delivery_day, cutoff)
    scored = next(r for r in rows if r["gate"] == "0530" and r["span"] == "d1")
    assert scored["status"] == "complete"
    assert scored["n"] == expected_n
    assert scored["rmae"] == 0
    assert all(r["status"] == "incomplete" for r in rows if r is not scored)
    assert len(rows) == 22

    again = backtest.score_delivery_day(delivery_day, cutoff)
    saved = pd.read_parquet(
        products.SCORES_DIR / "delivery" / f"{delivery_day}.parquet"
    )
    assert again == rows
    assert len(saved) == 22
    assert (
        saved.duplicated(["delivery_day", "origin_day", "gate", "span", "target"]).sum()
        == 0
    )

    versions.loc[grid[0], "available_at"] = cutoff + timedelta(hours=1)
    unchanged = backtest.score_delivery_day(delivery_day, cutoff)
    assert (
        unchanged == rows
    )  # later truth revisions cannot rewrite the original evaluation


def test_score_delivery_day_rejects_naive_cutoff():
    from delukit.backtest import score_delivery_day

    with pytest.raises(ValueError, match="timezone-aware"):
        score_delivery_day(date(2026, 1, 1), datetime(2026, 1, 2, 15, 30))
    with pytest.raises(ValueError, match="has not ended"):
        score_delivery_day(
            date(2026, 1, 2), datetime(2026, 1, 2, 15, 30, tzinfo=BERLIN)
        )
    with pytest.raises(ValueError, match="has not occurred"):
        score_delivery_day(
            date(2099, 1, 1), datetime(2099, 1, 2, 15, 30, tzinfo=BERLIN)
        )


def test_partial_truth_is_reported_without_a_metric(tmp_dirs, monkeypatch):
    import delukit.backtest as backtest
    from delukit.core.config import products

    monkeypatch.setattr(products, "TARGETS", ("load_actual_mw",))
    delivery_day = date(2026, 1, 6)
    grid = quarter_grid(delivery_day)
    cutoff = datetime(2026, 1, 7, 15, 30, tzinfo=BERLIN)
    truth = pd.DataFrame(
        {
            "load_actual_mw": [100.0] * 95 + [None],
            "available_at": [cutoff - timedelta(hours=1)] * 96,
        },
        index=grid,
    )
    monkeypatch.setattr(
        backtest,
        "load",
        lambda: SimpleNamespace(
            data_parts=[SimpleNamespace(feature_names=["load_actual_mw"], data=truth)]
        ),
    )
    path = (
        tmp_dirs["forecasts"]
        / "2026-01-05"
        / "0530_d1"
        / "load_actual_mw__xgboost.parquet"
    )
    path.parent.mkdir(parents=True)
    pd.DataFrame(
        {
            "quantile_P10": [90.0] * 96,
            "quantile_P50": [100.0] * 96,
            "quantile_P90": [110.0] * 96,
        },
        index=grid,
    ).to_parquet(path)

    rows = backtest.score_delivery_day(delivery_day, cutoff)
    score = next(r for r in rows if r["gate"] == "0530" and r["span"] == "d1")
    assert score["expected_n"] == 96
    assert score["truth_n"] == 95
    assert score["status"] == "incomplete"
    assert score["reason"] == "truth_unavailable_at_cutoff"
    assert score["rmae"] is None and score["rcrps"] is None
