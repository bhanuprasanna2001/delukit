import json
from datetime import date, datetime

from delukit.layers.bronze.records import make_records
from delukit.layers.bronze.semantic import semantic_hash
from delukit.layers.bronze.tables import RECORD_COLUMNS

FETCHED_AT = datetime(2026, 9, 16, 6, 0, 0)  # noqa: DTZ001 — naive UTC by design
DAY = date(2026, 9, 15)


def test_one_row_per_day_and_key():
    raws = {
        DAY: {
            "day_ahead_price/1": "<GL_MarketDocument><TimeSeries/></GL_MarketDocument>",
            "day_ahead_price/2": "<GL_MarketDocument><TimeSeries/></GL_MarketDocument>",
        },
        date(2026, 9, 16): {},
    }
    rows = make_records("entsoe", raws, FETCHED_AT)

    assert len(rows) == 2
    for row in rows:
        assert list(row) == RECORD_COLUMNS
        assert row["source"] == "entsoe"
        assert row["day"] == DAY
        assert row["fetched_at"] == FETCHED_AT
    assert {row["key"] for row in rows} == {"day_ahead_price/1", "day_ahead_price/2"}


def test_payload_preserved_byte_for_byte():
    text = "<GL_MarketDocument>\n  <TimeSeries>...</TimeSeries>\n</GL_MarketDocument>"
    rows = make_records("entsoe", {DAY: {"load_actual": text}}, FETCHED_AT)

    assert rows[0]["payload"] == text


def test_dict_payload_serialized_to_json():
    payload = {"run": "2026-09-16T00:00", "locations": {"berlin": {"hourly": {}}}}
    rows = make_records("weather", {DAY: {"forecast": payload}}, FETCHED_AT)

    assert json.loads(rows[0]["payload"]) == payload


def test_hash_matches_semantic_hash():
    text = '{"series": [[1, 2.0]]}'
    rows = make_records("smard", {DAY: {"day_ahead_price": text}}, FETCHED_AT)

    assert rows[0]["payload_hash"] == semantic_hash("smard", text)
