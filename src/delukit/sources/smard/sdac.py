"""SDAC day-ahead prices (DE-LU) — raw JSON, one doc per day."""

FILTER = 4169


def fetch_day(source, day, area, resolution) -> dict[str, str]:
    return source._day_payload(day, FILTER, "day_ahead_price", area, resolution)
