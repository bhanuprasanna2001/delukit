"""Actual total load — raw XML."""


def fetch_day(source, day, area) -> dict[str, str]:
    text = source._request_xml(source.client.query_load, area, *source._day_window(day))
    return {"load_actual": text}
