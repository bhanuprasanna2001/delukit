"""Generation day-ahead forecast — raw JSON, one doc per type.

SMARD forecasts only wind, solar, and aggregates, so this map is smaller
than the actual-generation one. Filter ids verified against SMARD's
market_data_configuration catalog.
"""

from delukit.sources.data_source import SourceError

DAY_AHEAD_FILTERS = {
    "total": 122,
    "solar": 125,
    "wind_onshore": 123,
    "wind_offshore": 3791,
    "other": 715,
    "pv_wind": 5097,
}


def fetch_day_ahead(
    source, day, area, resolution, generation_types=()
) -> dict[str, str]:
    raws: dict[str, str] = {}
    for name in generation_types:
        try:
            filter_id = DAY_AHEAD_FILTERS[name]
        except (KeyError, TypeError):
            raise SourceError(
                f"{source.name}: unknown generation type {name!r} for "
                f"generation_forecast_day_ahead "
                f"(supported: {', '.join(DAY_AHEAD_FILTERS)})"
            ) from None
        raws.update(
            source._day_payload(
                day,
                filter_id,
                f"generation_forecast_day_ahead/{name}",
                area,
                resolution,
            )
        )
    return raws
