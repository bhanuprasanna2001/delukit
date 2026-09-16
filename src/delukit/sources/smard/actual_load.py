"""Actual total load — raw JSON."""

FILTER = 410


def fetch_day(source, day, area, resolution) -> dict[str, str]:
    return source._day_payload(day, FILTER, "load_actual", area, resolution)
