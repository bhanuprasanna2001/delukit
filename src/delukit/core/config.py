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


_KNOWN_SOURCES = {
    "smard": ["area", "resolution"],
    "entsoe": ["methods"],
    "energy_charts": ["methods"],
    "weather": ["fields", "locations"],
}


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
    if not isinstance(storages, list) or not all(isinstance(item, str) for item in storages):
        raise ConfigError("storages must be a list of strings")

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


def load_raw_config(path: str | Path) -> RawConfig:
    return RawConfig.from_file(path)
