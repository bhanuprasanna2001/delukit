"""Actual generation per production type — raw JSON, one doc per type.

Filter ids verified against SMARD's market_data_configuration catalog.
"""

from delukit.sources.data_source import SourceError

GENERATION_FILTERS = {
    "biomass": 4066,
    "wind_onshore": 4067,
    "solar": 4068,
    "lignite": 1223,
    "nuclear": 1224,
    "hard_coal": 4069,
    "gas": 4071,
    "pumped_storage": 4070,
    "hydro": 1226,
    "other_renewables": 1228,
    "other_conventional": 1227,
    "wind_offshore": 1225,
}


def fetch_day(source, day, area, resolution, generation_types=()) -> dict[str, str]:
    raws: dict[str, str] = {}
    for name in generation_types:
        try:
            filter_id = GENERATION_FILTERS[name]
        except (KeyError, TypeError):
            raise SourceError(
                f"{source.name}: unknown generation type {name!r} "
                f"(supported: {', '.join(GENERATION_FILTERS)})"
            ) from None
        raws.update(
            source._day_payload(
                day, filter_id, f"generation_actual/{name}", area, resolution
            )
        )
    return raws
