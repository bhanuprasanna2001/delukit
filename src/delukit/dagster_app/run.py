"""Manual triggers without the daemon: sync / forecast / scores for a gate.

Same code path the schedules use (dg.materialize over the same assets),
for backfills, debugging, or machines without the daemon running.
"""

import argparse
from datetime import date, datetime

import dagster as dg

from delukit.core.clean import UTC
from delukit.dagster_app import definitions as defs


def _key(day: date, gate: str) -> str:
    return f"{day.isoformat()}|{gate}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize delukit assets once.")
    parser.add_argument("action", choices=["sync", "forecast", "scores"])
    parser.add_argument("--date", default=None, help="Berlin day YYYY-MM-DD")
    parser.add_argument("--gate", choices=["0530", "1130"], default="0530")
    args = parser.parse_args()

    day = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(UTC).astimezone(defs.BERLIN).date()
    )
    if args.action == "sync":
        dg.materialize([defs.raw_data, defs.clean_data, defs.versioned_data])
    elif args.action == "forecast":
        # Full chain like the schedule: sync + rebuild before forecasting.
        dg.materialize(
            [
                defs.raw_data,
                defs.clean_data,
                defs.versioned_data,
                defs.forecast_d1,
                defs.forecast_d10,
            ],
            partition_key=_key(day, args.gate),
        )
    else:
        dg.materialize([defs.forecast_scores], partition_key=_key(day, args.gate))


if __name__ == "__main__":
    main()
