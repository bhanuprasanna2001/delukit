from copy import deepcopy

import pytest

from delukit.layers.bronze.semantic import semantic_hash

ENTSOE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-6:generationloaddocument:3:0">'
    "<mRID>d59f167b37e5458eb94e6972dfba455c</mRID>"
    "<revisionNumber>1</revisionNumber>"
    "<createdDateTime>2026-09-16T15:36:12Z</createdDateTime>"
    "<TimeSeries>"
    "<mRID>1</mRID>"
    "<businessType>A01</businessType>"
    "<Period>"
    "<timeInterval><start>2026-09-15T22:00Z</start><end>2026-09-16T15:00Z</end></timeInterval>"
    "<resolution>PT15M</resolution>"
    "<Point><position>1</position><quantity>0</quantity></Point>"
    "<Point><position>2</position><quantity>42.5</quantity></Point>"
    "</Period>"
    "</TimeSeries>"
    "</GL_MarketDocument>"
)

SMARD = (
    '{"meta_data": {"created": "2026-09-16T10:00:00Z", "version": 1},'
    ' "series": [[1789250400000, 42.5], [1789251300000, 43.0]]}'
)

ENERGY_CHARTS = (
    '{"license_info": "CC BY 4.0", "unix_seconds": [1, 2],'
    ' "price": [40.0, 41.0], "unit": "EUR / MWh", "deprecated": false}'
)

WEATHER = {
    "run": "2026-09-16T00:00",
    "model": "ecmwf_ifs",
    "locations": {
        "berlin": {
            "generationtime_ms": 1.606,
            "elevation": 40.0,
            "hourly": {"time": ["2026-09-16T02:00"], "temperature_2m": [21.5]},
        },
        "kiel": {
            "generationtime_ms": 2.718,
            "elevation": 5.0,
            "hourly": {"time": ["2026-09-16T02:00"], "temperature_2m": [20.0]},
        },
    },
}


def test_entsoe_volatile_metadata_ignored():
    changed = (
        ENTSOE.replace(
            "d59f167b37e5458eb94e6972dfba455c", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        .replace(
            "<revisionNumber>1</revisionNumber>", "<revisionNumber>7</revisionNumber>"
        )
        .replace("2026-09-16T15:36:12Z", "2026-09-16T23:59:59Z")
    )
    assert semantic_hash("entsoe", changed) == semantic_hash("entsoe", ENTSOE)


def test_entsoe_quantity_change_detected():
    changed = ENTSOE.replace("<quantity>42.5</quantity>", "<quantity>43.0</quantity>")
    assert semantic_hash("entsoe", changed) != semantic_hash("entsoe", ENTSOE)


def test_entsoe_timeseries_mrid_ignored():
    changed = ENTSOE.replace("<TimeSeries><mRID>1</mRID>", "<TimeSeries><mRID>9</mRID>")
    assert semantic_hash("entsoe", changed) == semantic_hash("entsoe", ENTSOE)


def test_entsoe_without_timeseries_raises():
    with pytest.raises(ValueError, match="no TimeSeries"):
        semantic_hash("entsoe", "<GL_MarketDocument></GL_MarketDocument>")


def test_smard_meta_data_ignored():
    changed = SMARD.replace('"version": 1', '"version": 2').replace(
        "2026-09-16T10:00:00Z", "2026-09-17T10:00:00Z"
    )
    assert semantic_hash("smard", changed) == semantic_hash("smard", SMARD)


def test_smard_series_change_detected():
    changed = SMARD.replace("43.0", "44.0")
    assert semantic_hash("smard", changed) != semantic_hash("smard", SMARD)


def test_energy_charts_license_ignored():
    changed = ENERGY_CHARTS.replace("CC BY 4.0", "CC BY 4.1")
    assert semantic_hash("energy_charts", changed) == semantic_hash(
        "energy_charts", ENERGY_CHARTS
    )


def test_energy_charts_price_change_detected():
    changed = ENERGY_CHARTS.replace("41.0", "42.0")
    assert semantic_hash("energy_charts", changed) != semantic_hash(
        "energy_charts", ENERGY_CHARTS
    )


def test_weather_generation_time_ignored():
    changed = deepcopy(WEATHER)
    changed["locations"]["berlin"]["generationtime_ms"] = 9.999
    assert semantic_hash("weather", changed) == semantic_hash("weather", WEATHER)


def test_weather_value_change_detected():
    changed = deepcopy(WEATHER)
    changed["locations"]["berlin"]["hourly"]["temperature_2m"] = [20.0]
    assert semantic_hash("weather", changed) != semantic_hash("weather", WEATHER)


def test_weather_location_order_ignored():
    reordered = deepcopy(WEATHER)
    reordered["locations"] = dict(reversed(list(reordered["locations"].items())))
    assert semantic_hash("weather", reordered) == semantic_hash("weather", WEATHER)


def test_hash_is_sha256_hex():
    digest = semantic_hash("smard", SMARD)
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_unknown_source_raises():
    with pytest.raises(ValueError, match="unknown source"):
        semantic_hash("bogus", "{}")
