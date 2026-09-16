import json
from pathlib import Path

import pytest

from delukit.core.config import Config, ConfigError, load_config
from delukit.pipelines.raw import run

VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "smard": {"area": "DE_LU", "resolution": "15min"},
        "weather": {"fields": ["temperature_2m"], "locations": []},
    },
}


def test_load_valid_config(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(VALID))

    config = load_config(file)

    assert isinstance(config, Config)
    assert config.storages == ["local"]
    assert config.sources["smard"]["area"] == "DE_LU"


def test_malformed_json(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text("{not json")

    with pytest.raises(ConfigError, match="not valid json"):
        load_config(file)


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_config("nope.json")


def test_missing_field(tmp_path):
    data = {key: value for key, value in VALID.items() if key != "timezone"}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="timezone"):
        load_config(file)


def test_bad_date(tmp_path):
    data = {**VALID, "start": "2025/10/01"}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="iso date"):
        load_config(file)


def test_unknown_source(tmp_path):
    data = {**VALID, "sources": {**VALID["sources"], "nope": {}}}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="unknown source"):
        load_config(file)


def test_repo_config_loads():
    path = Path(__file__).parents[1] / "configs" / "raw.json"
    config = load_config(path)

    assert str(config.start) == "2025-10-01"
    assert set(config.sources) == {"smard", "entsoe", "energy_charts", "weather"}


def test_raw_run_uses_config(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(VALID))

    config = run(str(file))

    assert isinstance(config, Config)
    assert config.sources["smard"]["resolution"] == "15min"
