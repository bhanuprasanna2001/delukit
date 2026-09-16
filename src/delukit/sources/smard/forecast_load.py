"""Day-ahead total load forecast — raw JSON."""

FILTER = 411


def fetch_day(source, day, area, resolution) -> dict[str, str]:
    return source._day_payload(day, FILTER, "load_forecast", area, resolution)
