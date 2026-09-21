import threading

from dotenv import load_dotenv

from delukit.core import (
    BASE_DIR,
    REFRESH_DAYS,
    START,
    end_date,
    setup_logging,
    sync_progress,
)
from delukit.core.config.calendar import calendar_countries
from delukit.core.config.entsoe import entsoe_params
from delukit.core.config.smard import smard_modules
from delukit.core.config.weather import (
    WEATHER_FORECAST_DAYS,
    WEATHER_LOCATIONS,
    WEATHER_MODEL,
)
from delukit.core.log import LOG_FILE
from delukit.sources import calendar, entsoe, smard, weather

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


def show_header(end):
    rows = [
        ("Sources", ", ".join(SOURCES)),
        ("Area", "DE-LU"),
        ("Window", f"{START} -> {end}"),
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
    print("  // DELUKIT :: bronze sync //")
    print("-" * width)
    print("\n".join(body))
    print(bar)


def main():
    log = setup_logging()
    end = end_date()

    show_header(end)

    days = (end - START).days + 1
    totals = {
        source: len(categories) * days for source, (_, categories) in SOURCES.items()
    }
    counts = {}

    with sync_progress(totals) as advance:

        def track(source, category, day, state):
            advance(source, day, state)
            if state in ("no_data", "failed"):
                log.info("%s %s %s: %s", source, day, category, state)
            elif state == "updated":
                log.info("%s %s %s: revised upstream", source, day, category)

        def run(source, module):
            counts[source] = module.sync(
                START, end, on_each=lambda c, d, s: track(source, c, d, s)
            )

        # Different hosts, independent limits: run both pools at once.
        threads = [
            threading.Thread(target=run, args=(source, module))
            for source, (module, _) in SOURCES.items()
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    log.info(counts)


if __name__ == "__main__":
    main()
