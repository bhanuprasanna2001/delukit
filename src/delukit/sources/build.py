"""Build source instances from raw config entries."""

from __future__ import annotations

from typing import Any

from delukit.sources.data_source import DataSource
from delukit.sources.energy_charts import EnergyChartsSource
from delukit.sources.entsoe import EntsoeSource
from delukit.sources.smard import SmardSource
from delukit.sources.weather import WeatherSource


def build_source(name: str, config: dict[str, Any], tz: str) -> DataSource:
    """Build a source from its raw config entry."""
    if name == "smard":
        return SmardSource(tz=tz)
    if name == "entsoe":
        return EntsoeSource(tz=tz)
    if name == "energy_charts":
        return EnergyChartsSource(tz=tz)
    if name == "weather":
        missing = [key for key in ("locations", "fields") if key not in config]
        if missing:
            raise ValueError(
                f"weather source requires 'locations' and 'fields': "
                f"missing {', '.join(missing)}"
            )
        return WeatherSource(
            locations=config["locations"],
            fields=config["fields"],
            model=config.get("model", "ecmwf_ifs"),
            forecast_days=config.get("forecast_days", 16),
            tz=tz,
        )
    raise ValueError(f"unknown source: {name!r}")
