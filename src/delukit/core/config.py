"""Config loading and validation.

Pydantic v2 models declare the whole pipeline file: nesting, required keys
and absent-means-absent round-tripping come from the models; domain rules
live in small validators that raise the long-standing ConfigError phrases.
One config drives every stage: bronze fetches it, silver parses it, gold
transforms it.

Strictness differs per subtree on purpose: ``sources`` stays lenient (a
stale key like ``fetch_policy`` rides along), gold is a contract (unknown
keys fail here, never mid-pipeline).
"""

# ruff: noqa: TRY004  # validators must raise ValueError: pydantic folds it
# into ValidationError; the public ConfigError is raised once at the boundary.

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)


class ConfigError(Exception):
    """Raised when a config file is unreadable, unparsable, or invalid."""


@dataclass(frozen=True)
class PipelineConfig:
    """One config drives every stage: bronze fetches it, silver parses it,
    gold transforms it. The optional gold block names every gold dataset
    and its exact policy — silver keeps every source side by side, gold
    alone decides which source wins per timestamp."""

    start: date | str
    end: date | str
    timezone: str
    storages: list[str]
    sources: dict[str, dict]
    gold: dict | None = None

    @classmethod
    def from_file(cls, path: str | Path) -> PipelineConfig:
        raw = _read(path)
        data = _parse(raw, path)
        try:
            model = _PipelineFile.model_validate(
                data, context={"sources": data.get("sources")}
            )
        except ValidationError as error:
            raise ConfigError(
                "; ".join(entry["msg"] for entry in error.errors())
            ) from error
        dumped = model.model_dump(exclude_unset=True, by_alias=True)
        return cls(
            start=dumped["start"],
            end=dumped["end"],
            timezone=dumped["timezone"],
            storages=dumped["storages"],
            sources=dumped["sources"],
            gold=dumped.get("gold"),
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

_GOLD_SERIES_SOURCES = {"smard", "entsoe", "energy_charts"}
_GOLD_GRAINS = {"15min", "hour"}
_GOLD_UPSAMPLES = {"ffill", "interpolate"}
_GOLD_RUN_POLICIES = {"latest", "day_ahead_gate"}
_GOLD_REGION_METHODS = {"mean", "weighted_mean", "min", "max", "median"}
_GOLD_NATIONAL_METHODS = {"region_mean", "region_weighted_mean"}
_GOLD_HOLIDAY_SOURCES = {"open_holidays", "none"}
_GOLD_HOLIDAY_SCOPES = {"nationwide", "any_subdivision"}
_GOLD_ROLLING_AGGS = {"mean", "std", "min", "max"}
_GOLD_CALENDAR_FEATURES = {
    "hour",
    "day_of_week",
    "month",
    "day_of_year",
    "week_of_year",
    "is_weekend",
    "is_holiday",
    "is_working_day",
    "is_bridge_day",
    "days_to_holiday",
    "days_since_holiday",
    "hour_sin",
    "hour_cos",
    "day_of_week_sin",
    "day_of_week_cos",
    "month_sin",
    "month_cos",
}
_GOLD_HOLIDAY_FEATURES = {
    "is_holiday",
    "is_working_day",
    "is_bridge_day",
    "days_to_holiday",
    "days_since_holiday",
}
_GOLD_LEVELS = ("location", "region", "national")
_GOLD_TRANSFORM_KEYS = {
    "lag": {"type", "offsets_h"},
    "rolling": {"type", "agg", "windows_h", "min_periods"},
    "diff": {"type", "offsets_h"},
    "asinh": {"type"},
}
# applies_to scopes one weather transform to a subset of weather inputs
# (field names and/or derived kinds, e.g. ["temperature_2m", "hdd"]).
# Series transforms are already per-series, so the key is weather-only.
_GOLD_TRANSFORM_SCOPE_KEY = "applies_to"
_GOLD_DERIVED_KEYS = {
    "hdd": {"type", "from", "base_c"},
    "cdd": {"type", "from", "base_c"},
    "wind_power_proxy": {"type", "from"},
}
_ENTSOE_GENERATION_METHODS = {"generation_actual", "generation_forecast"}
_SMARD_GENERATION_METHODS = {"generation_actual", "generation_forecast_day_ahead"}


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


def _is_direction(field: str) -> bool:
    return field.startswith("wind_direction")


def _as_dict(data: Any, message: str) -> Any:
    """Item guard: list entries must be objects, with a legacy phrase."""
    if not isinstance(data, dict):
        raise ValueError(message)
    return data


def _unknown(data: Any, allowed: set[str], where: str) -> Any:
    """Strict-block guard: a typo'd key fails here, never mid-pipeline."""
    if isinstance(data, dict):
        extra = sorted(set(data) - allowed)
        if extra:
            raise ValueError(f"{where}: unknown field: {extra[0]!r}")
    return data


def _allowed(cls: type[BaseModel]) -> set[str]:
    """Declared keys, including aliases (``from_`` accepts ``from``)."""
    return {field.alias or name for name, field in cls.model_fields.items()}


def _ints(value: Any, where: str) -> None:
    """Positive unique ints (offsets, windows); bools are not ints."""
    if not isinstance(value, list) or not value:
        raise ValueError(f"{where} must be a non-empty list")
    seen: set[int] = set()
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise ValueError(f"{where} must be positive integers")
        if item in seen:
            raise ValueError(f"{where} must not contain duplicates")
        seen.add(item)


def _weights(weights: Any, keys: list, where: str) -> None:
    if not isinstance(weights, dict) or set(weights) != set(keys):
        raise ValueError(
            f"{where} weights must cover exactly: {', '.join(sorted(keys))}"
        )
    for value in weights.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"{where} weights must be positive numbers")


def _transform_shapes(t: dict, where: str) -> None:
    """Shared lag/rolling/diff/asinh parameter checks for both scopes."""
    kind = t.get("type")
    if kind in ("lag", "diff"):
        _ints(t.get("offsets_h"), f"{where} {kind} offsets_h")
    elif kind == "rolling":
        aggs = t.get("agg")
        if not isinstance(aggs, list) or not aggs:
            raise ValueError(f"{where} rolling agg must be a non-empty list")
        if not all(isinstance(agg, str) and agg in _GOLD_ROLLING_AGGS for agg in aggs):
            raise ValueError(f"{where} rolling agg must be mean, std, min or max")
        if len(set(aggs)) != len(aggs):
            raise ValueError(f"{where} rolling agg must not contain duplicates")
        _ints(t.get("windows_h"), f"{where} rolling windows_h")
        min_periods = t.get("min_periods")
        if isinstance(min_periods, bool) or (
            min_periods is not None
            and (not isinstance(min_periods, int) or min_periods < 1)
        ):
            raise ValueError(f"{where} rolling min_periods must be an integer >= 1")


class _Strict(BaseModel):
    """Gold-side base: unknown keys rejected with a block-specific where."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    _where: ClassVar[str] = "config"

    @model_validator(mode="before")
    @classmethod
    def _check_keys(cls, data: Any) -> Any:
        return _unknown(data, _allowed(cls), cls._where)


class _Lenient(BaseModel):
    """Sources-side base: extras ride along (e.g. stale ``fetch_policy``)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# --- sources ---


class _EntsoeMethod(_Lenient):
    method: Any = None
    area: Any = None
    sequences: Any = None
    psr_types: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(
            data, "entsoe method entries must be objects with a method field"
        )

    @model_validator(mode="after")
    def _check(self) -> _EntsoeMethod:
        if not isinstance(self.method, str):
            raise ValueError(
                "entsoe method entries must be objects with a method field"
            )
        if self.method not in _ENTSOE_METHODS:
            raise ValueError(f"unknown entsoe method: {self.method}")
        if not isinstance(self.area, str):
            raise ValueError(f"entsoe method {self.method} is missing field: area")
        if (
            self.method in ("generation_actual", "generation_forecast")
            and self.psr_types is None
        ):
            raise ValueError(f"entsoe method {self.method} is missing field: psr_types")
        if self.sequences is not None:
            valid = isinstance(self.sequences, list) and all(
                isinstance(s, int) and not isinstance(s, bool) and s in (1, 2)
                for s in self.sequences
            )
            if not valid:
                raise ValueError(
                    f"entsoe method {self.method} sequences must be a list of 1 and/or 2"
                )
        if self.psr_types is not None and (
            not isinstance(self.psr_types, list)
            or not all(isinstance(p, str) for p in self.psr_types)
        ):
            raise ValueError(
                f"entsoe method {self.method} psr_types must be a list of strings"
            )
        return self


class _EnergyChartsMethod(_Lenient):
    method: Any = None
    bidding_zone: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(
            data, "energy_charts method entries must be objects with a method field"
        )

    @model_validator(mode="after")
    def _check(self) -> _EnergyChartsMethod:
        if not isinstance(self.method, str):
            raise ValueError(
                "energy_charts method entries must be objects with a method field"
            )
        if self.method not in _ENERGY_CHARTS_METHODS:
            raise ValueError(f"unknown energy_charts method: {self.method}")
        if not isinstance(self.bidding_zone, str):
            raise ValueError(
                f"energy_charts method {self.method} is missing field: bidding_zone"
            )
        return self


class _SmardMethod(_Lenient):
    method: Any = None
    generation_types: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(
            data, "smard method entries must be objects with a method field"
        )

    @model_validator(mode="after")
    def _check(self) -> _SmardMethod:
        if not isinstance(self.method, str):
            raise ValueError("smard method entries must be objects with a method field")
        if self.method not in _SMARD_METHODS:
            raise ValueError(f"unknown smard method: {self.method}")
        if self.method in _SMARD_GENERATION_METHODS and not (
            isinstance(self.generation_types, list)
            and self.generation_types
            and all(isinstance(item, str) for item in self.generation_types)
        ):
            raise ValueError(
                f"smard method {self.method} generation_types must be "
                "a non-empty list of strings"
            )
        return self


def _method_list(data: Any, kind: str, model: type[_Lenient]) -> Any:
    """Shared methods-shape guard; items validate as their entry model."""
    if not isinstance(data, list):
        raise ValueError(f"{kind} methods must be a list")
    try:
        return [model.model_validate(item) for item in data]
    except ValidationError as error:
        raise ValueError("; ".join(item["msg"] for item in error.errors())) from error


class _SmardSource(_Lenient):
    area: Any = None
    resolution: Any = None
    methods: Any = None
    refresh_days: Any = None

    _source: ClassVar[str] = "smard"

    @model_validator(mode="after")
    def _check(self) -> _SmardSource:
        for required in ("area", "resolution", "methods"):
            if required not in self.model_fields_set:
                raise ValueError(f"source smard is missing field: {required}")
        if "refresh_days" in self.model_fields_set and self.refresh_days is None:
            raise ValueError(
                f"source {self._source} refresh_days must be an integer >= 1"
            )
        if self.refresh_days is not None and (
            isinstance(self.refresh_days, bool)
            or not isinstance(self.refresh_days, int)
            or self.refresh_days < 1
        ):
            raise ValueError("source smard refresh_days must be an integer >= 1")
        if not isinstance(self.area, str):
            raise ValueError("smard area must be a string")
        if not isinstance(self.resolution, str) or self.resolution not in (
            _SMARD_RESOLUTIONS
        ):
            raise ValueError("smard resolution must be 15min or hour")
        _method_list(self.methods, "smard", _SmardMethod)
        return self


class _EntsoeSource(_Lenient):
    methods: Any = None
    refresh_days: Any = None

    _source: ClassVar[str] = "entsoe"

    @model_validator(mode="after")
    def _check(self) -> _EntsoeSource:
        if "methods" not in self.model_fields_set:
            raise ValueError("source entsoe is missing field: methods")
        if "refresh_days" in self.model_fields_set and self.refresh_days is None:
            raise ValueError(
                f"source {self._source} refresh_days must be an integer >= 1"
            )
        if self.refresh_days is not None and (
            isinstance(self.refresh_days, bool)
            or not isinstance(self.refresh_days, int)
            or self.refresh_days < 1
        ):
            raise ValueError("source entsoe refresh_days must be an integer >= 1")
        _method_list(self.methods, "entsoe", _EntsoeMethod)
        return self


class _EnergyChartsSource(_Lenient):
    methods: Any = None
    refresh_days: Any = None

    _source: ClassVar[str] = "energy_charts"

    @model_validator(mode="after")
    def _check(self) -> _EnergyChartsSource:
        if "methods" not in self.model_fields_set:
            raise ValueError("source energy_charts is missing field: methods")
        if "refresh_days" in self.model_fields_set and self.refresh_days is None:
            raise ValueError(
                f"source {self._source} refresh_days must be an integer >= 1"
            )
        if self.refresh_days is not None and (
            isinstance(self.refresh_days, bool)
            or not isinstance(self.refresh_days, int)
            or self.refresh_days < 1
        ):
            raise ValueError(
                "source energy_charts refresh_days must be an integer >= 1"
            )
        _method_list(self.methods, "energy_charts", _EnergyChartsMethod)
        return self


class _WeatherLocation(_Lenient):
    name: Any = None
    latitude: Any = None
    longitude: Any = None
    cell_selection: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(data, "weather location entries must be objects")

    @model_validator(mode="after")
    def _check(self) -> _WeatherLocation:
        for field in ("name", "latitude", "longitude", "cell_selection"):
            if field not in self.model_fields_set:
                raise ValueError(f"weather location is missing field: {field}")
        if not isinstance(self.name, str):
            raise ValueError("weather location name must be a string")
        for field, value, low, high in (
            ("latitude", self.latitude, -90, 90),
            ("longitude", self.longitude, -180, 180),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(
                    f"weather location {self.name} {field} must be a number"
                )
            if not low <= value <= high:
                raise ValueError(
                    f"weather location {self.name} {field} must be within "
                    f"{low} and {high}"
                )
        if self.cell_selection not in _WEATHER_CELL_SELECTIONS:
            raise ValueError(
                f"weather location {self.name} cell_selection must be land, sea or nearest"
            )
        return self


class _WeatherSource(_Lenient):
    model: Any = "ecmwf_ifs"
    forecast_days: Any = 16
    fields: Any = None
    locations: Any = None
    refresh_days: Any = None

    _source: ClassVar[str] = "weather"

    @model_validator(mode="after")
    def _check(self) -> _WeatherSource:
        for required in ("fields", "locations"):
            if required not in self.model_fields_set:
                raise ValueError(f"source weather is missing field: {required}")
        if "refresh_days" in self.model_fields_set and self.refresh_days is None:
            raise ValueError(
                f"source {self._source} refresh_days must be an integer >= 1"
            )
        if self.refresh_days is not None and (
            isinstance(self.refresh_days, bool)
            or not isinstance(self.refresh_days, int)
            or self.refresh_days < 1
        ):
            raise ValueError("source weather refresh_days must be an integer >= 1")
        if (
            isinstance(self.forecast_days, bool)
            or not isinstance(self.forecast_days, int)
            or not 1 <= self.forecast_days <= 16
        ):
            raise ValueError("weather forecast_days must be an integer from 1 to 16")
        if not isinstance(self.model, str) or self.model not in _WEATHER_MODELS:
            raise ValueError(f"unknown weather model: {self.model!r}")
        if (
            not isinstance(self.fields, list)
            or not self.fields
            or not all(isinstance(field, str) for field in self.fields)
        ):
            raise ValueError("weather fields must be a non-empty list of strings")
        for field in self.fields:
            if field not in _WEATHER_FIELDS:
                raise ValueError(f"unknown weather field: {field}")
        if not isinstance(self.locations, list) or not self.locations:
            raise ValueError("weather locations must be a non-empty list")
        seen: set[str] = set()
        for item in self.locations:
            location = _WeatherLocation.model_validate(item)
            if location.name in seen:
                raise ValueError(f"duplicate weather location: {location.name}")
            seen.add(location.name)
        return self


class _Sources(BaseModel):
    """Fetch subtree: dispatches each entry by source name, extras ignored."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    smard: Any = None
    entsoe: Any = None
    energy_charts: Any = None
    weather: Any = None

    _models: ClassVar[dict] = {
        "smard": _SmardSource,
        "entsoe": _EntsoeSource,
        "energy_charts": _EnergyChartsSource,
        "weather": _WeatherSource,
    }

    @model_validator(mode="before")
    @classmethod
    def _dispatch(cls, data: Any) -> Any:
        # ponytail: validate-and-discard — raw entries round-trip untouched,
        # so validated output stays byte-identical to the input file.
        if not isinstance(data, dict):
            raise ValueError("sources must be an object")
        for name, entry in data.items():
            if name not in _KNOWN_SOURCES:
                raise ValueError(f"unknown source: {name}")
            if not isinstance(entry, dict):
                raise ValueError(f"source must be an object: {name}")
            try:
                cls._models[name].model_validate(entry)
            except ValidationError as error:
                raise ValueError(
                    "; ".join(item["msg"] for item in error.errors())
                ) from error
        return data


# --- gold ---


class _GoldCalendar(_Strict):
    _where: ClassVar[str] = "gold calendar"

    country: Any = "DE"
    holiday_source: Any = "none"
    holiday_scope: Any = "nationwide"
    features: Any = None

    @model_validator(mode="after")
    def _check(self) -> _GoldCalendar:
        if not isinstance(self.country, str) or not re.fullmatch(
            r"[A-Z]{2}", self.country
        ):
            raise ValueError("gold calendar country must be a two-letter ISO code")
        if not isinstance(self.holiday_source, str) or (
            self.holiday_source not in _GOLD_HOLIDAY_SOURCES
        ):
            raise ValueError(
                "gold calendar holiday_source must be open_holidays or none"
            )
        if not isinstance(self.holiday_scope, str) or (
            self.holiday_scope not in _GOLD_HOLIDAY_SCOPES
        ):
            raise ValueError(
                "gold calendar holiday_scope must be nationwide or any_subdivision"
            )
        if "features" in self.model_fields_set and self.features is None:
            raise ValueError("gold calendar features must be a list")
        features = self.features if self.features is not None else []
        if not isinstance(features, list):
            raise ValueError("gold calendar features must be a list")
        seen: set[str] = set()
        for feature in features:
            if not isinstance(feature, str) or feature not in _GOLD_CALENDAR_FEATURES:
                raise ValueError(f"unknown gold calendar feature: {feature!r}")
            if feature in seen:
                raise ValueError(f"duplicate gold calendar feature: {feature!r}")
            if (
                feature in _GOLD_HOLIDAY_FEATURES
                and self.holiday_source != "open_holidays"
            ):
                raise ValueError(
                    f"gold calendar feature {feature!r} requires "
                    "holiday_source: open_holidays"
                )
            seen.add(feature)
        return self


class _GoldFrom(_Strict):
    """One silver origin for a series; must be configured for fetch."""

    _where: ClassVar[str] = "gold series from"

    source: Any = None
    method: Any = None
    sequence: Any = None
    psr_type: Any = None
    generation_type: Any = None

    @model_validator(mode="after")
    def _check(self, info) -> _GoldFrom:
        sources = (info.context or {}).get("sources") or {}
        if self.source == "weather":
            raise ValueError(
                "gold series: weather belongs in the dataset weather block"
            )
        if not isinstance(self.source, str) or self.source not in (
            _GOLD_SERIES_SOURCES
        ):
            raise ValueError(f"gold series from: unknown source: {self.source!r}")
        if self.source not in sources:
            raise ValueError(
                f"gold series from: source not configured: {self.source!r}"
            )
        where = "gold series from"
        matching = [
            m
            for m in sources[self.source]["methods"]
            if isinstance(m, dict) and m.get("method") == self.method
        ]
        if not matching:
            raise ValueError(
                f"{where}: {self.source} method not configured for fetch: "
                f"{self.method!r}"
            )
        self._check_fetch_keys(matching, where)
        return self

    def _check_fetch_keys(self, matching: list[dict], where: str) -> None:
        source, method = self.source, self.method
        sequence = self.sequence
        if source == "entsoe" and method == "day_ahead_price":
            if sequence is None:
                sequence = 1
            if (
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or sequence not in (1, 2)
            ):
                raise ValueError(
                    f"{where}: entsoe day_ahead_price sequence must be 1 (SDAC) or 2 (EXAA)"
                )
            fetched = {s for m in matching for s in m.get("sequences", [1])}
            if sequence not in fetched:
                raise ValueError(
                    f"{where}: entsoe sequence {sequence} is not configured for fetch "
                    "(sources.entsoe sequences)"
                )
        elif sequence is not None:
            raise ValueError(
                f"{where}: sequence is only valid for entsoe day_ahead_price"
            )
        if source == "entsoe" and method in _ENTSOE_GENERATION_METHODS:
            if not isinstance(self.psr_type, str):
                raise ValueError(f"{where}: entsoe {method} requires psr_type")
            fetched = {p for m in matching for p in m.get("psr_types", [])}
            if self.psr_type not in fetched:
                raise ValueError(
                    f"{where}: entsoe psr_type {self.psr_type!r} is not configured "
                    "for fetch"
                )
        elif self.psr_type is not None:
            raise ValueError(
                f"{where}: psr_type is only valid for entsoe generation methods"
            )
        if source == "smard" and method in _SMARD_GENERATION_METHODS:
            if not isinstance(self.generation_type, str):
                raise ValueError(f"{where}: smard {method} requires generation_type")
            fetched = {g for m in matching for g in m.get("generation_types", [])}
            if self.generation_type not in fetched:
                raise ValueError(
                    f"{where}: smard generation_type {self.generation_type!r} "
                    "is not configured for fetch"
                )
        elif self.generation_type is not None:
            raise ValueError(
                f"{where}: generation_type is only valid for smard generation methods"
            )

    def _identity(self) -> tuple:
        sequence = self.sequence
        if self.source == "entsoe" and self.method == "day_ahead_price":
            sequence = 1 if sequence is None else sequence
        return (
            self.source,
            self.method,
            sequence,
            self.psr_type,
            self.generation_type,
        )


class _SeriesTransform(_Strict):
    """Per-series transform: already scoped, so applies_to is rejected."""

    _where: ClassVar[str] = "gold series transform"

    type: Any = None
    offsets_h: Any = None
    agg: Any = None
    windows_h: Any = None
    min_periods: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(data, "gold series transforms must be objects")

    @model_validator(mode="after")
    def _check(self) -> _SeriesTransform:
        if not isinstance(self.type, str) or self.type not in _GOLD_TRANSFORM_KEYS:
            raise ValueError(f"unknown gold transform: {self.type!r}")
        provided = {key: None for key in self.model_fields_set}
        _unknown(provided, _GOLD_TRANSFORM_KEYS[self.type], self._where)
        _transform_shapes(self.model_dump(), "gold series")
        return self


class _WeatherTransform(_Strict):
    """Weather-block transform: may carry an applies_to input scope."""

    _where: ClassVar[str] = "gold weather transform"

    type: Any = None
    offsets_h: Any = None
    agg: Any = None
    windows_h: Any = None
    min_periods: Any = None
    applies_to: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        return _as_dict(data, "gold weather transforms must be objects")

    @model_validator(mode="after")
    def _check(self) -> _WeatherTransform:
        if not isinstance(self.type, str) or self.type not in _GOLD_TRANSFORM_KEYS:
            raise ValueError(f"unknown gold transform: {self.type!r}")
        allowed = set(_GOLD_TRANSFORM_KEYS[self.type]) | {_GOLD_TRANSFORM_SCOPE_KEY}
        provided = {key: None for key in self.model_fields_set}
        _unknown(provided, allowed, self._where)
        _transform_shapes(self.model_dump(), "gold weather")
        if self.applies_to is not None:
            if (
                not isinstance(self.applies_to, list)
                or not self.applies_to
                or not all(isinstance(item, str) for item in self.applies_to)
            ):
                raise ValueError(
                    "gold weather transform applies_to must be a non-empty list "
                    "of strings"
                )
            if len(set(self.applies_to)) != len(self.applies_to):
                raise ValueError(
                    "gold weather transform applies_to must not contain duplicates"
                )
        return self


def _transform_list(
    data: Any, model: type[_Strict], objects_message: str, list_message: str
) -> list:
    if not isinstance(data, list):
        raise ValueError(list_message)
    return [model.model_validate(item) for item in data]


class _Region(_Strict):
    _where: ClassVar[str] = "gold weather region"

    locations: Any = None
    method: Any = "mean"
    weights: Any = None

    @model_validator(mode="after")
    def _check(self) -> _Region:
        if (
            not isinstance(self.locations, list)
            or not self.locations
            or not all(isinstance(member, str) for member in self.locations)
        ):
            raise ValueError(
                "gold weather region locations must be a non-empty list of strings"
            )
        if not isinstance(self.method, str) or self.method not in (
            _GOLD_REGION_METHODS
        ):
            raise ValueError(
                "gold weather region method must be mean, weighted_mean, min, max "
                "or median"
            )
        if self.method == "weighted_mean":
            if not isinstance(self.weights, dict):
                raise ValueError("gold weather region weighted_mean requires weights")
            _weights(self.weights, self.locations, "gold weather region")
        elif self.weights is not None:
            raise ValueError(
                "gold weather region weights require method: weighted_mean"
            )
        return self


class _National(_Strict):
    _where: ClassVar[str] = "gold weather national"

    method: Any = "region_mean"
    region_weights: Any = None


class _Derived(_Lenient):
    """Lenient base: kind-aware unknown-key check lives in _must_be_entry."""

    type: Any = None
    extra_from: Any = Field(default=None, alias="from")
    base_c: Any = None

    @model_validator(mode="before")
    @classmethod
    def _must_be_entry(cls, data: Any) -> Any:
        _as_dict(data, "gold weather derived entries must be objects")
        kind = data.get("type")
        allowed = (
            _GOLD_DERIVED_KEYS[kind]
            if isinstance(kind, str) and kind in _GOLD_DERIVED_KEYS
            else {"type", "from", "base_c"}
        )
        return _unknown(data, allowed, f"gold weather derived {kind}")

    @model_validator(mode="after")
    def _check(self) -> _Derived:
        if not isinstance(self.type, str) or self.type not in _GOLD_DERIVED_KEYS:
            raise ValueError(f"unknown gold weather derived type: {self.type!r}")
        if self.type in ("hdd", "cdd") and (
            isinstance(self.base_c, bool) or not isinstance(self.base_c, (int, float))
        ):
            raise ValueError(
                f"gold weather derived {self.type} requires base_c (a number)"
            )
        return self


class _Weather(_Strict):
    _where: ClassVar[str] = "gold dataset weather"

    run_policy: Any = "latest"
    fields: Any = None
    regions: Any = None
    national: Any = None
    levels: Any = None
    derived: Any = None
    transforms: Any = None

    @model_validator(mode="after")
    def _check(self, info) -> _Weather:
        where = "gold dataset weather"
        sources = (info.context or {}).get("sources") or {}
        if "weather" not in sources:
            raise ValueError(f"{where} requires a configured weather source")
        if not isinstance(self.run_policy, str) or (
            self.run_policy not in _GOLD_RUN_POLICIES
        ):
            raise ValueError(f"{where} run_policy must be latest or day_ahead_gate")
        if (
            not isinstance(self.fields, list)
            or not self.fields
            or not all(isinstance(field, str) for field in self.fields)
        ):
            raise ValueError(f"{where} fields must be a non-empty list of strings")
        if len(set(self.fields)) != len(self.fields):
            raise ValueError(f"{where} fields must not contain duplicates")
        fetched = set((sources.get("weather") or {}).get("fields", []))
        for field in self.fields:
            if field not in fetched:
                raise ValueError(
                    f"{where} field is not fetched by the weather source: {field!r}"
                )
        if not isinstance(self.regions, dict) or not self.regions:
            raise ValueError(f"{where} regions must be a non-empty object")
        checked_regions = {}
        for region_name, region in self.regions.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", region_name):
                raise ValueError(
                    f"{where} region name must be a lowercase snake_case name"
                )
            if not isinstance(region, dict):
                raise ValueError(f"{where} region {region_name} must be an object")
            checked_regions[region_name] = _Region.model_validate(region)
        if any(_is_direction(field) for field in self.fields):
            for region_name, region in checked_regions.items():
                if region.method in {"min", "max", "median"}:
                    raise ValueError(
                        f"{where} region {region_name}: directional fields aggregate "
                        "with a circular mean; method must be mean or weighted_mean"
                    )
        locations = [
            loc["name"] for loc in (sources.get("weather") or {}).get("locations", [])
        ]
        assigned = [
            loc for region in checked_regions.values() for loc in region.locations
        ]
        for member in assigned:
            if member not in locations:
                raise ValueError(
                    f"{where} region references unknown location: {member!r}"
                )
        duplicated = sorted({loc for loc in assigned if assigned.count(loc) > 1})
        if duplicated:
            raise ValueError(f"{where} location in multiple regions: {duplicated[0]!r}")
        missing = [loc for loc in locations if loc not in assigned]
        if missing:
            raise ValueError(
                f"{where} location not assigned to any region: {missing[0]!r}"
            )
        if "national" in self.model_fields_set and self.national is None:
            raise ValueError(f"{where} national must be an object")
        if self.national is not None:
            if not isinstance(self.national, dict):
                raise ValueError(f"{where} national must be an object")
            national = _National.model_validate(self.national)
            if not isinstance(national.method, str) or (
                national.method not in _GOLD_NATIONAL_METHODS
            ):
                raise ValueError(
                    f"{where} national method must be region_mean or "
                    "region_weighted_mean"
                )
            if national.method == "region_weighted_mean":
                if not isinstance(national.region_weights, dict):
                    raise ValueError(
                        f"{where} national region_weighted_mean requires region_weights"
                    )
                _weights(
                    national.region_weights,
                    list(checked_regions),
                    f"{where} national",
                )
            elif national.region_weights is not None:
                raise ValueError(
                    f"{where} national region_weights require method: "
                    "region_weighted_mean"
                )
        if "levels" in self.model_fields_set and self.levels is None:
            raise ValueError(
                f"{where} levels must be a non-empty list of "
                "location, region and/or national"
            )
        levels = self.levels if self.levels is not None else ["region", "national"]
        if (
            not isinstance(levels, list)
            or not levels
            or not all(isinstance(level, str) for level in levels)
        ):
            raise ValueError(
                f"{where} levels must be a non-empty list of "
                "location, region and/or national"
            )
        if len(set(levels)) != len(levels):
            raise ValueError(f"{where} levels must not contain duplicates")
        for level in levels:
            if level not in _GOLD_LEVELS:
                raise ValueError(
                    f"{where} unknown level: {level!r} "
                    "(expected location, region or national)"
                )
        if "derived" in self.model_fields_set and self.derived is None:
            raise ValueError(f"{where} derived must be a list")
        derived = self.derived if self.derived is not None else []
        if not isinstance(derived, list):
            raise ValueError(f"{where} derived must be a list")
        checked_derived = []
        seen: set[tuple] = set()
        for feature in derived:
            item = _Derived.model_validate(feature)
            from_field = item.extra_from
            if from_field not in self.fields:
                raise ValueError(
                    f"{where} derived {item.type} from field not selected: "
                    f"{from_field!r}"
                )
            if _is_direction(from_field):
                raise ValueError(
                    f"{where} derived {item.type} cannot use a directional field: "
                    f"{from_field!r}"
                )
            if item.type == "wind_power_proxy" and not from_field.startswith(
                "wind_speed"
            ):
                raise ValueError(
                    f"{where} derived wind_power_proxy requires a wind_speed field: "
                    f"{from_field!r}"
                )
            key = (item.type, from_field)
            if key in seen:
                raise ValueError(
                    f"{where} duplicate derived feature: {item.type} from "
                    f"{from_field!r}"
                )
            seen.add(key)
            checked_derived.append(item)
        selectable = set(self.fields) | {item.type for item in checked_derived}
        if "transforms" in self.model_fields_set and self.transforms is None:
            raise ValueError(f"{where} transforms must be a list")
        transforms = self.transforms if self.transforms is not None else []
        checked_transforms = _transform_list(
            transforms,
            _WeatherTransform,
            "gold weather transforms must be objects",
            f"{where} transforms must be a list",
        )
        for transform in checked_transforms:
            if transform.applies_to is not None:
                for item in transform.applies_to:
                    if item not in selectable:
                        raise ValueError(
                            f"{where} transform applies_to has unknown input: {item!r}"
                        )
        seen_transforms: set[str] = set()
        for transform in checked_transforms:
            key = json.dumps(transform.model_dump(exclude_unset=True), sort_keys=True)
            if key in seen_transforms:
                raise ValueError(f"{where} duplicate transform")
            seen_transforms.add(key)
        return self


class _Series(BaseModel):
    """Series entries: extras kept for the dataset's dynamic unknown check."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    name: Any = None
    from_: Any = Field(default=None, alias="from")
    upsample: Any = "ffill"
    transforms: Any = None

    @model_validator(mode="after")
    def _check(self, info) -> _Series:
        if not isinstance(self.name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*", self.name
        ):
            raise ValueError("gold series name must be a lowercase snake_case name")
        if not isinstance(self.upsample, str) or self.upsample not in _GOLD_UPSAMPLES:
            raise ValueError(
                f"gold series {self.name} upsample must be ffill or interpolate"
            )
        entries = self.from_
        if not isinstance(entries, list) or not entries:
            raise ValueError(f"gold series {self.name} from must be a non-empty list")
        context = {"sources": ((info.context or {}).get("sources") or {})}
        checked = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"gold series {self.name} from entries must be objects"
                )
            try:
                checked.append(_GoldFrom.model_validate(entry, context=context))
            except ValidationError as error:
                raise ValueError(
                    "; ".join(item["msg"] for item in error.errors())
                ) from error
        seen: set[tuple] = set()
        for item in checked:
            key = item._identity()
            if key in seen:
                raise ValueError(f"duplicate gold series from entry in {self.name!r}")
            seen.add(key)
        # ponytail: explicit null is not absent (legacy parity) — only
        # top-level gold and target treat null as omitted.
        if "transforms" in self.model_fields_set and self.transforms is None:
            raise ValueError(f"gold series {self.name} transforms must be a list")
        transforms = self.transforms if self.transforms is not None else []
        checked_transforms = _transform_list(
            transforms,
            _SeriesTransform,
            "gold series transforms must be objects",
            f"gold series {self.name} transforms must be a list",
        )
        seen_transforms: set[str] = set()
        for transform in checked_transforms:
            key = json.dumps(transform.model_dump(exclude_unset=True), sort_keys=True)
            if key in seen_transforms:
                raise ValueError(f"gold series {self.name} duplicate transform")
            seen_transforms.add(key)
        return self


class _Dataset(_Strict):
    _where: ClassVar[str] = "gold dataset"

    name: Any = None
    grain: Any = "15min"
    series: Any = None
    weather: Any = None
    target: Any = None
    columns: Any = None

    @model_validator(mode="before")
    @classmethod
    def _shapes(cls, data: Any) -> Any:
        _unknown(data, _allowed(cls), "gold dataset")
        if isinstance(data, dict):
            series = data.get("series")
            if not isinstance(series, list) or not series:
                raise ValueError(
                    f"gold dataset {data.get('name')} series must be a non-empty list"
                )
            for entry in series:
                if not isinstance(entry, dict):
                    raise ValueError(
                        f"gold dataset {data.get('name')} series must be objects"
                    )
        return data

    @model_validator(mode="after")
    def _check(self) -> _Dataset:
        if not isinstance(self.name, str) or not re.fullmatch(
            r"[a-z][a-z0-9_]*", self.name
        ):
            raise ValueError("gold dataset name must be a lowercase snake_case name")
        if not isinstance(self.grain, str) or self.grain not in _GOLD_GRAINS:
            raise ValueError(f"gold dataset {self.name} grain must be 15min or hour")
        return self


class _GoldBlock(_Strict):
    _where: ClassVar[str] = "gold"

    calendar: Any = None
    datasets: Any = None

    @model_validator(mode="before")
    @classmethod
    def _shapes(cls, data: Any) -> Any:
        _unknown(data, _allowed(cls), "gold")
        if isinstance(data, dict):
            datasets = data.get("datasets")
            if not isinstance(datasets, list) or not datasets:
                raise ValueError("gold datasets must be a non-empty list")
            for entry in datasets:
                if not isinstance(entry, dict):
                    raise ValueError("gold datasets must be objects")
        return data

    @model_validator(mode="after")
    def _check(self, info) -> _GoldBlock:
        context = info.context or {}
        if self.calendar is not None and not isinstance(self.calendar, dict):
            raise ValueError("gold calendar must be an object")
        if "calendar" in self.model_fields_set and self.calendar is None:
            raise ValueError("gold calendar must be an object")
        calendar = (
            _GoldCalendar.model_validate(self.calendar)
            if self.calendar is not None
            else None
        )
        calendar_features = (
            calendar.features if calendar is not None and calendar.features else []
        )
        seen: set[str] = set()
        checked = []
        for entry in self.datasets:
            dataset = _Dataset.model_validate(entry)
            if dataset.name in seen:
                raise ValueError(f"duplicate gold dataset: {dataset.name!r}")
            seen.add(dataset.name)
            checked.append(dataset)
        for dataset in checked:
            self._finalize(dataset, calendar_features, context)
        return self

    @staticmethod
    def _finalize(dataset: _Dataset, calendar_features: list, context: dict) -> None:
        # ponytail: validate-only — raw entries round-trip untouched. Series
        # unknown keys need the dataset name, so the dynamic where lives
        # here, not in the series model.
        checked_series = []
        series_names: set[str] = set()
        for entry in dataset.series:
            try:
                series = _Series.model_validate(entry, context=context)
            except ValidationError as error:
                raise ValueError(
                    "; ".join(item["msg"] for item in error.errors())
                ) from error
            if series.model_extra:
                extra = sorted(series.model_extra)
                raise ValueError(
                    f"gold series in {dataset.name}: unknown field: {extra[0]!r}"
                )
            if series.name in series_names:
                raise ValueError(f"duplicate gold series: {series.name!r}")
            series_names.add(series.name)
            checked_series.append(series)
        weather: dict | None = None
        if "weather" in dataset.model_fields_set and dataset.weather is None:
            raise ValueError(f"gold dataset {dataset.name} weather must be an object")
        if dataset.weather is not None:
            if not isinstance(dataset.weather, dict):
                raise ValueError(
                    f"gold dataset {dataset.name} weather must be an object"
                )
            try:
                _Weather.model_validate(dataset.weather, context=context)
            except ValidationError as error:
                raise ValueError(
                    "; ".join(item["msg"] for item in error.errors())
                ) from error
            weather = dataset.weather
        if dataset.target is not None and (
            not isinstance(dataset.target, str) or dataset.target not in series_names
        ):
            raise ValueError(
                f"gold dataset {dataset.name} target must be one of its series: "
                f"{sorted(series_names)!r}"
            )
        if dataset.columns is not None:
            _validate_columns(
                dataset.name,
                dataset.columns,
                checked_series,
                weather,
                calendar_features,
            )
            if dataset.target is not None and dataset.target not in dataset.columns:
                raise ValueError(
                    f"gold dataset {dataset.name} target {dataset.target!r} "
                    "must be listed in columns"
                )


def _validate_columns(
    name: str,
    columns: Any,
    checked_series: list,
    weather: dict | None,
    calendar_features: list,
) -> None:
    """Explicit final projection: the model's exact input contract."""
    where = f"gold dataset {name} columns"
    if (
        not isinstance(columns, list)
        or not columns
        or not all(isinstance(column, str) for column in columns)
    ):
        raise ValueError(f"{where} must be a non-empty list of strings")
    if len(set(columns)) != len(columns):
        raise ValueError(f"{where} must not contain duplicates")
    if "timestamp" in columns:
        raise ValueError(f"{where} must not list timestamp (it is implicit)")

    expected: set[str] = set(calendar_features or [])
    for series in checked_series:
        expected |= _series_feature_names(
            series.name, series.transforms if series.transforms is not None else []
        )
    if isinstance(weather, dict):
        expected |= _weather_feature_names(weather)
    for column in columns:
        if column not in expected:
            raise ValueError(f"{where} has unknown column: {column!r}")


def _series_feature_names(name: str, transforms: list) -> set[str]:
    """Every output a series can produce: base plus one column per transform.

    Names follow docs/gold-pipeline-plan.md §3.5: ``{base}_lag_{h}h``,
    ``{base}_roll_{agg}_{w}h``, ``{base}_diff_{h}h``, ``{base}_asinh``.
    ``timestamp`` is the implicit index and never listed."""
    names = {name}
    for transform in transforms:
        if not isinstance(transform, dict):
            continue
        kind = transform.get("type")
        if kind in ("lag", "diff"):
            suffix = "lag" if kind == "lag" else "diff"
            for offset in transform.get("offsets_h", []):
                names.add(f"{name}_{suffix}_{offset}h")
        elif kind == "rolling":
            for agg in transform.get("agg", []):
                for window in transform.get("windows_h", []):
                    names.add(f"{name}_roll_{agg}_{window}h")
        elif kind == "asinh":
            names.add(f"{name}_asinh")
    return names


def _weather_feature_names(weather: dict) -> set[str]:
    """Every output a weather block can produce, level-qualified.

    Bases use a ``__`` separator so field and level never blur together
    (``temperature_2m__national``, never ``temp_national``):
    ``{field}__{location|region|national}`` and derived
    ``{kind}__{from}__{level}``. Transform outputs append the same suffixes
    as series, filtered per transform by its ``applies_to`` scope."""
    fields = weather.get("fields", [])
    regions = weather.get("regions", {})
    levels = weather.get("levels", ["region", "national"])
    derived = weather.get("derived", [])
    transforms = weather.get("transforms", [])
    locations = [loc for region in regions.values() for loc in region["locations"]]

    bases: set[str] = set()
    # ponytail: one scope set per base (fields or derived kinds it came
    # from); a transform applies when its applies_to hits that scope.
    scopes: dict[str, set[str]] = {}
    for field in fields:
        if "location" in levels:
            for location in locations:
                base = f"{field}__{location}"
                bases.add(base)
                scopes[base] = {field}
        if "region" in levels:
            for region_name in regions:
                base = f"{field}__{region_name}"
                bases.add(base)
                scopes[base] = {field}
        if "national" in levels:
            base = f"{field}__national"
            bases.add(base)
            scopes[base] = {field}
    for feature in derived:
        if not isinstance(feature, dict):
            continue
        kind, from_field = feature.get("type"), feature.get("from")
        label = f"{kind}__{from_field}"
        if "location" in levels:
            for location in locations:
                base = f"{label}__{location}"
                bases.add(base)
                scopes[base] = {from_field, kind}
        if "region" in levels:
            for region_name in regions:
                base = f"{label}__{region_name}"
                bases.add(base)
                scopes[base] = {from_field, kind}
        if "national" in levels:
            base = f"{label}__national"
            bases.add(base)
            scopes[base] = {from_field, kind}

    names = set(bases)
    for transform in transforms:
        if not isinstance(transform, dict):
            continue
        scope = set(transform.get(_GOLD_TRANSFORM_SCOPE_KEY, [])) or None
        kind = transform.get("type")
        for base in bases:
            if scope is not None and scopes[base].isdisjoint(scope):
                continue
            if kind in ("lag", "diff"):
                suffix = "lag" if kind == "lag" else "diff"
                for offset in transform.get("offsets_h", []):
                    names.add(f"{base}_{suffix}_{offset}h")
            elif kind == "rolling":
                for agg in transform.get("agg", []):
                    for window in transform.get("windows_h", []):
                        names.add(f"{base}_roll_{agg}_{window}h")
            elif kind == "asinh":
                names.add(f"{base}_asinh")
    return names


def _parse_date(value: object, field: str) -> date | str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    if value == "latest":
        return value
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field} must be an iso date or latest")


class _PipelineFile(BaseModel):
    """Whole file: required keys, then per-subtree models do the rest."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    start: Any = None
    end: Any = None
    timezone: Any = None
    storages: Any = None
    sources: Any = None
    gold: Any = None

    @model_validator(mode="before")
    @classmethod
    def _required(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for field in ("start", "end", "timezone", "storages", "sources"):
                if field not in data:
                    raise ValueError(f"missing required field: {field}")
        return data

    @model_validator(mode="after")
    def _check(self) -> _PipelineFile:
        # ponytail: validate only — start/end stay raw strings like before.
        _parse_date(self.start, "start")
        _parse_date(self.end, "end")
        if not isinstance(self.timezone, str):
            raise ValueError("timezone must be a string")
        if (
            not isinstance(self.storages, list)
            or not self.storages
            or not all(isinstance(item, str) for item in self.storages)
        ):
            raise ValueError("storages must be a non-empty list of strings")
        for storage in self.storages:
            if storage not in _KNOWN_STORAGES:
                raise ValueError(f"unknown storage: {storage}")
        try:
            _Sources.model_validate(self.sources)
        except ValidationError as error:
            raise ValueError(
                "; ".join(item["msg"] for item in error.errors())
            ) from error
        if self.gold is not None:
            if not isinstance(self.gold, dict):
                raise ValueError("gold must be an object")
            try:
                _GoldBlock.model_validate(self.gold, context={"sources": self.sources})
            except ValidationError as error:
                raise ValueError(
                    "; ".join(item["msg"] for item in error.errors())
                ) from error
        return self


def load_pipeline_config(path: str | Path) -> PipelineConfig:
    return PipelineConfig.from_file(path)
