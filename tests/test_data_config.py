import json
from pathlib import Path

import pytest

from delukit.core.config import ConfigError, load_data_config


def test_repo_data_config_loads():
    path = Path(__file__).parents[1] / "configs" / "data.json"
    config = load_data_config(path)

    assert set(config.sources) == {"smard", "entsoe", "energy_charts", "weather"}
    assert config.storages == ["local", "databricks"]
    assert "fetch_policy" not in json.dumps(config.sources["energy_charts"])


def test_data_config_reuses_raw_validation(tmp_path):
    file = tmp_path / "data.json"
    file.write_text(json.dumps({"start": "2025-10-01"}))

    with pytest.raises(ConfigError, match="missing required field"):
        load_data_config(file)


def test_data_config_rejects_unknown_source(tmp_path):
    file = tmp_path / "data.json"
    file.write_text(
        json.dumps(
            {
                "start": "2025-10-01",
                "end": "latest",
                "timezone": "Europe/Berlin",
                "storages": ["local"],
                "sources": {"bogus": {}},
            }
        )
    )

    with pytest.raises(ConfigError, match="unknown source"):
        load_data_config(file)


def test_data_config_ignores_fetch_policy(tmp_path):
    file = tmp_path / "data.json"
    file.write_text(
        json.dumps(
            {
                "start": "2025-10-01",
                "end": "latest",
                "timezone": "Europe/Berlin",
                "storages": ["local"],
                "sources": {
                    "energy_charts": {
                        "methods": [
                            {
                                "bidding_zone": "DE-LU",
                                "method": "day_ahead_price",
                                "fetch_policy": {"mode": "fallback"},
                            }
                        ]
                    }
                },
            }
        )
    )

    config = load_data_config(file)

    assert config.sources["energy_charts"]["methods"][0]["method"] == "day_ahead_price"
