import json
from pathlib import Path

import pytest

from delukit.core.config import ConfigError, RawConfig, load_raw_config
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


def test_load_valid_raw_config(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(VALID))

    config = load_raw_config(file)

    assert isinstance(config, RawConfig)
    assert config.storages == ["local"]
    assert config.sources["smard"]["area"] == "DE_LU"


def test_malformed_json(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text("{not json")

    with pytest.raises(ConfigError, match="not valid json"):
        load_raw_config(file)


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_raw_config("nope.json")


def test_missing_field(tmp_path):
    data = {key: value for key, value in VALID.items() if key != "timezone"}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="timezone"):
        load_raw_config(file)


def test_bad_date(tmp_path):
    data = {**VALID, "start": "2025/10/01"}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="iso date"):
        load_raw_config(file)


def test_unknown_source(tmp_path):
    data = {**VALID, "sources": {**VALID["sources"], "nope": {}}}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="unknown source"):
        load_raw_config(file)


def test_repo_raw_config_loads():
    path = Path(__file__).parents[1] / "configs" / "raw.json"
    config = load_raw_config(path)

    assert str(config.start) == "2025-10-01"
    assert set(config.sources) == {"smard", "entsoe", "energy_charts", "weather"}


def test_raw_run_uses_raw_config(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(VALID))

    config = run(str(file))

    assert isinstance(config, RawConfig)
    assert config.sources["smard"]["resolution"] == "15min"


ENERGY_CHARTS_VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "energy_charts": {
            "methods": [{"bidding_zone": "DE-LU", "method": "day_ahead_price"}]
        }
    },
}


def test_valid_energy_charts_methods(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(ENERGY_CHARTS_VALID))

    config = load_raw_config(file)

    assert config.sources["energy_charts"]["methods"][0]["bidding_zone"] == "DE-LU"


def energy_charts_config(methods):
    data = json.loads(json.dumps(ENERGY_CHARTS_VALID))
    data["sources"]["energy_charts"]["methods"] = methods
    return data


@pytest.mark.parametrize(
    "methods, message",
    [
        (
            [{"bidding_zone": "DE-LU", "method": "bogus"}],
            "unknown energy_charts method",
        ),
        ([{"method": "day_ahead_price"}], "missing field: bidding_zone"),
        ("not a list", "methods must be a list"),
        ([{"method": 5}], "method field"),
    ],
)
def test_invalid_energy_charts_methods(tmp_path, methods, message):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(energy_charts_config(methods)))

    with pytest.raises(ConfigError, match=message):
        load_raw_config(file)


ENTSOE_VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "entsoe": {
            "methods": [
                {"area": "DE_LU", "method": "day_ahead_price", "sequences": [1, 2]},
                {"area": "DE_LU", "method": "load_actual"},
                {
                    "area": "DE_LU",
                    "method": "generation_actual",
                    "psr_types": ["B16", "B18"],
                },
            ]
        }
    },
}


def entsoe_config(methods):
    data = json.loads(json.dumps(ENTSOE_VALID))
    data["sources"]["entsoe"]["methods"] = methods
    return data


def test_valid_entsoe_methods(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(ENTSOE_VALID))

    config = load_raw_config(file)

    assert config.sources["entsoe"]["methods"][0]["sequences"] == [1, 2]


@pytest.mark.parametrize(
    "methods, message",
    [
        ([{"area": "DE_LU", "method": "bogus"}], "unknown entsoe method"),
        ([{"method": "load_actual"}], "missing field: area"),
        (
            [{"area": "DE_LU", "method": "generation_actual"}],
            "missing field: psr_types",
        ),
        (
            [{"area": "DE_LU", "method": "generation_forecast"}],
            "missing field: psr_types",
        ),
        (
            [{"area": "DE_LU", "method": "day_ahead_price", "sequences": [3]}],
            "sequences must be",
        ),
        (
            [{"area": "DE_LU", "method": "day_ahead_price", "sequences": "12"}],
            "sequences must be",
        ),
        (
            [{"area": "DE_LU", "method": "generation_actual", "psr_types": "B16"}],
            "psr_types must be",
        ),
        ("not a list", "methods must be a list"),
        ([{"method": 5}], "method field"),
    ],
)
def test_invalid_entsoe_methods(tmp_path, methods, message):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(entsoe_config(methods)))

    with pytest.raises(ConfigError, match=message):
        load_raw_config(file)
