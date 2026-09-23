import threading
from datetime import date, timedelta

from dotenv import load_dotenv

from delukit.core import (
    BASE_DIR,
    REFRESH_DAYS,
    START,
    end_date,
    setup_logging,
    sync_progress,
)
from delukit.core.config.calendar import CALENDAR_AHEAD_DAYS, calendar_countries
from delukit.core.config.entsoe import entsoe_params
from delukit.core.config.smard import smard_modules
from delukit.core.config.weather import (
    WEATHER_FORECAST_DAYS,
    WEATHER_LOCATIONS,
    WEATHER_MODEL,
)
from delukit.core.log import LOG_FILE
from delukit.sources import calendar, entsoe, smard, weather
from delukit.sources.observations import bootstrap_legacy

# energy_charts is implemented (sources/energy_charts.py, standalone-runnable)
# but not synced until downstream needs it; enable with:
#   "energy_charts": (energy_charts, energy_charts_categories),

SOURCES = {
    "entsoe": (entsoe, entsoe_params),
    "smard": (smard, smard_modules),
    "weather": (weather, WEATHER_LOCATIONS),
    "calendar": (calendar, calendar_countries),
}

load_dotenv()


def show_header(start, end):
    rows = [
        ("Sources", ", ".join(SOURCES)),
        ("Area", "DE-LU"),
        ("Window", f"{start} -> {end}"),
        ("Refresh", f"last {REFRESH_DAYS} days re-fetched"),
        ("Destination", f"{BASE_DIR}/<day>/<source>/<category>/data.*"),
        ("Log", LOG_FILE),
        ("entsoe", ", ".join(entsoe_params)),
        ("smard", ", ".join(smard_modules)),
        ("weather", f"{WEATHER_MODEL}, {WEATHER_FORECAST_DAYS}d, land+sea"),
        ("calendar", f"OpenHolidays {', '.join(calendar_countries)}"),
    ]
    body = [f"  {label:<11} {value}" for label, value in rows]
    width = max(len(line) for line in body)
    bar = "=" * width
    print(bar)
    print("  // DELUKIT :: raw sync //")
    print("-" * width)
    print("\n".join(body))
    print(bar)


def show_summary(counts):
    head = f"  {'source':<10}{'new':>5}{'upd':>5}{'same':>6}{'empty':>7}{'fail':>6}"
    body = [head] + [
        f"  {source:<10}{counts[source]['fetched']:>5}"
        f"{counts[source]['updated']:>5}{counts[source]['unchanged']:>6}"
        f"{counts[source]['no_data']:>7}{counts[source]['failed']:>6}"
        for source in SOURCES
    ]
    width = max(len(line) for line in body)
    bar = "=" * width
    print(bar)
    print("  // DELUKIT :: summary //")
    print("-" * width)
    print("\n".join(body))
    print(bar)


def main(*, start: date | None = None):
    log = setup_logging()
    end = end_date()
    start = start or max(START, end - timedelta(days=REFRESH_DAYS + 1))
    if start < START or start > end:
        raise ValueError(f"source start must be between {START} and {end}")
    legacy = bootstrap_legacy(BASE_DIR)
    if legacy:
        log.info("stamped %d legacy raw files with today's observed time", legacy)

    show_header(start, end)

    days = (end - start).days + 1
    cal_end = max(end, end + timedelta(days=CALENDAR_AHEAD_DAYS - 1))
    cal_days = (cal_end - start).days + 1
    totals = {
        source: len(categories) * (cal_days if source == "calendar" else days)
        for source, (_, categories) in SOURCES.items()
    }
    counts = {}
    errors = {}

    with sync_progress(totals) as advance:

        def track(source, category, day, state):
            advance(source, day, state)
            if state in ("no_data", "failed"):
                log.info("%s %s %s: %s", source, day, category, state)
            elif state == "updated":
                log.info("%s %s %s: revised upstream", source, day, category)

        def run(source, module):
            try:
                counts[source] = module.sync(
                    start, end, on_each=lambda c, d, s: track(source, c, d, s)
                )
            except Exception as exc:  # noqa: BLE001 - carry worker failure to caller
                errors[source] = exc

        # Different hosts, independent limits: run both pools at once.
        threads = [
            threading.Thread(target=run, args=(source, module))
            for source, (module, _) in SOURCES.items()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    if errors:
        names = ", ".join(sorted(errors))
        raise RuntimeError(f"source sync failed: {names}") from next(
            iter(errors.values())
        )
    show_summary(counts)
    failed = {name: c["failed"] for name, c in counts.items() if c["failed"]}
    if failed:
        raise RuntimeError(f"source fetch failures: {failed}")
    for source in SOURCES:
        c = counts[source]
        log.info(
            "summary %s: new=%d upd=%d same=%d empty=%d fail=%d",
            source,
            c["fetched"],
            c["updated"],
            c["unchanged"],
            c["no_data"],
            c["failed"],
        )


def cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Refresh provider observations.")
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        help="Berlin first day for a deliberate historical repair (default: recent window)",
    )
    args = parser.parse_args()
    main(start=args.since)


if __name__ == "__main__":
    cli()
