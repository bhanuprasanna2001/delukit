"""SDAC day-ahead prices (sequence 1) — raw XML."""


def fetch_day(source, day, area) -> dict[str, str]:
    text = source._request_xml(
        source.client.query_day_ahead_prices, area, *source._day_window(day), sequence=1
    )
    return {"day_ahead_price/1": text}
