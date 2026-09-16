import json
from pathlib import Path

import pytest

from delukit.core.config import ConfigError, RawConfig, load_raw_config

VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "smard": {
            "area": "DE_LU",
            "resolution": "15min",
            "methods": [
                {"method": "day_ahead_price"},
                {"method": "load_actual"},
                {"method": "generation_actual", "generation_types": ["solar"]},
            ],
        },
        "weather": {
            "model": "ecmwf_ifs",
            "forecast_days": 16,
            "fields": ["temperature_2m"],
            "locations": [
                {
                    "name": "berlin",
                    "latitude": 52.52,
                    "longitude": 13.41,
                    "cell_selection": "land",
                }
            ],
        },
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

    config = load_raw_config(file)

    assert isinstance(config, RawConfig)
    assert config.sources["smard"]["resolution"] == "15min"


def test_unknown_storage(tmp_path):
    data = {**VALID, "storages": ["local", "bogus"]}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="unknown storage"):
        load_raw_config(file)


def test_storages_must_include_local(tmp_path):
    data = {**VALID, "storages": ["databricks"]}
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="local"):
        load_raw_config(file)


@pytest.mark.parametrize("value", [0, -3, 2.5, "7", True])
def test_invalid_refresh_days(tmp_path, value):
    data = json.loads(json.dumps(VALID))
    data["sources"]["smard"]["refresh_days"] = value
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="refresh_days"):
        load_raw_config(file)


def test_valid_refresh_days(tmp_path):
    data = json.loads(json.dumps(VALID))
    data["sources"]["smard"]["refresh_days"] = 2
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    config = load_raw_config(file)

    assert config.sources["smard"]["refresh_days"] == 2


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


SMARD_VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "smard": {
            "area": "DE_LU",
            "resolution": "15min",
            "methods": [
                {"method": "day_ahead_price"},
                {"method": "load_actual"},
                {"method": "load_forecast"},
                {
                    "method": "generation_actual",
                    "generation_types": ["solar", "wind_offshore", "wind_onshore"],
                },
                {
                    "method": "generation_forecast_day_ahead",
                    "generation_types": ["solar", "wind_offshore", "wind_onshore"],
                },
            ],
        }
    },
}


def smard_config(methods=None, resolution="15min", area="DE_LU"):
    data = json.loads(json.dumps(SMARD_VALID))
    source = data["sources"]["smard"]
    if methods is not None:
        source["methods"] = methods
    source["resolution"] = resolution
    source["area"] = area
    return data


def test_valid_smard_methods(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(SMARD_VALID))

    config = load_raw_config(file)

    methods = config.sources["smard"]["methods"]
    assert methods[3]["generation_types"] == ["solar", "wind_offshore", "wind_onshore"]


@pytest.mark.parametrize(
    "methods, message",
    [
        ([{"method": "bogus"}], "unknown smard method"),
        ([{"method": "generation_actual"}], "generation_types must be"),
        (
            [{"method": "generation_actual", "generation_types": []}],
            "generation_types must be",
        ),
        (
            [{"method": "generation_actual", "generation_types": "solar"}],
            "generation_types must be",
        ),
        (
            [{"method": "generation_actual", "generation_types": [1]}],
            "generation_types must be",
        ),
        ([{"method": "generation_forecast_day_ahead"}], "generation_types must be"),
        ("not a list", "methods must be a list"),
        ([{"method": 5}], "method field"),
    ],
)
def test_invalid_smard_methods(tmp_path, methods, message):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(smard_config(methods=methods)))

    with pytest.raises(ConfigError, match=message):
        load_raw_config(file)


@pytest.mark.parametrize("resolution", ["5min", [], {"value": "15min"}, 15])
def test_invalid_smard_resolution(tmp_path, resolution):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(smard_config(resolution=resolution)))

    with pytest.raises(ConfigError, match="resolution must be 15min or hour"):
        load_raw_config(file)


def test_smard_missing_methods_field(tmp_path):
    data = json.loads(json.dumps(SMARD_VALID))
    del data["sources"]["smard"]["methods"]
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="smard is missing field: methods"):
        load_raw_config(file)


def test_invalid_smard_area(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(smard_config(area=5)))

    with pytest.raises(ConfigError, match="smard area must be a string"):
        load_raw_config(file)


WEATHER_VALID = {
    "start": "2025-10-01",
    "end": "latest",
    "timezone": "Europe/Berlin",
    "storages": ["local"],
    "sources": {
        "weather": {
            "model": "ecmwf_ifs",
            "forecast_days": 16,
            "fields": ["temperature_2m", "wind_speed_100m"],
            "locations": [
                {
                    "name": "berlin",
                    "latitude": 52.52,
                    "longitude": 13.41,
                    "cell_selection": "land",
                },
                {
                    "name": "north_sea_west",
                    "latitude": 54.75,
                    "longitude": 6.30,
                    "cell_selection": "sea",
                },
            ],
        }
    },
}


def weather_config(**overrides):
    data = json.loads(json.dumps(WEATHER_VALID))
    data["sources"]["weather"].update(overrides)
    return data


def test_valid_weather(tmp_path):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(WEATHER_VALID))

    config = load_raw_config(file)

    weather = config.sources["weather"]
    assert weather["model"] == "ecmwf_ifs"
    assert weather["forecast_days"] == 16
    assert weather["locations"][1]["cell_selection"] == "sea"


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"model": "ecmwf_hres"}, "unknown weather model"),
        ({"model": 5}, "unknown weather model"),
        ({"forecast_days": 0}, "forecast_days must be"),
        ({"forecast_days": 17}, "forecast_days must be"),
        ({"forecast_days": "16"}, "forecast_days must be"),
        ({"fields": []}, "fields must be a non-empty list"),
        ({"fields": "temperature_2m"}, "fields must be a non-empty list"),
        ({"fields": ["bogus"]}, "unknown weather field"),
        ({"locations": []}, "locations must be a non-empty list"),
        ({"locations": {}}, "locations must be a non-empty list"),
    ],
)
def test_invalid_weather_source(tmp_path, overrides, message):
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(weather_config(**overrides)))

    with pytest.raises(ConfigError, match=message):
        load_raw_config(file)


def test_weather_location_missing_field(tmp_path):
    data = weather_config()
    del data["sources"]["weather"]["locations"][0]["latitude"]
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="missing field: latitude"):
        load_raw_config(file)


@pytest.mark.parametrize(
    "location, message",
    [
        (
            {
                "name": "dup",
                "latitude": 52.0,
                "longitude": 13.0,
                "cell_selection": "land",
            },
            "duplicate weather location",
        ),
        (
            {"name": 5, "latitude": 52.0, "longitude": 13.0, "cell_selection": "land"},
            "name must be a string",
        ),
        (
            {
                "name": "x",
                "latitude": 91.0,
                "longitude": 13.0,
                "cell_selection": "land",
            },
            "latitude must be within -90 and 90",
        ),
        (
            {
                "name": "x",
                "latitude": 52.0,
                "longitude": -181.0,
                "cell_selection": "land",
            },
            "longitude must be within -180 and 180",
        ),
        (
            {
                "name": "x",
                "latitude": "52.0",
                "longitude": 13.0,
                "cell_selection": "land",
            },
            "latitude must be a number",
        ),
        (
            {"name": "x", "latitude": 52.0, "longitude": 13.0, "cell_selection": "air"},
            "cell_selection must be land, sea or nearest",
        ),
    ],
)
def test_invalid_weather_location(tmp_path, location, message):
    data = weather_config()
    locations = data["sources"]["weather"]["locations"]
    if location["name"] == "dup":
        locations.append(dict(location, name=locations[0]["name"]))
    else:
        locations.append(location)
    file = tmp_path / "raw.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match=message):
        load_raw_config(file)
