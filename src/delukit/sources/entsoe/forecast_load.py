"""Day-ahead total load forecast — raw XML."""


def fetch_day(source, day, area) -> dict[str, str]:
    text = source._request_xml(
        source.client.query_load_forecast, area, *source._day_window(day)
    )
    return {"load_forecast": text}
