"""Wind and solar day-ahead generation forecast — raw XML.

One request covers all wind/solar psr types, so psr_types only matters
for silver-layer filtering.
"""


def fetch_day(source, day, area, psr_types=()) -> dict[str, str]:
    text = source._request_xml(
        source.client.query_wind_and_solar_forecast, area, *source._day_window(day)
    )
    return {"generation_forecast": text}
