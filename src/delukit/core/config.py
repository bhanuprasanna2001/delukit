"""Config loading and validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


class ConfigError(Exception):
    """Raised when a config file is unreadable, unparsable, or invalid."""


@dataclass(frozen=True)
class RawConfig:
    start: date | str
    end: date | str
    timezone: str
    storages: list[str]
    sources: dict[str, dict]

    @classmethod
    def from_file(cls, path: str | Path) -> RawConfig:
        raw = _read(path)
        data = _parse(raw, path)
        _validate(data)
        return cls(
            start=data["start"],
            end=data["end"],
            timezone=data["timezone"],
            storages=data["storages"],
            sources=data["sources"],
        )


@dataclass(frozen=True)
class DataConfig:
    """Silver config: same sources shape as raw; fetch_policy (if present)
    is ignored — source fallback is gold's job, silver keeps every source."""

    start: date | str
    end: date | str
    timezone: str
    storages: list[str]
    sources: dict[str, dict]

    @classmethod
    def from_file(cls, path: str | Path) -> DataConfig:
        raw = _read(path)
        data = _parse(raw, path)
        _validate(data)
        return cls(
            start=data["start"],
            end=data["end"],
            timezone=data["timezone"],
            storages=data["storages"],
            sources=data["sources"],
        )


_KNOWN_SOURCES = {
    "smard": ["area", "resolution", "methods"],
    "entsoe": ["methods"],
    "energy_charts": ["methods"],
    "weather": ["fields", "locations"],
}

_KNOWN_STORAGES = {"local", "databricks", "snowflake"}

_SMARD_RESOLUTIONS = {"15min", "hour"}

_SMARD_METHODS = {
    "day_ahead_price",
    "load_actual",
    "load_forecast",
    "generation_actual",
    "generation_forecast_day_ahead",
}

_SMARD_GENERATION_METHODS = {
    "generation_actual",
    "generation_forecast_day_ahead",
}

_ENTSOE_METHODS = {
    "day_ahead_price",
    "load_actual",
    "load_forecast",
    "generation_actual",
    "generation_forecast",
}

_ENERGY_CHARTS_METHODS = {"day_ahead_price"}

_WEATHER_MODELS = {"ecmwf_ifs", "ecmwf_ifs025", "gfs_seamless"}

_WEATHER_FIELDS = {
    "temperature_2m",
    "wind_speed_100m",
    "wind_direction_100m",
    "shortwave_radiation",
    "cloud_cover",
}

_WEATHER_CELL_SELECTIONS = {"land", "sea", "nearest"}


def _read(path: str | Path) -> str:
    file = Path(path)
    if not file.is_file():
        raise ConfigError(f"config file not found: {file}")
    try:
        return file.read_text()
    except OSError as error:
        raise ConfigError(f"config file not readable: {file}") from error


def _parse(raw: str, path: str | Path) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigError(f"config is not valid json: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"config root must be an object: {path}")
    return data


def _parse_date(value: object, field: str) -> date | str:
    if not isinstance(value, str):
        raise ConfigError(f"{field} must be a string")
    if value == "latest":
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ConfigError(f"{field} must be an iso date or latest")


def _validate(data: dict) -> None:
    for field in ("start", "end", "timezone", "storages", "sources"):
        if field not in data:
            raise ConfigError(f"missing required field: {field}")

    _parse_date(data["start"], "start")
    _parse_date(data["end"], "end")

    if not isinstance(data["timezone"], str):
        raise ConfigError("timezone must be a string")

    storages = data["storages"]
    if (
        not isinstance(storages, list)
        or not storages
        or not all(isinstance(item, str) for item in storages)
    ):
        raise ConfigError("storages must be a non-empty list of strings")
    for storage in storages:
        if storage not in _KNOWN_STORAGES:
            raise ConfigError(f"unknown storage: {storage}")

    sources = data["sources"]
    if not isinstance(sources, dict):
        raise ConfigError("sources must be an object")

    for name, source in sources.items():
        if name not in _KNOWN_SOURCES:
            raise ConfigError(f"unknown source: {name}")
        if not isinstance(source, dict):
            raise ConfigError(f"source must be an object: {name}")
        for required in _KNOWN_SOURCES[name]:
            if required not in source:
                raise ConfigError(f"source {name} is missing field: {required}")
        _validate_refresh_days(source, name)
        if name == "entsoe":
            _validate_entsoe_methods(source["methods"])
        if name == "energy_charts":
            _validate_energy_charts_methods(source["methods"])
        if name == "smard":
            _validate_smard(source)
        if name == "weather":
            _validate_weather(source)


def _validate_refresh_days(source: dict, name: str) -> None:
    if "refresh_days" not in source:
        return
    value = source["refresh_days"]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"source {name} refresh_days must be an integer >= 1")


def _validate_entsoe_methods(methods: object) -> None:
    if not isinstance(methods, list):
        raise ConfigError("entsoe methods must be a list")
    for entry in methods:
        if not isinstance(entry, dict) or not isinstance(entry.get("method"), str):
            raise ConfigError(
                "entsoe method entries must be objects with a method field"
            )
        method = entry["method"]
        if method not in _ENTSOE_METHODS:
            raise ConfigError(f"unknown entsoe method: {method}")
        if not isinstance(entry.get("area"), str):
            raise ConfigError(f"entsoe method {method} is missing field: area")
        if (
            method in ("generation_actual", "generation_forecast")
            and "psr_types" not in entry
        ):
            raise ConfigError(f"entsoe method {method} is missing field: psr_types")
        if "sequences" in entry:
            sequences = entry["sequences"]
            valid = isinstance(sequences, list) and all(
                isinstance(s, int) and s in (1, 2) for s in sequences
            )
            if not valid:
                raise ConfigError(
                    f"entsoe method {method} sequences must be a list of 1 and/or 2"
                )
        if "psr_types" in entry:
            psr_types = entry["psr_types"]
            if not isinstance(psr_types, list) or not all(
                isinstance(p, str) for p in psr_types
            ):
                raise ConfigError(
                    f"entsoe method {method} psr_types must be a list of strings"
                )


def _validate_energy_charts_methods(methods: object) -> None:
    if not isinstance(methods, list):
        raise ConfigError("energy_charts methods must be a list")
    for entry in methods:
        if not isinstance(entry, dict) or not isinstance(entry.get("method"), str):
            raise ConfigError(
                "energy_charts method entries must be objects with a method field"
            )
        method = entry["method"]
        if method not in _ENERGY_CHARTS_METHODS:
            raise ConfigError(f"unknown energy_charts method: {method}")
        if not isinstance(entry.get("bidding_zone"), str):
            raise ConfigError(
                f"energy_charts method {method} is missing field: bidding_zone"
            )


def _validate_smard(source: object) -> None:
    if not isinstance(source, dict):
        raise ConfigError("source must be an object: smard")
    if not isinstance(source.get("area"), str):
        raise ConfigError("smard area must be a string")
    resolution = source.get("resolution")
    if not isinstance(resolution, str) or resolution not in _SMARD_RESOLUTIONS:
        raise ConfigError("smard resolution must be 15min or hour")
    _validate_smard_methods(source.get("methods"))


def _validate_smard_methods(methods: object) -> None:
    if not isinstance(methods, list):
        raise ConfigError("smard methods must be a list")
    for entry in methods:
        if not isinstance(entry, dict) or not isinstance(entry.get("method"), str):
            raise ConfigError(
                "smard method entries must be objects with a method field"
            )
        method = entry["method"]
        if method not in _SMARD_METHODS:
            raise ConfigError(f"unknown smard method: {method}")
        if method in _SMARD_GENERATION_METHODS:
            generation_types = entry.get("generation_types")
            valid = (
                isinstance(generation_types, list)
                and generation_types
                and all(isinstance(item, str) for item in generation_types)
            )
            if not valid:
                raise ConfigError(
                    f"smard method {method} generation_types must be "
                    "a non-empty list of strings"
                )


def _validate_weather(source: object) -> None:
    if not isinstance(source, dict):
        raise ConfigError("source must be an object: weather")

    forecast_days = source.get("forecast_days", 16)
    if (
        isinstance(forecast_days, bool)
        or not isinstance(forecast_days, int)
        or not 1 <= forecast_days <= 16
    ):
        raise ConfigError("weather forecast_days must be an integer from 1 to 16")

    model = source.get("model", "ecmwf_ifs")
    if not isinstance(model, str) or model not in _WEATHER_MODELS:
        raise ConfigError(f"unknown weather model: {model!r}")

    fields = source.get("fields")
    if (
        not isinstance(fields, list)
        or not fields
        or not all(isinstance(field, str) for field in fields)
    ):
        raise ConfigError("weather fields must be a non-empty list of strings")
    for field in fields:
        if field not in _WEATHER_FIELDS:
            raise ConfigError(f"unknown weather field: {field}")

    locations = source.get("locations")
    if not isinstance(locations, list) or not locations:
        raise ConfigError("weather locations must be a non-empty list")
    names: set[str] = set()
    for location in locations:
        if not isinstance(location, dict):
            raise ConfigError("weather location entries must be objects")
        for field in ("name", "latitude", "longitude", "cell_selection"):
            if field not in location:
                raise ConfigError(f"weather location is missing field: {field}")
        name = location["name"]
        if not isinstance(name, str):
            raise ConfigError("weather location name must be a string")
        if name in names:
            raise ConfigError(f"duplicate weather location: {name}")
        names.add(name)
        latitude = location["latitude"]
        longitude = location["longitude"]
        for field, value, low, high in (
            ("latitude", latitude, -90, 90),
            ("longitude", longitude, -180, 180),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"weather location {name} {field} must be a number")
            if not low <= value <= high:
                raise ConfigError(
                    f"weather location {name} {field} must be within {low} and {high}"
                )
        if location["cell_selection"] not in _WEATHER_CELL_SELECTIONS:
            raise ConfigError(
                f"weather location {name} cell_selection must be land, sea or nearest"
            )


def load_raw_config(path: str | Path) -> RawConfig:
    return RawConfig.from_file(path)


def load_data_config(path: str | Path) -> DataConfig:
    return DataConfig.from_file(path)
