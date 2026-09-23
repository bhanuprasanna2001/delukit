"""Availability-stamped dataset: data/clean -> data/versioned.

Build splits the latest clean tables into one TimeSeriesDataset part per
publication event. It assigns each row an ``available_at`` from the rules in
core/config/availability.py. Validate replays the 05:30 and 11:30 gates and
checks those configured rules.

ENTSO-E and SMARD retain one daily payload per category. Historical parts
therefore contain the latest retained revision, not the revision proven to
exist at a past gate. Weather retains separate forecast runs.
"""

import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from datetime import time as dtime
from statistics import mean

import pandas as pd
from openstef_core.datasets import TimeSeriesDataset, VersionedTimeSeriesDataset

from delukit.core.clean import BERLIN, UTC, day_bounds
from delukit.core.config import CLEAN_DIR, VERSIONED_DIR
from delukit.core.config.availability import (
    CALENDAR_AVAILABLE_AT,
    ENTSOE_ACTUALS_DELAY,
    ENTSOE_LOAD_FC_PUBLISH,
    EXAA_PUBLISH,
    GATES,
    SDAC_PUBLISH,
    SMARD_ACTUALS_DELAY,
    SMARD_DAY_AHEAD_PUBLISH,
    TSO_RENEWABLES_PUBLISH,
    WEATHER_RUN_PUBLISH_UTC,
)
from delukit.core.config.products import GEN_TOTAL_COLUMNS
from delukit.core.config.weather import WEATHER_FIELDS

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
    out = df[columns]
    out = out.assign(available_at=out.index + delay)
    return TimeSeriesDataset(out, sample_interval=QUARTER)


def _published(df: pd.DataFrame, columns: list[str], wall: dtime) -> TimeSeriesDataset:
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
    drop = [c for c in TIME_COLS if c in df.columns]
    # Subdivision names are identifiers, not features (trees take no strings).
    drop += [
        c
        for c in df.columns
        if c not in drop and pd.api.types.is_string_dtype(df[c].dtype)
    ]
    out = df.drop(columns=drop)
    # HolidayFeatureAdder always adds its own `is_holiday`; ours is the
    # DE-LU aggregate, so it lives under its own name.
    out = out.rename(columns={"is_holiday": "is_holiday_delu"})
    out = out.assign(available_at=pd.Timestamp(CALENDAR_AVAILABLE_AT, tz=UTC))
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


def build() -> None:
    """data/clean -> data/versioned/<part>.parquet."""
    VERSIONED_DIR.mkdir(parents=True, exist_ok=True)
    parts: dict[str, TimeSeriesDataset] = {}
    parts.update(_entsoe_parts(pd.read_parquet(CLEAN_DIR / "entsoe.parquet")))
    parts.update(_smard_parts(pd.read_parquet(CLEAN_DIR / "smard.parquet")))
    parts["calendar"] = _calendar_part(pd.read_parquet(CLEAN_DIR / "calendar.parquet"))
    parts["weather"] = _weather_part(pd.read_parquet(CLEAN_DIR / "weather.parquet"))

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


# -------------------------------------------------------------------------- validate


def _gate(day: date, wall: dtime) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(day, wall, BERLIN)).tz_convert(UTC)


def _visible(part: TimeSeriesDataset, day: date, gate: pd.Timestamp) -> pd.DataFrame:
    start, end, _ = day_bounds(day)
    return part.filter_by_range(start, end).filter_by_available_before(gate).data


def _data_days(part: TimeSeriesDataset, column: str | None = None) -> set[date]:
    """Berlin days where the part carries data (one column, or any feature)."""
    frame = part.data[[column]] if column else part.data[part.feature_names]
    stamps = frame.dropna(how="any" if column else "all").index
    return set(stamps.tz_convert(BERLIN).date)


def _validation_days(parts: dict[str, TimeSeriesDataset]) -> tuple[list[date], Counter]:
    """Days where the whole contract is checkable, plus why others are not."""
    truth = _data_days(parts["entsoe_actuals"], "load_actual_mw")
    # Runs issued on D-1 and D must exist: they are the freshest weather
    # versions visible at the 05:30 and 11:30 gates on D.
    weather_runs = set(parts["weather"].data["available_at"].dt.date)
    needs = {
        "smard_actuals": _data_days(parts["smard_actuals"], "load_actual_mwh"),
        "sdac": _data_days(parts["sdac"], "price_sdac_seq1_eur_mwh"),
        "tso_day_ahead": _data_days(parts["tso_day_ahead"], "gen_forecast_total_mw"),
        "exaa": _data_days(parts["exaa"], "price_exaa_eur_mwh"),
        "entsoe_day_ahead": _data_days(parts["entsoe_day_ahead"], "load_forecast_mw"),
        "weather": _data_days(parts["weather"]),
        "calendar": _data_days(parts["calendar"], "is_holiday_delu"),
    }
    days, skipped = [], Counter()
    for day in sorted(truth):
        missing = [
            name
            for name, covered in (
                ("smard_actuals", day in needs["smard_actuals"]),
                ("sdac", day in needs["sdac"]),
                ("tso_day_ahead", day in needs["tso_day_ahead"]),
                ("exaa", day + timedelta(days=1) in needs["exaa"]),
                (
                    "entsoe_day_ahead",
                    day + timedelta(days=1) in needs["entsoe_day_ahead"],
                ),
                (
                    "weather",
                    day + timedelta(days=1) in needs["weather"]
                    and day + timedelta(days=FORECAST_HORIZON_DAYS) in needs["weather"],
                ),
                (
                    "weather_runs",
                    day - timedelta(days=1) in weather_runs and day in weather_runs,
                ),
                (
                    "calendar",
                    day + timedelta(days=FORECAST_HORIZON_DAYS) in needs["calendar"],
                ),
            )
            if not covered
        ]
        if missing:
            skipped["+".join(missing)] += 1
        else:
            days.append(day)
    return days, skipped


def validate() -> int:
    """Replay historical gates and check the configured availability rules."""
    ds = load()
    parts = dict(
        zip(
            (p.stem for p in sorted(VERSIONED_DIR.glob("*.parquet"))),
            ds.data_parts,
            strict=True,
        )
    )

    days, skipped = _validation_days(parts)
    failures: Counter = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    coverage: dict[str, list[float]] = defaultdict(list)

    def fail(check: str, day: date, wall: dtime, detail: str) -> None:
        failures[check] += 1
        if len(examples[check]) < 5:
            examples[check].append(f"{day.isoformat()} {wall:%H:%M} {detail}")

    for day in days:
        # Calendar must cover the whole D+1..D+10 horizon at every gate.
        start, _, _ = day_bounds(day + timedelta(days=1))
        end, _, _ = day_bounds(day + timedelta(days=FORECAST_HORIZON_DAYS + 1))
        expected = sum(
            day_bounds(day + timedelta(days=i))[2]
            for i in range(1, FORECAST_HORIZON_DAYS + 1)
        )
        got = len(parts["calendar"].filter_by_range(start, end).data)
        if got != expected:
            fail("calendar_d1_d10", day, GATES[0], f"{got}/{expected} quarters")

        for wall in GATES:
            gate = _gate(day, wall)
            morning = wall == GATES[0]

            for name, delay in (
                ("entsoe", ENTSOE_ACTUALS_DELAY),
                ("smard", SMARD_ACTUALS_DELAY),
            ):
                cutoff = gate - delay
                rows = _visible(parts[f"{name}_actuals"], day, gate)
                if rows.empty:
                    fail(f"{name}_actuals", day, wall, "no quarters visible")
                elif not cutoff - timedelta(hours=2) <= rows.index.max() <= cutoff:
                    cutoff_berlin = cutoff.tz_convert(BERLIN)
                    last = rows.index.max().tz_convert(BERLIN)
                    fail(
                        f"{name}_actuals",
                        day,
                        wall,
                        f"last quarter {last:%Y-%m-%d %H:%M} != ~{cutoff_berlin:%H:%M}",
                    )

            visibility = [
                # part, target day, column, expected visible at this gate, check
                (
                    "exaa",
                    day + timedelta(days=1),
                    "price_exaa_eur_mwh",
                    not morning,
                    "exaa_d1",
                ),
                (
                    "entsoe_day_ahead",
                    day + timedelta(days=1),
                    "load_forecast_mw",
                    not morning,
                    "entsoe_fc_d1",
                ),
                (
                    "smard_day_ahead",
                    day + timedelta(days=1),
                    "load_forecast_mwh",
                    False,
                    "smard_fc_d1",
                ),
                (
                    "sdac",
                    day + timedelta(days=1),
                    "price_sdac_seq1_eur_mwh",
                    False,
                    "sdac_d1",
                ),
                ("sdac", day, "price_sdac_seq1_eur_mwh", True, "sdac_d0"),
                (
                    "tso_day_ahead",
                    day + timedelta(days=1),
                    "gen_forecast_total_mw",
                    False,
                    "tso_d1",
                ),
                ("tso_day_ahead", day, "gen_forecast_total_mw", True, "tso_d0"),
            ]
            for part_name, target, column, expected_visible, check in visibility:
                count = _visible(parts[part_name], target, gate)[column].count()
                if bool(count) != expected_visible:
                    state = f"visible ({count} quarters)" if count else "invisible"
                    fail(check, day, wall, state)
                elif expected_visible:
                    coverage[check].append(count / day_bounds(target)[2])

            weather = _visible(parts["weather"], day + timedelta(days=1), gate)
            if weather.empty:
                fail("weather_d1", day, wall, "no run covers D+1")
            else:
                expected_run = day - timedelta(days=1) if morning else day
                newest_run = weather["available_at"].max().date()
                if newest_run != expected_run:
                    fail(
                        "weather_d1",
                        day,
                        wall,
                        f"freshest run {newest_run} != {expected_run}",
                    )
                coverage["weather_d1"].append(
                    weather.index.nunique() / day_bounds(day + timedelta(days=1))[2]
                )
            far = _visible(
                parts["weather"], day + timedelta(days=FORECAST_HORIZON_DAYS), gate
            )
            if far.empty:
                fail(
                    "weather_d10", day, wall, f"no run covers D+{FORECAST_HORIZON_DAYS}"
                )
            else:
                coverage["weather_d10"].append(
                    far.index.nunique()
                    / day_bounds(day + timedelta(days=FORECAST_HORIZON_DAYS))[2]
                )

    print(f"validated {len(days)} days x {len(GATES)} gates ({days[0]} .. {days[-1]})")
    for reason, count in skipped.most_common():
        print(f"  skipped {count:>3} days: missing {reason}")
    for check, ratios in coverage.items():
        print(f"  coverage {check}: mean {mean(ratios):.1%}, min {min(ratios):.1%}")

    if failures:
        for check, count in failures.most_common():
            print(f"FAILED {check}: {count} gate-days")
            for line in examples[check]:
                print(f"    {line}")
        return 1
    print("all availability checks passed")
    return 0


def main() -> None:
    if "--validate-only" not in sys.argv:
        build()
    sys.exit(validate())


if __name__ == "__main__":
    main()
