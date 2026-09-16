"""EXAA day-ahead prices (sequence 2) — raw XML."""


def fetch_day(source, day, area) -> dict[str, str]:
    text = source._request_xml(
        source.client.query_day_ahead_prices, area, *source._day_window(day), sequence=2
    )
    return {"day_ahead_price/2": text}
