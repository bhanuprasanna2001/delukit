import json
from pathlib import Path

import pytest

from delukit.core.config import ConfigError, PipelineConfig, load_pipeline_config

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


def test_load_valid_config(tmp_path):
    file = tmp_path / "config.json"
    file.write_text(json.dumps(VALID))

    config = load_pipeline_config(file)

    assert isinstance(config, PipelineConfig)
    assert config.storages == ["local"]
    assert config.sources["smard"]["area"] == "DE_LU"


def test_malformed_json(tmp_path):
    file = tmp_path / "config.json"
    file.write_text("{not json")

    with pytest.raises(ConfigError, match="not valid json"):
        load_pipeline_config(file)


def test_missing_file():
    with pytest.raises(ConfigError, match="not found"):
        load_pipeline_config("nope.json")


def test_missing_field(tmp_path):
    data = {key: value for key, value in VALID.items() if key != "timezone"}
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="timezone"):
        load_pipeline_config(file)


def test_bad_date(tmp_path):
    data = {**VALID, "start": "2025/10/01"}
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="iso date"):
        load_pipeline_config(file)


def test_unknown_source(tmp_path):
    data = {**VALID, "sources": {**VALID["sources"], "nope": {}}}
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="unknown source"):
        load_pipeline_config(file)


def test_repo_pipeline_config_loads():
    path = Path(__file__).parents[1] / "configs" / "pipeline.json"
    config = load_pipeline_config(path)

    assert str(config.start) == "2025-10-01"
    assert set(config.sources) == {"smard", "entsoe", "energy_charts", "weather"}


def test_unknown_storage(tmp_path):
    data = {**VALID, "storages": ["local", "bogus"]}
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="unknown storage"):
        load_pipeline_config(file)


def test_storages_may_omit_local(tmp_path):
    for storages in (["databricks"], ["snowflake"], ["databricks", "snowflake"]):
        data = {**VALID, "storages": storages}
        file = tmp_path / "config.json"
        file.write_text(json.dumps(data))

        assert load_pipeline_config(file).storages == storages


def test_storages_must_be_non_empty(tmp_path):
    data = {**VALID, "storages": []}
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="non-empty"):
        load_pipeline_config(file)


@pytest.mark.parametrize("value", [0, -3, 2.5, "7", True])
def test_invalid_refresh_days(tmp_path, value):
    data = json.loads(json.dumps(VALID))
    data["sources"]["smard"]["refresh_days"] = value
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="refresh_days"):
        load_pipeline_config(file)


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
    file = tmp_path / "config.json"
    file.write_text(json.dumps(energy_charts_config(methods)))

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(file)


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
    file = tmp_path / "config.json"
    file.write_text(json.dumps(entsoe_config(methods)))

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(file)


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
    file = tmp_path / "config.json"
    file.write_text(json.dumps(smard_config(methods=methods)))

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(file)


@pytest.mark.parametrize("resolution", ["5min", [], {"value": "15min"}, 15])
def test_invalid_smard_resolution(tmp_path, resolution):
    file = tmp_path / "config.json"
    file.write_text(json.dumps(smard_config(resolution=resolution)))

    with pytest.raises(ConfigError, match="resolution must be 15min or hour"):
        load_pipeline_config(file)


def test_invalid_smard_source_shape(tmp_path):
    data = json.loads(json.dumps(SMARD_VALID))
    del data["sources"]["smard"]["methods"]
    with pytest.raises(ConfigError, match="smard is missing field: methods"):
        load_pipeline_config(write_config(data, tmp_path))

    with pytest.raises(ConfigError, match="smard area must be a string"):
        load_pipeline_config(write_config(smard_config(area=5), tmp_path))


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
    file = tmp_path / "config.json"
    file.write_text(json.dumps(weather_config(**overrides)))

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(file)


def test_weather_location_missing_field(tmp_path):
    data = weather_config()
    del data["sources"]["weather"]["locations"][0]["latitude"]
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match="missing field: latitude"):
        load_pipeline_config(file)


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
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(file)


GOLD_VALID = {
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
                {"method": "load_forecast"},
                {
                    "method": "generation_forecast_day_ahead",
                    "generation_types": ["wind_onshore"],
                },
            ],
        },
        "entsoe": {
            "methods": [
                {"area": "DE_LU", "method": "day_ahead_price", "sequences": [1, 2]},
                {"area": "DE_LU", "method": "load_forecast"},
                {
                    "area": "DE_LU",
                    "method": "generation_forecast",
                    "psr_types": ["B18"],
                },
            ]
        },
        "energy_charts": {
            "methods": [{"bidding_zone": "DE-LU", "method": "day_ahead_price"}]
        },
        "weather": {
            "model": "ecmwf_ifs",
            "forecast_days": 16,
            "fields": [
                "temperature_2m",
                "wind_speed_100m",
                "wind_direction_100m",
            ],
            "locations": [
                {
                    "name": "berlin",
                    "latitude": 52.52,
                    "longitude": 13.41,
                    "cell_selection": "land",
                },
                {
                    "name": "hamburg",
                    "latitude": 53.55,
                    "longitude": 9.99,
                    "cell_selection": "land",
                },
                {
                    "name": "north_sea_west",
                    "latitude": 54.75,
                    "longitude": 6.30,
                    "cell_selection": "sea",
                },
            ],
        },
    },
    "gold": {
        "calendar": {
            "country": "DE",
            "holiday_source": "open_holidays",
            "features": ["hour", "is_holiday", "is_bridge_day"],
        },
        "datasets": [
            {
                "name": "features",
                "grain": "hour",
                "series": [
                    {
                        "name": "price",
                        "from": [
                            {
                                "source": "entsoe",
                                "method": "day_ahead_price",
                                "sequence": 2,
                            },
                            {"source": "smard", "method": "day_ahead_price"},
                            {
                                "source": "energy_charts",
                                "method": "day_ahead_price",
                            },
                        ],
                        "upsample": "ffill",
                        "transforms": [
                            {"type": "lag", "offsets_h": [24, 168]},
                            {
                                "type": "rolling",
                                "agg": ["mean", "std"],
                                "windows_h": [24],
                                "min_periods": 12,
                            },
                            {"type": "diff", "offsets_h": [1]},
                            {"type": "asinh"},
                        ],
                    },
                    {
                        "name": "wind_onshore",
                        "from": [
                            {
                                "source": "entsoe",
                                "method": "generation_forecast",
                                "psr_type": "B18",
                            },
                            {
                                "source": "smard",
                                "method": "generation_forecast_day_ahead",
                                "generation_type": "wind_onshore",
                            },
                        ],
                    },
                ],
                "weather": {
                    "run_policy": "day_ahead_gate",
                    "fields": [
                        "temperature_2m",
                        "wind_speed_100m",
                        "wind_direction_100m",
                    ],
                    "regions": {
                        "land": {
                            "locations": ["berlin", "hamburg"],
                            "method": "mean",
                        },
                        "sea": {"locations": ["north_sea_west"], "method": "mean"},
                    },
                    "national": {"method": "region_mean"},
                    "derived": [
                        {
                            "type": "hdd",
                            "from": "temperature_2m",
                            "base_c": 15.5,
                        },
                        {"type": "wind_power_proxy", "from": "wind_speed_100m"},
                    ],
                    "transforms": [{"type": "lag", "offsets_h": [24]}],
                },
            }
        ],
    },
}


def gold_data():
    return json.loads(json.dumps(GOLD_VALID))


def write_config(data, tmp_path):
    file = tmp_path / "config.json"
    file.write_text(json.dumps(data))
    return file


_DELETE = object()


def _set(data, path, value):
    node = data
    for key in path[:-1]:
        node = node[key]
    if value is _DELETE:
        del node[path[-1]]
    else:
        node[path[-1]] = value


def test_gold_absent_or_null_is_none(tmp_path):
    data = gold_data()
    del data["gold"]
    assert load_pipeline_config(write_config(data, tmp_path)).gold is None

    data = gold_data()
    data["gold"] = None
    assert load_pipeline_config(write_config(data, tmp_path)).gold is None


def test_gold_entsoe_price_defaults_to_sdac(tmp_path):
    data = gold_data()
    del data["gold"]["datasets"][0]["series"][0]["from"][0]["sequence"]

    config = load_pipeline_config(write_config(data, tmp_path))

    assert config.gold["datasets"][0]["series"][0]["from"][0] == {
        "source": "entsoe",
        "method": "day_ahead_price",
    }


def test_gold_optional_sections_may_be_absent(tmp_path):
    data = gold_data()
    del data["gold"]["calendar"]
    assert "calendar" not in load_pipeline_config(write_config(data, tmp_path)).gold

    data = gold_data()
    del data["gold"]["datasets"][0]["weather"]
    gold = load_pipeline_config(write_config(data, tmp_path)).gold
    assert "weather" not in gold["datasets"][0]

    data = gold_data()
    data["gold"]["datasets"][0]["target"] = None
    gold = load_pipeline_config(write_config(data, tmp_path)).gold
    assert gold["datasets"][0].get("target") is None


def test_gold_duplicates_rejected(tmp_path):
    data = gold_data()
    data["gold"]["datasets"].append(json.loads(json.dumps(data["gold"]["datasets"][0])))
    with pytest.raises(ConfigError, match="duplicate gold dataset"):
        load_pipeline_config(write_config(data, tmp_path))

    data = gold_data()
    dataset = data["gold"]["datasets"][0]
    dataset["series"].append(json.loads(json.dumps(dataset["series"][0])))
    with pytest.raises(ConfigError, match="duplicate gold series"):
        load_pipeline_config(write_config(data, tmp_path))

    data = gold_data()
    entries = data["gold"]["datasets"][0]["series"][0]["from"]
    entries.append(json.loads(json.dumps(entries[0])))
    with pytest.raises(ConfigError, match="duplicate gold series from entry"):
        load_pipeline_config(write_config(data, tmp_path))

    data = gold_data()
    entries = data["gold"]["datasets"][0]["series"][0]["from"]
    entries.append({"source": "entsoe", "method": "day_ahead_price"})
    entries.append({"source": "entsoe", "method": "day_ahead_price", "sequence": 1})
    with pytest.raises(ConfigError, match="duplicate gold series from entry"):
        load_pipeline_config(write_config(data, tmp_path))

    data = gold_data()
    transforms = data["gold"]["datasets"][0]["series"][0]["transforms"]
    transforms.append(json.loads(json.dumps(transforms[0])))
    with pytest.raises(ConfigError, match="duplicate transform"):
        load_pipeline_config(write_config(data, tmp_path))

    data = gold_data()
    derived = data["gold"]["datasets"][0]["weather"]["derived"]
    derived.append(json.loads(json.dumps(derived[0])))
    with pytest.raises(ConfigError, match="duplicate derived feature"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_region_name_must_be_snake_case(tmp_path):
    data = gold_data()
    regions = data["gold"]["datasets"][0]["weather"]["regions"]
    regions["N1"] = regions.pop("land")

    with pytest.raises(ConfigError, match="region name must be a lowercase"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_entsoe_sequence_not_fetched(tmp_path):
    data = gold_data()
    for method in data["sources"]["entsoe"]["methods"]:
        if method["method"] == "day_ahead_price":
            method["sequences"] = [1]

    with pytest.raises(ConfigError, match="sequence 2 is not configured for fetch"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_weather_requires_weather_source(tmp_path):
    data = gold_data()
    del data["sources"]["weather"]

    with pytest.raises(ConfigError, match="requires a configured weather source"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_region_weights_must_cover_exactly(tmp_path):
    data = gold_data()
    region = data["gold"]["datasets"][0]["weather"]["regions"]["land"]
    region["method"] = "weighted_mean"
    region["weights"] = {"berlin": 1.0}

    with pytest.raises(ConfigError, match="weights must cover exactly"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_region_weights_must_be_positive(tmp_path):
    data = gold_data()
    region = data["gold"]["datasets"][0]["weather"]["regions"]["land"]
    region["method"] = "weighted_mean"
    region["weights"] = {"berlin": 0, "hamburg": 2}

    with pytest.raises(ConfigError, match="weights must be positive"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_national_region_weights_must_cover_all(tmp_path):
    data = gold_data()
    national = data["gold"]["datasets"][0]["weather"]["national"]
    national["method"] = "region_weighted_mean"
    national["region_weights"] = {"land": 1.0}

    with pytest.raises(ConfigError, match="weights must cover exactly"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_weighted_region_is_valid(tmp_path):
    data = gold_data()
    weather = data["gold"]["datasets"][0]["weather"]
    land = weather["regions"]["land"]
    land["method"] = "weighted_mean"
    land["weights"] = {"berlin": 2.0, "hamburg": 1.0}
    national = weather["national"]
    national["method"] = "region_weighted_mean"
    national["region_weights"] = {"land": 3.0, "sea": 1.0}

    config = load_pipeline_config(write_config(data, tmp_path))

    assert config.gold["datasets"][0]["weather"]["regions"]["land"]["weights"] == {
        "berlin": 2.0,
        "hamburg": 1.0,
    }


_SERIES = ("gold", "datasets", 0, "series")
_PRICE = _SERIES + (0,)
_WIND = _SERIES + (1,)
_WEATHER = ("gold", "datasets", 0, "weather")
_CALENDAR = ("gold", "calendar")


@pytest.mark.parametrize(
    "path, value, message",
    [
        (("gold",), "nope", "gold must be an object"),
        (("gold", "bogus"), 1, "gold: unknown field"),
        (("gold", "datasets"), _DELETE, "non-empty list"),
        (("gold", "datasets"), [], "non-empty list"),
        (("gold", "datasets"), ["nope"], "must be objects"),
        (_CALENDAR, "nope", "gold calendar must be an object"),
        (_CALENDAR + ("bogus",), 1, "gold calendar: unknown field"),
        (_CALENDAR + ("country",), "DEU", "two-letter ISO"),
        (_CALENDAR + ("country",), 5, "two-letter ISO"),
        (_CALENDAR + ("holiday_source",), {"mode": "x"}, "open_holidays or none"),
        (_CALENDAR + ("holiday_source",), "none", "requires holiday_source"),
        (
            _CALENDAR + ("holiday_scope",),
            ["nationwide"],
            "nationwide or any_subdivision",
        ),
        (_CALENDAR + ("features",), "hour", "features must be a list"),
        (
            _CALENDAR + ("features",),
            [{"name": "hour"}],
            "unknown gold calendar feature",
        ),
        (_CALENDAR + ("features",), ["bogus"], "unknown gold calendar feature"),
        (
            _CALENDAR + ("features",),
            ["hour", "hour"],
            "duplicate gold calendar feature",
        ),
        (("gold", "datasets", 0, "bogus"), 1, "gold dataset: unknown field"),
        (("gold", "datasets", 0, "name"), "Features", "snake_case name"),
        (("gold", "datasets", 0, "grain"), "hourly", "grain must be 15min or hour"),
        (("gold", "datasets", 0, "grain"), {}, "grain must be 15min or hour"),
        (("gold", "datasets", 0, "series"), [], "series must be a non-empty list"),
        (_PRICE + ("bogus",), 1, "gold series in features: unknown field"),
        (_PRICE + ("name",), "Price", "snake_case name"),
        (_PRICE + ("upsample",), "nearest", "ffill or interpolate"),
        (_PRICE + ("upsample",), {}, "ffill or interpolate"),
        (_PRICE + ("from",), [], "from must be a non-empty list"),
        (_PRICE + ("from",), ["nope"], "from entries must be objects"),
        (_PRICE + ("from", 0, "bogus"), 1, "unknown field"),
        (_PRICE + ("from", 0, "source"), {"name": "smard"}, "unknown source"),
        (_PRICE + ("from", 0, "source"), "weather", "weather block"),
        (_PRICE + ("from", 0, "source"), "nope", "unknown source"),
        (_PRICE + ("from", 0, "method"), "load_actual", "not configured for fetch"),
        (_PRICE + ("from", 0, "sequence"), 3, "must be 1 \\(SDAC\\) or 2 \\(EXAA\\)"),
        (
            _PRICE + ("from", 0, "sequence"),
            True,
            "must be 1 \\(SDAC\\) or 2 \\(EXAA\\)",
        ),
        (_PRICE + ("from", 0, "sequence"), 2.0, "must be 1 \\(SDAC\\) or 2 \\(EXAA\\)"),
        (_PRICE + ("from", 1, "sequence"), 1, "only valid for entsoe day_ahead_price"),
        (_PRICE + ("from", 0, "psr_type"), "B18", "only valid for entsoe generation"),
        (
            _PRICE + ("from", 0, "generation_type"),
            "solar",
            "only valid for smard generation",
        ),
        (_WIND + ("from", 0, "psr_type"), _DELETE, "requires psr_type"),
        (_WIND + ("from", 0, "psr_type"), "B99", "not configured for fetch"),
        (_WIND + ("from", 0, "psr_type"), {}, "requires psr_type"),
        (_WIND + ("from", 1, "generation_type"), _DELETE, "requires generation_type"),
        (_WIND + ("from", 1, "generation_type"), "solar", "not configured for fetch"),
        (_WIND + ("from", 0, "sequence"), 1, "only valid for entsoe day_ahead_price"),
        (_PRICE + ("transforms",), "nope", "transforms must be a list"),
        (_PRICE + ("transforms",), ["nope"], "transforms must be objects"),
        (_PRICE + ("transforms", 0, "type"), "bogus", "unknown gold transform"),
        (_PRICE + ("transforms", 0, "type"), {}, "unknown gold transform"),
        (
            _PRICE + ("transforms", 0, "offsets_h"),
            _DELETE,
            "lag offsets_h must be a non-empty",
        ),
        (_PRICE + ("transforms", 0, "offsets_h"), [0], "positive integers"),
        (
            _PRICE + ("transforms", 0, "offsets_h"),
            [24, 24],
            "must not contain duplicates",
        ),
        (_PRICE + ("transforms", 1, "agg"), _DELETE, "agg must be a non-empty list"),
        (_PRICE + ("transforms", 1, "agg"), ["sum"], "mean, std, min or max"),
        (
            _PRICE + ("transforms", 1, "agg"),
            ["mean", "mean"],
            "agg must not contain duplicates",
        ),
        (
            _PRICE + ("transforms", 1, "windows_h"),
            _DELETE,
            "rolling windows_h must be a non-empty",
        ),
        (
            _PRICE + ("transforms", 1, "min_periods"),
            0,
            "min_periods must be an integer >= 1",
        ),
        (
            _PRICE + ("transforms", 1, "min_periods"),
            True,
            "min_periods must be an integer >= 1",
        ),
        (_PRICE + ("transforms", 3, "offsets_h"), [1], "unknown field"),
        (_WEATHER, "nope", "weather must be an object"),
        (_WEATHER + ("bogus",), 1, "weather: unknown field"),
        (_WEATHER + ("run_policy",), "gates", "latest or day_ahead_gate"),
        (_WEATHER + ("run_policy",), {}, "latest or day_ahead_gate"),
        (_WEATHER + ("fields",), [], "non-empty list of strings"),
        (
            _WEATHER + ("fields",),
            ["temperature_2m", "bogus"],
            "not fetched by the weather",
        ),
        (
            _WEATHER + ("fields",),
            ["temperature_2m", "temperature_2m"],
            "must not contain duplicates",
        ),
        (_WEATHER + ("regions",), {}, "regions must be a non-empty object"),
        (
            _WEATHER + ("regions", "land", "method"),
            "sum",
            "mean, weighted_mean, min, max or median",
        ),
        (
            _WEATHER + ("regions", "land", "method"),
            "max",
            "directional fields aggregate",
        ),
        (
            _WEATHER + ("regions", "land", "method"),
            "weighted_mean",
            "weighted_mean requires weights",
        ),
        (
            _WEATHER + ("regions", "land", "method"),
            {},
            "mean, weighted_mean, min, max or median",
        ),
        (
            _WEATHER + ("regions", "land", "weights"),
            {"berlin": 1, "hamburg": 1},
            "require method: weighted_mean",
        ),
        (
            _WEATHER + ("regions", "land", "locations"),
            "berlin",
            "non-empty list of strings",
        ),
        (
            _WEATHER + ("regions", "land", "locations"),
            ["berlin", "nowhere"],
            "unknown location",
        ),
        (
            _WEATHER + ("regions", "land", "locations"),
            ["berlin"],
            "not assigned to any region",
        ),
        (
            _WEATHER + ("regions", "sea", "locations"),
            ["berlin", "north_sea_west"],
            "multiple regions",
        ),
        (
            _WEATHER + ("national", "method"),
            "median",
            "region_mean or region_weighted_mean",
        ),
        (
            _WEATHER + ("national", "method"),
            "region_weighted_mean",
            "requires region_weights",
        ),
        (
            _WEATHER + ("national", "region_weights"),
            {"land": 1, "sea": 1},
            "require method: region_weighted_mean",
        ),
        (
            _WEATHER + ("include_locations",),
            True,
            "weather: unknown field",
        ),
        (_WEATHER + ("levels",), "national", "levels must be a non-empty list"),
        (_WEATHER + ("levels",), [], "levels must be a non-empty list"),
        (
            _WEATHER + ("levels",),
            ["national", "national"],
            "levels must not contain duplicates",
        ),
        (_WEATHER + ("levels",), ["planetary"], "unknown level"),
        (
            _WEATHER + ("transforms", 0, "applies_to"),
            ["bogus_field"],
            "applies_to has unknown input",
        ),
        (
            _WEATHER + ("transforms", 0, "applies_to"),
            [],
            "applies_to must be a non-empty list",
        ),
        (
            _WEATHER + ("transforms", 0, "applies_to"),
            ["temperature_2m", "temperature_2m"],
            "applies_to must not contain duplicates",
        ),
        (
            _PRICE + ("transforms", 0, "applies_to"),
            ["temperature_2m"],
            "unknown field",
        ),
        (_WEATHER + ("derived",), "nope", "derived must be a list"),
        (
            _WEATHER + ("derived", 0, "type"),
            "wind_chill",
            "unknown gold weather derived type",
        ),
        (_WEATHER + ("derived", 0, "type"), {}, "unknown gold weather derived type"),
        (_WEATHER + ("derived", 0, "base_c"), _DELETE, "requires base_c"),
        (_WEATHER + ("derived", 0, "base_c"), True, "requires base_c"),
        (_WEATHER + ("derived", 0, "from"), "cloud_cover", "from field not selected"),
        (
            _WEATHER + ("derived", 0, "from"),
            "wind_direction_100m",
            "cannot use a directional field",
        ),
        (
            _WEATHER + ("derived", 1, "from"),
            "temperature_2m",
            "requires a wind_speed field",
        ),
        (_WEATHER + ("derived", 0, "bogus"), 1, "derived hdd: unknown field"),
        (_WEATHER + ("transforms", 0, "offsets_h"), [0], "positive integers"),
    ],
)
def test_invalid_gold(tmp_path, path, value, message):
    data = gold_data()
    _set(data, path, value)

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(write_config(data, tmp_path))


def _dataset_with_contract(data):
    """Minimal valid target+columns over GOLD_VALID's first dataset."""
    dataset = data["gold"]["datasets"][0]
    dataset["target"] = "price"
    dataset["columns"] = [
        "price",
        "price_lag_24h",
        "wind_onshore",
        "hour",
        "temperature_2m__national",
        "temperature_2m__national_lag_24h",
        "hdd__temperature_2m__national",
    ]
    return data


def test_gold_target_and_columns_load(tmp_path):
    data = _dataset_with_contract(gold_data())

    config = load_pipeline_config(write_config(data, tmp_path))

    dataset = config.gold["datasets"][0]
    assert dataset["target"] == "price"
    assert dataset["columns"][1] == "price_lag_24h"
    assert "temperature_2m__national_lag_24h" in dataset["columns"]


def test_gold_target_must_be_a_series(tmp_path):
    data = gold_data()
    data["gold"]["datasets"][0]["target"] = "bogus"

    with pytest.raises(ConfigError, match="target must be one of its series"):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_target_must_be_listed_in_columns(tmp_path):
    data = _dataset_with_contract(gold_data())
    data["gold"]["datasets"][0]["columns"].remove("price")

    with pytest.raises(ConfigError, match="target .* must be listed in columns"):
        load_pipeline_config(write_config(data, tmp_path))


@pytest.mark.parametrize(
    "columns, message",
    [
        ([], "columns must be a non-empty list"),
        ("price", "columns must be a non-empty list"),
        (["price", "price"], "columns must not contain duplicates"),
        (["price", "timestamp"], "must not list timestamp"),
        (["price", "temp_national"], "unknown column"),
        (["price", "temperature_2m__berlin"], "unknown column"),
        (["price", "price_lag_99h"], "unknown column"),
        (["price", "cloud_cover__national"], "unknown column"),
    ],
)
def test_gold_columns_rejections(tmp_path, columns, message):
    data = _dataset_with_contract(gold_data())
    data["gold"]["datasets"][0]["columns"] = columns

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(write_config(data, tmp_path))


def test_gold_columns_reject_unscoped_weather_lag(tmp_path):
    """Lag of an unselected input is unknowable: applies_to excludes wind,
    so the wind lag column cannot exist."""
    data = gold_data()
    dataset = data["gold"]["datasets"][0]
    dataset["weather"]["transforms"] = [
        {"type": "lag", "offsets_h": [24], "applies_to": ["temperature_2m"]}
    ]
    dataset["target"] = "price"
    dataset["columns"] = ["price", "wind_speed_100m__national_lag_24h"]

    with pytest.raises(ConfigError, match="unknown column"):
        load_pipeline_config(write_config(data, tmp_path))


@pytest.mark.parametrize(
    "levels",
    [["location"], ["region"], ["national"], ["location", "region", "national"]],
)
def test_gold_levels_select_aggregation_grain(tmp_path, levels):
    """C=25 (location), C=5 (region), C=1 (national): any non-empty subset."""
    data = gold_data()
    data["gold"]["datasets"][0]["weather"]["levels"] = levels

    config = load_pipeline_config(write_config(data, tmp_path))

    assert config.gold["datasets"][0]["weather"]["levels"] == levels


@pytest.mark.parametrize(
    "path, message",
    [
        (("gold", "calendar"), "gold calendar must be an object"),
        (("gold", "datasets", 0, "weather"), "weather must be an object"),
        (
            ("gold", "datasets", 0, "series", 0, "transforms"),
            "transforms must be a list",
        ),
        (
            ("gold", "datasets", 0, "weather", "transforms"),
            "transforms must be a list",
        ),
        (("gold", "datasets", 0, "weather", "derived"), "derived must be a list"),
        (("gold", "datasets", 0, "weather", "levels"), "levels must be a non-empty"),
        (("gold", "datasets", 0, "weather", "national"), "national must be an object"),
        (("gold", "calendar", "features"), "features must be a list"),
    ],
)
def test_gold_explicit_null_is_rejected(tmp_path, path, message):
    """Explicit null is not absent (legacy parity) — only top-level gold
    and target treat null as omitted."""
    data = gold_data()
    _set(data, path, None)

    with pytest.raises(ConfigError, match=message):
        load_pipeline_config(write_config(data, tmp_path))
