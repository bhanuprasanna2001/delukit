"""Actual generation per production type — raw XML, one doc per psr type."""

from entsoe.exceptions import NoMatchingDataError


def fetch_day(source, day, area, psr_types=()) -> dict[str, str]:
    raws: dict[str, str] = {}
    for psr_type in psr_types:
        try:
            text = source._request_xml(
                source.client.query_generation,
                area,
                *source._day_window(day),
                psr_type=psr_type,
            )
        except NoMatchingDataError:
            continue
        raws[f"generation_actual/{psr_type}"] = text
    return raws
