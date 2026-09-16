"""SDAC day-ahead prices (DE-LU) — raw JSON, one doc per day."""

PRICE_URL = "https://api.energy-charts.info/price"


def fetch_day(source, day, bidding_zone) -> dict[str, str]:
    start, end = source._day_window(day)
    text = source._request(
        PRICE_URL,
        {"bzn": bidding_zone, "start": start.isoformat(), "end": end.isoformat()},
        allow_404=True,
    )
    if text is None:
        return {}
    return {"day_ahead_price": text}
