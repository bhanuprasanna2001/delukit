"""Manual triggers without the daemon: sync, live forecast, or delivery-day scores.

Same code path the schedules use (dg.materialize over the same assets),
for backfills, debugging, or machines without the daemon running.
"""

import argparse
from datetime import date, datetime, timedelta

import dagster as dg

from delukit.core.clean import UTC
from delukit.dagster_app import definitions as defs


def _key(day: date, gate: str) -> str:
    return f"{day.isoformat()}|{gate}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize delukit assets once.")
    parser.add_argument("action", choices=["sync", "forecast", "scores"])
    parser.add_argument(
        "--date",
        default=None,
        help="Berlin forecast origin, or completed delivery day for scores",
    )
    parser.add_argument("--gate", choices=["0530", "1130"], default=None)
    args = parser.parse_args()

    today = datetime.now(UTC).astimezone(defs.BERLIN).date()
    day = (
        date.fromisoformat(args.date)
        if args.date
        else (today - timedelta(days=1) if args.action == "scores" else today)
    )
    if args.action == "sync":
        dg.materialize([defs.raw_data, defs.clean_data, defs.versioned_data])
    elif args.action == "forecast":
        # The gate reads the committed pre-gate refresh, like the schedule.
        dg.materialize(
            [
                defs.forecast_d1,
                defs.forecast_d10,
            ],
            partition_key=_key(day, args.gate or "0530"),
        )
    else:
        if args.gate is not None:
            parser.error("--gate applies only to forecast; scores include both gates")
        dg.materialize(
            [defs.forecast_scores],
            partition_key=day.isoformat(),
        )


if __name__ == "__main__":
    main()
