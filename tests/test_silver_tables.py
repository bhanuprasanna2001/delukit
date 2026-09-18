import pytest

from delukit.layers.silver.tables import (
    domain_for,
    keys_for,
    split_table,
    table_for,
)


def test_table_names_keep_source_separate():
    assert table_for("smard", "day_ahead_price") == "smard_day_ahead_price"
    assert table_for("entsoe", "day_ahead_price") == "entsoe_day_ahead_price"
    assert (
        table_for("energy_charts", "day_ahead_price") == "energy_charts_day_ahead_price"
    )
    assert table_for("weather", "forecast") == "weather_forecast"


def test_split_round_trips_underscored_sources():
    assert split_table("energy_charts_day_ahead_price") == (
        "energy_charts",
        "day_ahead_price",
    )
    assert split_table("smard_generation_forecast_day_ahead") == (
        "smard",
        "generation_forecast_day_ahead",
    )
    with pytest.raises(ValueError, match="unknown silver table"):
        split_table("bogus_table")


def test_domains_group_by_business_area():
    assert domain_for("day_ahead_price") == "prices"
    assert domain_for("load_actual") == "load"
    assert domain_for("load_forecast") == "load"
    assert domain_for("generation_actual") == "generation"
    assert domain_for("generation_forecast") == "generation"
    assert domain_for("generation_forecast_day_ahead") == "generation"
    assert domain_for("forecast") == "weather"
    with pytest.raises(ValueError, match="unknown silver method"):
        domain_for("bogus")


def test_keys_use_native_type_columns():
    assert keys_for("smard", "day_ahead_price") == ["timestamp", "sequence"]
    assert keys_for("entsoe", "day_ahead_price") == ["timestamp", "sequence"]
    assert keys_for("smard", "load_actual") == ["timestamp"]
    assert keys_for("entsoe", "load_forecast") == ["timestamp"]
    assert keys_for("smard", "generation_actual") == [
        "timestamp",
        "generation_type",
    ]
    assert keys_for("smard", "generation_forecast_day_ahead") == [
        "timestamp",
        "generation_type",
    ]
    assert keys_for("entsoe", "generation_actual") == ["timestamp", "psr_type"]
    assert keys_for("entsoe", "generation_forecast") == ["timestamp", "psr_type"]
    assert keys_for("weather", "forecast") == ["run_time", "location", "valid_time"]
    with pytest.raises(ValueError, match="unknown silver table"):
        keys_for("smard", "forecast")
