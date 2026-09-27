import argparse
from datetime import date, datetime

import dagster as dg

from delukit.core.clean import UTC
from delukit.dagster_app import definitions as defs


def _key(day: date, gate: str) -> str:
    return f"{day.isoformat()}|{gate}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Materialize delukit assets once.")
    parser.add_argument("action", choices=["sync", "forecast", "scores", "train"])
    parser.add_argument("--date", default=None, help="Berlin day YYYY-MM-DD")
    parser.add_argument("--gate", choices=["0530", "1130"], default="0530")
    args = parser.parse_args()

    day = (
        date.fromisoformat(args.date)
        if args.date
        else datetime.now(UTC).astimezone(defs.BERLIN).date()
    )
    if args.action == "sync":
        result = dg.materialize([defs.raw_data, defs.clean_data, defs.versioned_data])
    elif args.action == "forecast":
        result = dg.materialize(
            [
                defs.raw_data,
                defs.clean_data,
                defs.versioned_data,
                defs.forecast_gate,
            ],
            partition_key=_key(day, args.gate),
        )
    elif args.action == "scores":
        result = dg.materialize(
            [
                defs.raw_data,
                defs.clean_data,
                defs.versioned_data,
                defs.daily_score_reconciliation,
            ]
        )
    else:
        result = dg.materialize(
            [
                defs.raw_data,
                defs.clean_data,
                defs.versioned_data,
                defs.registered_models,
            ]
        )
    if not result.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
