"""Slot-aware feature snapshots: data/features/<asof>/<slot>/features.parquet.

One snapshot = training history + forecast horizon for a single 05:30 or
11:30 Berlin slot. Point-in-time correct: every value was knowable at slot.

Publication rules (verified: ENTSO-E DDD, SMARD user guide, EXAA trading
rules, EPEX/SDAC timelines, Open-Meteo docs + live probe; D = Berlin date):

- metered actuals: usable up to slot - 75min (ENTSO-E) / slot - 180min
  (SMARD; ticker lags ~3h, reported-only figures). Targets masked the same.
- auction prices (SDAC seq1, EXAA, SMARD day-ahead): known once published
  (SDAC ~13:30, EXAA 10:20, both D-1). Rest of today kept; staleness does
  not apply to auctions. SDAC seq1 is the sole price target.
- TSO forecasts: ENTSO-E load 10:00 D-1 (D+1 visible at 11:30), SMARD load
  post-auction ~13:00 D-1, wind/solar/total 18:00 D-1. Rest of today kept.
- weather: freshest 00z run available 6h+ before slot (00z accessible
  ~04-06Z; 05:30 uses D-1, 11:30 uses D). Zonal land/sea means.
- calendar: known far ahead, always joined incl. subdivision detail.

Derived: residual load actual + forecast (SMARD definition), SDAC 1/2/3/7d
lags keyed by (date, quarter, fold-occurrence) so DST fall-back folds don't
collapse, latest_value/minutes_since_latest per key stream. Cyclical
encodings stay a forecast-step concern (OpenSTEF).

Known limitation: ENTSO-E/SMARD history holds latest revisions (providers
revise in place; bronze keeps the newest), not as-published vintages, so
backtests are mildly optimistic on revised quarters.
"""

import argparse
from datetime import date, datetime, timedelta
from datetime import time as dtime

import pandas as pd

from delukit.core.clean import BERLIN, CLEAN_DIR, UTC, master_index, raw_days

FEATURES_DIR = "data/features"

SLOT_HOURS = {"0530": (5, 30), "1130": (11, 30)}
FORECAST_DAYS = 10  # delivery D+1..D+10; day 1 is the day-ahead
ACTUALS_LAG_ENTSOE = timedelta(minutes=75)
ACTUALS_LAG_SMARD = timedelta(minutes=180)
WX_RUN_LAG = timedelta(hours=6)  # 00z runs usable from ~06Z

# Publication hour/minute on D-1 (Berlin) per product family.
PUBLICATION = {
    "entsoe_load_forecast": (10, 0),
    "smard_load_forecast": (13, 0),  # submitted post-auction D-1
    "tso_wind_solar": (18, 0),
    "exaa": (10, 20),
    "sdac": (13, 30),
}

WX_FIELDS = (
    "temperature_2m",
    "wind_speed_100m",
    "wind_direction_100m",
    "shortwave_radiation",
    "cloud_cover",
)

# Nuclear phased out (always NaN since 2023); excluded, not imputed.
GEN_ACTUAL_COLS = (
    "gen_actual_biomass_mwh",
    "gen_actual_hydropower_mwh",
    "gen_actual_wind_offshore_mwh",
    "gen_actual_wind_onshore_mwh",
    "gen_actual_photovoltaics_mwh",
    "gen_actual_other_renewable_mwh",
    "gen_actual_lignite_mwh",
    "gen_actual_hard_coal_mwh",
    "gen_actual_fossil_gas_mwh",
    "gen_actual_hydro_pumped_storage_mwh",
    "gen_actual_other_conventional_mwh",
)

LATEST_STREAMS = (
    "load_actual_mw",
    "price_sdac_seq1_eur_mwh",
    "gen_total_mwh",
    "gen_wind_onshore_mwh",
    "gen_wind_offshore_mwh",
    "gen_photovoltaics_mwh",
)

LOC_GROUP = {
    "land": (
        "emden", "bremen", "hamburg", "kiel", "rostock", "hanover", "berlin",
        "muenster", "kassel", "leipzig", "dresden", "cologne", "frankfurt",
        "erfurt", "nuremberg", "luxembourg", "stuttgart", "freiburg",
        "munich", "passau",
    ),
    "sea": (
        "north_sea_west", "north_sea_centre", "north_sea_east",
        "baltic_west", "baltic_east",
    ),
}
GROUP_OF = {loc: grp for grp, locs in LOC_GROUP.items() for loc in locs}


def slot_datetime(asof: date, slot: str) -> datetime:
    hour, minute = SLOT_HOURS[slot]
    return datetime.combine(asof, dtime(hour, minute), BERLIN).astimezone(UTC)


def _published(
    delivery: pd.Series, slot_dt: datetime, hour: int, minute: int, day_offset: int = 1
) -> pd.Series:
    """True where the product for each delivery day was published by slot."""
    publish = [
        datetime.combine(d - timedelta(days=day_offset), dtime(hour, minute), BERLIN)
        .astimezone(UTC)
        for d in delivery
    ]
    return pd.Series(slot_dt >= pd.DatetimeIndex(publish), index=delivery.index)


def _weather_best_known(slot_dt: datetime, grid: pd.DatetimeIndex) -> pd.DataFrame:
    """Zonal means from the freshest runs usable at slot time."""
    wx = pd.read_parquet(CLEAN_DIR / "weather.parquet")
    usable_run = pd.to_datetime(wx["available_at"], utc=True) + WX_RUN_LAG <= slot_dt
    wx = wx[usable_run]
    if wx.empty:
        return pd.DataFrame(index=grid)
    # Freshest run per valid hour x location, then zonal means.
    ordered = wx.sort_values("available_at")
    best = ordered.groupby([ordered.index, "location"]).tail(1)
    best["grp"] = best["location"].map(GROUP_OF)
    agg = best.groupby([best.index, "grp"])[list(WX_FIELDS)].mean().unstack("grp")
    run_of = best.groupby(best.index)["run_day"].agg(lambda s: s.mode().iloc[0])
    out = pd.DataFrame(index=grid)
    out["wx_run_day"] = run_of.reindex(grid, method="ffill", limit=96)
    for field in WX_FIELDS:
        for grp in ("land", "sea"):
            col = f"wx_{grp}_{field}"
            series = agg[(field, grp)] if (field, grp) in agg.columns else None
            out[col] = (
                series.reindex(grid, method="ffill", limit=96)
                if series is not None
                else float("nan")
            )
    return out


def _price_lags(
    full: pd.Series, delivery_day: pd.Series, slot_dt: datetime, grid: pd.DatetimeIndex
) -> pd.DataFrame:
    """SDAC-seq1 same-quarter lags 1/2/3/7d, masked by auction publication.

    Keyed by (date, quarter, fold-occurrence): on DST fall-back days the
    02:00-02:45 wall quarters exist twice and must not collapse.
    """
    berlin_q = grid.tz_convert(BERLIN)
    dates_iso = delivery_day.dt.date.astype(str)
    quarters = berlin_q.hour * 4 + berlin_q.minute // 15 + 1
    occ = (
        pd.Series(0, index=grid)
        .groupby([list(dates_iso), list(quarters)])
        .cumcount()
    )
    lookup = {
        (d, q, o): v
        for d, q, o, v in zip(dates_iso, quarters, occ, full.values)
        if pd.notna(v)  # skip NaN history
    }
    out = pd.DataFrame(index=grid)
    hour, minute = PUBLICATION["sdac"]
    for lag in (1, 2, 3, 7):
        lag_dates = (delivery_day - pd.to_timedelta(lag, unit="D")).dt.date.astype(str)
        values = [
            lookup.get((d, q, o), lookup.get((d, q, 0), float("nan")))
            for d, q, o in zip(lag_dates, quarters, occ)
        ]
        col = pd.Series(values, index=grid)
        # Lagged value for delivery D is SDAC(D-lag), published 13:30 D-lag-1.
        col = col.where(_published(delivery_day, slot_dt, hour, minute, lag + 1))
        out[f"price_sdac_seq1_lag{lag}d_eur_mwh"] = col
    return out


def _latest(series: pd.Series, slot_dt: datetime) -> tuple[float, float]:
    """Last knowable value + its age in minutes (NaN, NaN when empty)."""
    known = series.dropna()
    if known.empty:
        return float("nan"), float("nan")
    stamp = known.index.max()
    return known.loc[stamp], (slot_dt - stamp).total_seconds() / 60


def build_snapshot(asof: date, slot: str, lookback_days: int | None = None):
    """Assemble and write one slot snapshot, returning its path."""
    from pathlib import Path

    slot_dt = slot_datetime(asof, slot)
    if lookback_days is None:  # full available history
        hist = [d for d in raw_days() if d < asof]
    else:
        hist = [asof - timedelta(days=i) for i in range(lookback_days, 0, -1)]
    days = hist + [asof + timedelta(days=i) for i in range(FORECAST_DAYS + 1)]
    grid = master_index(days)

    entsoe = pd.read_parquet(CLEAN_DIR / "entsoe.parquet").reindex(grid)
    smard = pd.read_parquet(CLEAN_DIR / "smard.parquet").reindex(grid)
    calendar = pd.read_parquet(CLEAN_DIR / "calendar.parquet").reindex(grid)

    past = pd.Series(grid <= slot_dt, index=grid)
    usable_e = pd.Series(grid <= slot_dt - ACTUALS_LAG_ENTSOE, index=grid)
    usable_s = pd.Series(grid <= slot_dt - ACTUALS_LAG_SMARD, index=grid)
    berlin = grid.tz_convert(BERLIN)
    delivery_day = pd.Series(pd.to_datetime(berlin.date), index=grid)

    df = pd.DataFrame(
        {
            "timestamp_berlin": berlin,
            "date": berlin.strftime("%Y-%m-%d"),
            "quarter": berlin.hour * 4 + berlin.minute // 15 + 1,
            "slot": slot,
        },
        index=grid,
    )
    df.index.name = "timestamp_utc"

    # Metered actuals + targets: staleness cutoffs per source family.
    df["load_actual_mw"] = entsoe["load_actual_mw"].where(usable_e)
    for col in GEN_ACTUAL_COLS:
        short = col.replace("gen_actual_", "gen_")
        df[short] = smard[col].where(usable_s)
    df["gen_total_mwh"] = smard[list(GEN_ACTUAL_COLS)].where(usable_s).sum(
        axis=1, min_count=11
    )

    # Auction prices: known once published (no metering staleness).
    # SDAC seq1 is history-as-feature here and the sole price target.
    df["price_sdac_seq1_eur_mwh"] = entsoe["price_sdac_seq1_eur_mwh"][
        _published(delivery_day, slot_dt, *PUBLICATION["sdac"])
    ].reindex(grid)
    df["price_exaa_eur_mwh"] = entsoe["price_exaa_eur_mwh"][
        _published(delivery_day, slot_dt, *PUBLICATION["exaa"])
    ].reindex(grid)
    df["price_day_ahead_smard_eur_mwh"] = smard["price_day_ahead_eur_mwh"][
        _published(delivery_day, slot_dt, *PUBLICATION["sdac"])
    ].reindex(grid)

    # Same quantity, other source: explicitly suffixed, never mixed silently.
    df["load_actual_smard_mwh"] = smard["load_actual_mwh"].where(usable_s)
    df["wind_onshore_actual_entsoe_mw"] = entsoe["gen_actual_B19_mw"].where(usable_e)
    df["wind_offshore_actual_entsoe_mw"] = entsoe["gen_actual_B18_mw"].where(usable_e)
    df["solar_actual_entsoe_mw"] = entsoe["gen_actual_B16_mw"].where(usable_e)

    # Residual load actual (SMARD definition).
    df["residual_load_actual_mwh"] = (
        smard["load_actual_mwh"].where(usable_s)
        - smard["gen_actual_photovoltaics_mwh"].where(usable_s)
        - smard["gen_actual_wind_onshore_mwh"].where(usable_s)
        - smard["gen_actual_wind_offshore_mwh"].where(usable_s)
    )

    # SDAC lags with auction-publication masking.
    df = df.join(_price_lags(entsoe["price_sdac_seq1_eur_mwh"], delivery_day, slot_dt, grid))

    # Staleness trackers: latest knowable value + age at slot time.
    for name in LATEST_STREAMS:
        value, age = _latest(df[name], slot_dt)
        df[f"latest_{name}"] = value
        df[f"mins_since_{name}"] = age

    # TSO forecasts: history always; future only when published by slot.
    # Source families stay separate (suffix); rest-of-today published
    # yesterday is kept, not masked.
    def _tso(series: pd.Series, rule: str) -> pd.Series:
        hist = series.where(past)
        hour, minute = PUBLICATION[rule]
        return hist.combine_first(
            series[~past & _published(delivery_day[~past], slot_dt, hour, minute)]
        ).reindex(grid)

    df["load_fc_entsoe_mw"] = _tso(entsoe["load_forecast_mw"], "entsoe_load_forecast")
    df["load_fc_smard_mwh"] = _tso(smard["load_forecast_mwh"], "smard_load_forecast")
    df["wind_onshore_fc_entsoe_mw"] = _tso(
        entsoe["wind_onshore_forecast_mw"], "tso_wind_solar"
    )
    df["wind_offshore_fc_entsoe_mw"] = _tso(
        entsoe["wind_offshore_forecast_mw"], "tso_wind_solar"
    )
    df["solar_fc_entsoe_mw"] = _tso(entsoe["solar_forecast_mw"], "tso_wind_solar")
    df["wind_onshore_fc_smard_mwh"] = _tso(
        smard["gen_forecast_wind_onshore_mwh"], "tso_wind_solar"
    )
    df["wind_offshore_fc_smard_mwh"] = _tso(
        smard["gen_forecast_wind_offshore_mwh"], "tso_wind_solar"
    )
    df["solar_fc_smard_mwh"] = _tso(
        smard["gen_forecast_photovoltaics_mwh"], "tso_wind_solar"
    )
    df["gen_fc_total_smard_mwh"] = _tso(
        smard["gen_forecast_total_mwh"], "tso_wind_solar"
    )
    df["gen_fc_other_smard_mwh"] = _tso(
        smard["gen_forecast_other_mwh"], "tso_wind_solar"
    )
    df["residual_load_fc_smard_mwh"] = (
        df["load_fc_smard_mwh"]
        - df["solar_fc_smard_mwh"]
        - df["wind_onshore_fc_smard_mwh"]
        - df["wind_offshore_fc_smard_mwh"]
    )
    df["residual_load_fc_entsoe_mw"] = (
        df["load_fc_entsoe_mw"]
        - df["solar_fc_entsoe_mw"]
        - df["wind_onshore_fc_entsoe_mw"]
        - df["wind_offshore_fc_entsoe_mw"]
    )

    # Weather (best-known usable run) + calendar with subdivision detail.
    df = df.join(_weather_best_known(slot_dt, grid))
    df = df.join(
        calendar[
            [
                "is_holiday", "is_working_day", "is_bridge_day", "school_holiday",
                "de_school_holiday", "lu_school_holiday",
                "de_school_subdivisions", "lu_school_subdivisions",
                "de_regional_public_subdivisions",
                "lu_regional_public_subdivisions",
            ]
        ]
    )

    path = Path(FEATURES_DIR) / asof.isoformat() / slot / "features.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    df.sort_index().to_parquet(tmp, engine="pyarrow")
    tmp.replace(path)
    return path


def main():
    parser = argparse.ArgumentParser(description="Build one slot feature snapshot.")
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--slot", choices=tuple(SLOT_HOURS), required=True)
    parser.add_argument(
        "--lookback-days", type=int, default=None,
        help="History days before asof; default = full available history.",
    )
    args = parser.parse_args()
    asof = args.asof or datetime.now(BERLIN).date()
    print(build_snapshot(asof, args.slot, args.lookback_days))


if __name__ == "__main__":
    main()
