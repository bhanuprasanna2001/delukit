"""Conservative point-in-time dataset from the latest clean tables.

Publication rules are lower bounds. Raw response observations provide the
first defensible knowledge time of the current semantic revision. Historical
provider vintages not observed by this repository cannot be reconstructed.
"""

import sys
from datetime import date, datetime, timedelta
from datetime import time as dtime

import pandas as pd
from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset

from delukit.core import config
from delukit.core.clean import BERLIN, UTC, day_bounds
from delukit.core.config import CLEAN_DIR, VERSIONED_DIR
from delukit.core.config.availability import (
    CALENDAR_AVAILABLE_AT,
    ENTSOE_ACTUALS_DELAY,
    ENTSOE_LOAD_FC_PUBLISH,
    EXAA_PUBLISH,
    SDAC_PUBLISH,
    SMARD_ACTUALS_DELAY,
    SMARD_DAY_AHEAD_PUBLISH,
    TSO_RENEWABLES_PUBLISH,
    WEATHER_RUN_PUBLISH_UTC,
)
from delukit.core.config.products import GEN_TOTAL_COLUMNS
from delukit.core.config.weather import WEATHER_FIELDS, WEATHER_LOCATIONS
from delukit.sources.entsoe import _comparable as entsoe_comparable
from delukit.sources.observations import known_at
from delukit.sources.smard import _comparable as smard_comparable

QUARTER = timedelta(minutes=15)
TIME_COLS = ("timestamp_berlin", "date", "quarter")
FORECAST_HORIZON_DAYS = 10  # gates forecast D+1 .. D+10
# ffill limit for the hourly -> quarter grid: 3 expansion quarters plus the
# 4 quarters of the fall-back hour gap (wall-clock API, see sources/weather.py).
WEATHER_FFILL_LIMIT = 7

# --------------------------------------------------------------------------- build


def _delayed(
    df: pd.DataFrame, columns: list[str], delay: timedelta
) -> TimeSeriesDataset:
    """Actuals: known ``delay`` after the quarter they describe."""
    out = df[columns]
    out = out.assign(available_at=out.index + delay)
    return TimeSeriesDataset(out, sample_interval=QUARTER)


def _published(df: pd.DataFrame, columns: list[str], wall: dtime) -> TimeSeriesDataset:
    """Day-ahead curve: all of Berlin day T is published on T-1 at ``wall``."""
    out = df[columns]
    publish_day = pd.to_datetime(out.index.tz_convert(BERLIN).date) - pd.Timedelta(
        days=1
    )
    available = publish_day + pd.Timedelta(hours=wall.hour, minutes=wall.minute)
    available = available.tz_localize(
        BERLIN, ambiguous=True, nonexistent="shift_forward"
    )
    out = out.assign(available_at=available.tz_convert(UTC))
    return TimeSeriesDataset(out, sample_interval=QUARTER)


def _guard_unmapped(
    df: pd.DataFrame, assigned: list[str], skipped: tuple[str, ...] = ()
) -> None:
    """Fail loudly on unmapped columns: clean-schema drift must be a decision."""
    leftover = set(df.columns) - set(TIME_COLS) - set(assigned) - set(skipped)
    if leftover:
        raise ValueError(f"unmapped clean columns: {sorted(leftover)}")


def _entsoe_parts(df: pd.DataFrame) -> dict[str, TimeSeriesDataset]:
    """Measured quarters, day-ahead price curves, TSO forecasts: five events."""
    actuals = sorted(
        c for c in df.columns if c.startswith(("load_actual", "gen_actual"))
    )
    renewables = [
        "gen_forecast_total_mw",
        "solar_forecast_mw",
        "wind_offshore_forecast_mw",
        "wind_onshore_forecast_mw",
    ]
    prices = [
        "price_exaa_eur_mwh",
        "price_sdac_seq1_eur_mwh",
        "price_sdac_seq2_eur_mwh",
    ]
    _guard_unmapped(df, actuals + renewables + ["load_forecast_mw"] + prices)
    return {
        "entsoe_actuals": _delayed(df, actuals, ENTSOE_ACTUALS_DELAY),
        "exaa": _published(df, ["price_exaa_eur_mwh"], EXAA_PUBLISH),
        "sdac": _published(
            df, ["price_sdac_seq1_eur_mwh", "price_sdac_seq2_eur_mwh"], SDAC_PUBLISH
        ),
        "entsoe_day_ahead": _published(
            df, ["load_forecast_mw"], ENTSOE_LOAD_FC_PUBLISH
        ),
        "tso_day_ahead": _published(df, renewables, TSO_RENEWABLES_PUBLISH),
    }


def _smard_parts(df: pd.DataFrame) -> dict[str, TimeSeriesDataset]:
    """Measured quarters (+ derived total) and day-ahead forecasts: two events."""
    actuals = sorted(
        c for c in df.columns if c.startswith(("load_actual", "gen_actual"))
    )
    forecasts = sorted(
        c for c in df.columns if c.startswith(("load_forecast", "gen_forecast"))
    )
    # price_day_ahead_eur_mwh restates the SDAC day-ahead price; entsoe is canonical.
    _guard_unmapped(df, actuals + forecasts, skipped=("price_day_ahead_eur_mwh",))
    actuals_frame = df[actuals].assign(
        gen_actual_total_mwh=df[list(GEN_TOTAL_COLUMNS)].sum(axis=1, min_count=1)
    )
    return {
        "smard_actuals": _delayed(
            actuals_frame, [*actuals, "gen_actual_total_mwh"], SMARD_ACTUALS_DELAY
        ),
        "smard_day_ahead": _published(df, forecasts, SMARD_DAY_AHEAD_PUBLISH),
    }


def _calendar_part(df: pd.DataFrame) -> TimeSeriesDataset:
    # Holiday and school-break flags come from the current OpenHolidays
    # payload. Its historical publication vintage is unknown, so only dates'
    # deterministic properties may enter a historical replay.
    berlin_days = df.index.tz_convert(BERLIN)
    out = pd.DataFrame(
        {
            "day_of_week": berlin_days.dayofweek,
            "is_weekend": berlin_days.dayofweek >= 5,
            "available_at": pd.Timestamp(CALENDAR_AVAILABLE_AT, tz=UTC),
        },
        index=df.index,
    )
    return TimeSeriesDataset(out, sample_interval=QUARTER)


def _weather_part(df: pd.DataFrame) -> TimeSeriesDataset:
    """Wide per location, hourly runs expanded onto the quarter grid."""
    wide = (
        df.reset_index()
        .set_index(["run_day", "timestamp_utc", "location"])[list(WEATHER_FIELDS)]
        .unstack("location")
    )
    wide.columns = [f"{field}__{loc}" for field, loc in wide.columns]
    publish = pd.Timedelta(
        hours=WEATHER_RUN_PUBLISH_UTC.hour, minutes=WEATHER_RUN_PUBLISH_UTC.minute
    )
    frames = []
    for run_day, run in wide.groupby(level="run_day", sort=True):
        hourly = run.droplevel("run_day")
        grid = pd.date_range(
            hourly.index.min(),
            hourly.index.max() + pd.Timedelta(minutes=45),
            freq="15min",
        )
        expanded = hourly.reindex(grid).ffill(limit=WEATHER_FFILL_LIMIT)
        frames.append(
            expanded.assign(available_at=pd.Timestamp(run_day, tz=UTC) + publish)
        )
    return TimeSeriesDataset(pd.concat(frames), sample_interval=QUARTER)


def _observed_part(
    part: TimeSeriesDataset,
    source: str,
    columns: dict[str, list[str]],
    *,
    run_dates: bool = False,
) -> TimeSeriesDataset:
    """Raise non-null rows to the latest raw revision's observed onset."""
    out = part.data.copy()
    days = (
        out["available_at"].dt.date
        if run_dates
        else pd.Series(out.index.tz_convert(BERLIN).date, index=out.index)
    )
    for category, fields in columns.items():
        active = out[fields].notna().any(axis=1)
        for day in days[active].unique():
            mask = active & (days == day)
            path = (
                config.BASE_DIR
                / day.isoformat()
                / source
                / category
                / ("data.json" if source == "weather" else "data.xml")
            )
            body = path.read_bytes()
            comparable = (
                entsoe_comparable(body)
                if source == "entsoe"
                else smard_comparable(body)
                if source == "smard"
                else body
            )
            observed = pd.Timestamp(known_at(path, semantic=comparable))
            out.loc[mask, "available_at"] = out.loc[mask, "available_at"].clip(
                lower=observed
            )
    return TimeSeriesDataset(out, sample_interval=QUARTER)


def build() -> None:
    """data/clean -> data/versioned/<part>.parquet."""
    VERSIONED_DIR.mkdir(parents=True, exist_ok=True)
    parts: dict[str, TimeSeriesDataset] = {}
    parts.update(_entsoe_parts(pd.read_parquet(CLEAN_DIR / "entsoe.parquet")))
    parts.update(_smard_parts(pd.read_parquet(CLEAN_DIR / "smard.parquet")))
    parts["calendar"] = _calendar_part(pd.read_parquet(CLEAN_DIR / "calendar.parquet"))
    parts["weather"] = _weather_part(pd.read_parquet(CLEAN_DIR / "weather.parquet"))

    observed = {
        "entsoe_actuals": (
            "entsoe",
            {
                "load_actual": [
                    c
                    for c in parts["entsoe_actuals"].feature_names
                    if c.startswith("load_actual")
                ],
                "generation_actual": [
                    c
                    for c in parts["entsoe_actuals"].feature_names
                    if c.startswith("gen_actual")
                ],
            },
        ),
        "exaa": ("entsoe", {"EXAA": list(parts["exaa"].feature_names)}),
        "sdac": ("entsoe", {"SDAC": list(parts["sdac"].feature_names)}),
        "entsoe_day_ahead": (
            "entsoe",
            {"load_forecast": list(parts["entsoe_day_ahead"].feature_names)},
        ),
        "tso_day_ahead": (
            "entsoe",
            {
                "generation_forecast": ["gen_forecast_total_mw"],
                "generation_wind_solar_forecast": [
                    c
                    for c in parts["tso_day_ahead"].feature_names
                    if c != "gen_forecast_total_mw"
                ],
            },
        ),
        "smard_actuals": (
            "smard",
            {
                "load_actual": [
                    c
                    for c in parts["smard_actuals"].feature_names
                    if c.startswith("load_actual")
                ],
                "generation_actual": [
                    c
                    for c in parts["smard_actuals"].feature_names
                    if c.startswith("gen_actual")
                ],
            },
        ),
        "smard_day_ahead": (
            "smard",
            {
                "load_forecast": [
                    c
                    for c in parts["smard_day_ahead"].feature_names
                    if c.startswith("load_forecast")
                ],
                "generation_forecast": [
                    c
                    for c in parts["smard_day_ahead"].feature_names
                    if c.startswith("gen_forecast")
                ],
            },
        ),
    }
    for name, (source, columns) in observed.items():
        parts[name] = _observed_part(parts[name], source, columns)
    weather_columns = {
        group: [
            c
            for c in parts["weather"].feature_names
            if c.rpartition("__")[2] in {name for name, _, _ in locations}
        ]
        for group, locations in WEATHER_LOCATIONS.items()
    }
    parts["weather"] = _observed_part(
        parts["weather"], "weather", weather_columns, run_dates=True
    )

    for name in sorted(parts):
        part = parts[name]
        path = VERSIONED_DIR / f"{name}.parquet"
        tmp = path.with_suffix(".tmp")
        part.to_parquet(tmp)
        tmp.replace(path)
        print(
            f"versioned {name:<18} {len(part.data):>9,} rows x {len(part.feature_names):>3} features"
        )


def load() -> VersionedTimeSeriesDataset:
    """Read back data/versioned as one openstef VersionedTimeSeriesDataset."""
    paths = sorted(VERSIONED_DIR.glob("*.parquet"))
    return VersionedTimeSeriesDataset(
        [
            TimeSeriesDataset.read_parquet(path, sample_interval=QUARTER)
            for path in paths
        ]
    )


def assert_replayable(start: datetime, end: datetime) -> None:
    """Reject strict replay when latest-only clean cannot prove the first origin."""
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("replay requires ordered timezone-aware endpoints")
    first = start.astimezone(UTC)
    last_day = (end.astimezone(BERLIN) + timedelta(days=FORECAST_HORIZON_DAYS)).date()
    found = False
    for path in config.BASE_DIR.glob("????-??-??/*/*/data.*"):
        if path.parent.parent.name not in ("entsoe", "smard", "weather"):
            continue
        if date.fromisoformat(path.parts[-4]) > last_day:
            continue
        found = True
        body = path.read_bytes()
        source = path.parent.parent.name
        semantic = (
            entsoe_comparable(body)
            if source == "entsoe"
            else smard_comparable(body)
            if source == "smard"
            else body
        )
        observed = known_at(path, semantic=semantic)
        if observed > first:
            raise ValueError(
                f"strict replay starts before latest observed source vintage: {path}; "
                "use a later window with proven observations"
            )
    if not found:
        raise ValueError("strict replay has no observed source vintages")


# -------------------------------------------------------------------------- validate


def _gate(day: date, wall: dtime) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day, wall, BERLIN)).tz_convert(UTC)


def _visible(part: TimeSeriesDataset, day: date, gate: pd.Timestamp) -> pd.DataFrame:
    """Rows describing ``day`` that were already visible at ``gate``."""
    start, end, _ = day_bounds(day)
    return part.filter_by_range(start, end).filter_by_available_before(gate).data


def _data_days(part: TimeSeriesDataset, column: str | None = None) -> set[date]:
    """Berlin days where the part carries data (one column, or any feature)."""
    frame = part.data[[column]] if column else part.data[part.feature_names]
    stamps = frame.dropna(how="any" if column else "all").index
    return set(stamps.tz_convert(BERLIN).date)


def validate() -> int:
    """Check conservative availability bounds without asserting lost history."""
    parts = dict(
        zip(
            (p.stem for p in sorted(VERSIONED_DIR.glob("*.parquet"))),
            load().data_parts,
            strict=True,
        )
    )
    required = {
        "entsoe_actuals",
        "exaa",
        "sdac",
        "entsoe_day_ahead",
        "tso_day_ahead",
        "smard_actuals",
        "smard_day_ahead",
        "calendar",
        "weather",
    }
    if set(parts) != required:
        print(f"invalid versioned parts: {sorted(set(parts) ^ required)}")
        return 1

    failures = []
    for name, part in parts.items():
        data = part.data
        if data.empty or data["available_at"].isna().any():
            failures.append(f"{name}: empty or missing availability")
        elif data["available_at"].dt.tz is None:
            failures.append(f"{name}: availability lacks timezone")
        print(f"versioned {name}: {len(data):,} rows")

    for name, delay in (
        ("entsoe_actuals", ENTSOE_ACTUALS_DELAY),
        ("smard_actuals", SMARD_ACTUALS_DELAY),
    ):
        part = parts[name]
        populated = part.data[part.feature_names].notna().any(axis=1)
        if (
            part.data.loc[populated, "available_at"]
            < part.data.index[populated] + delay
        ).any():
            failures.append(f"{name}: before measured publication lower bound")

    for name, wall in (
        ("exaa", EXAA_PUBLISH),
        ("sdac", SDAC_PUBLISH),
        ("entsoe_day_ahead", ENTSOE_LOAD_FC_PUBLISH),
        ("tso_day_ahead", TSO_RENEWABLES_PUBLISH),
        ("smard_day_ahead", SMARD_DAY_AHEAD_PUBLISH),
    ):
        part = parts[name]
        expected = _published(
            pd.DataFrame({"value": 0}, index=part.data.index), ["value"], wall
        ).data["available_at"]
        if (part.data["available_at"].array < expected.array).any():
            failures.append(f"{name}: before day-ahead publication lower bound")

    if failures:
        for message in failures:
            print(f"FAILED {message}")
        return 1
    print(
        "availability lower bounds passed; unobserved historical vintages remain unavailable"
    )
    return 0


def main() -> None:
    if "--validate-only" not in sys.argv:
        build()
    sys.exit(validate())


if __name__ == "__main__":
    main()
