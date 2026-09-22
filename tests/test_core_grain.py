"""Master grain (Berlin quarters) + parallel runner + product helpers.

Why these: DST miscounts and sister-source leakage silently corrupt every
downstream model; the parallel runner decides fetched/failed counts.
"""

from datetime import date, timedelta


def test_day_bounds_dst_counts():
    from delukit.core.clean import day_bounds

    # 2026-03-29 springs forward (92), 2026-10-25 falls back (100)
    assert day_bounds(date(2026, 1, 5))[2] == 96
    assert day_bounds(date(2026, 3, 29))[2] == 92
    assert day_bounds(date(2026, 10, 25))[2] == 100


def test_quarter_grid_starts_at_berlin_midnight():
    from datetime import date

    from delukit.core.clean import BERLIN, quarter_grid

    grid = quarter_grid(date(2026, 1, 5))
    assert len(grid) == 96
    assert grid[0] == grid[0].tz_convert(BERLIN).normalize().tz_convert("UTC")
    assert (grid[1] - grid[0]) == timedelta(minutes=15)


def test_frame_canonical_columns():
    from datetime import date

    from delukit.core.clean import frame, quarter_grid

    df = frame(quarter_grid(date(2026, 1, 5)))
    assert df.index.name == "timestamp_utc"
    assert df["quarter"].min() == 1 and df["quarter"].max() == 96
    assert (df["date"] == "2026-01-05").all()
    assert df["timestamp_berlin"].dt.date.astype(str).eq("2026-01-05").all()


def test_master_index_empty_and_joins_days():
    from datetime import date

    import pandas as pd

    from delukit.core.clean import master_index

    assert len(master_index([])) == 0
    idx = master_index([date(2026, 1, 5), date(2026, 1, 6)])
    assert len(idx) == 192
    assert isinstance(idx, pd.DatetimeIndex)


def test_run_parallel_counts_and_failed_on_exception():
    from delukit.core.parallel import run_parallel

    def fetch(cat, day):
        if cat == "boom":
            raise RuntimeError("x")
        return "fetched" if cat == "a" else "no_data"

    counts = run_parallel([("a", 1), ("b", 2), ("boom", 3)], fetch, workers=2)
    assert counts["fetched"] == 1
    assert counts["no_data"] == 1
    assert counts["failed"] == 1


def test_run_parallel_rate_limited_stops_early():
    from delukit.core.parallel import RateLimited, run_parallel

    calls = []

    def fetch(cat, day):
        calls.append(cat)
        if cat == "first":
            raise RateLimited("hit")
        return "fetched"

    counts = run_parallel([("first", 1), ("second", 2)], fetch, workers=1)
    assert counts["failed"] >= 1
    assert calls[0] == "first"


def test_feature_exclude_keeps_target_and_known_curves():
    from delukit.core.config.products import feature_exclude

    excluded = feature_exclude("load_actual_mw", "1130", "d1")
    # 1130/d1 is the only product that sees EXAA + ENTSO-E load forecast
    assert "price_exaa_eur_mwh" not in excluded
    assert "load_forecast_mw" not in excluded
    assert "load_actual_mw" not in excluded  # target itself always kept
    # sister-source actuals never valid features
    assert "load_actual_mwh" in excluded
    # other gates see no published curves
    assert "price_exaa_eur_mwh" in feature_exclude("load_actual_mw", "0530", "d1")


def test_product_helpers():
    from delukit.core.config.products import (
        energy_price_column,
        model_id,
        weather_ref,
    )

    assert energy_price_column("price_sdac_seq1_eur_mwh") == "price_exaa_eur_mwh"
    assert energy_price_column("load_actual_mw") == "price_sdac_seq1_eur_mwh"
    assert model_id("t", "0530", "d1") == "t__0530__d1"
    assert weather_ref("temperature_2m") == "temperature_2m__frankfurt"
