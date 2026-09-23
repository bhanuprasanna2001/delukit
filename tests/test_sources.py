"""Source parsers: bytes in -> state out. No network.

Why these: every provider has its own empty/invalid envelope; misreading it
as data (or data as empty) silently gaps the clean tables. Comparable-strip
tests pin the 'every re-fetch looks updated' bug.
"""

from datetime import date

import pytest


# --- SMARD ---
def test_smard_parse_envelopes():
    from delukit.sources.smard import _parse

    assert _parse(b"<Categories/>") is False  # no Category at all
    assert _parse(b"<Categories><Category/></Categories>") is None  # no Components
    assert _parse(b"not xml") is False
    empty = b"<Categories><Category><Components></Components></Category></Categories>"
    assert _parse(empty) is None
    full = (
        b"<Categories><Category><Components><Component><Values>"
        b"<Value_detail><Value>1</Value></Value_detail>"
        b"</Values></Component></Components></Category></Categories>"
    )
    assert _parse(full) == full


def test_smard_comparable_ignores_header():
    from delukit.sources.smard import _comparable

    a = b"<Header>ts1</Header><Categories><Category/></Categories>"
    b = b"<Header>ts2</Header><Categories><Category/></Categories>"
    assert _comparable(a) == _comparable(b)


def test_smard_number_and_slug_and_columns():
    from delukit.sources.smard import _columns, _number, _slug

    assert _number("1,234") == 1234.0
    assert _number("-") != _number("-")  # NaN
    assert _slug("Wind Onshore") == "wind_onshore"
    assert _slug("Photo-voltaics") == "photo_voltaics"
    assert _columns("load_actual", []) == "load_actual_mwh"
    assert _columns("day_ahead_prices", []) == "price_day_ahead_eur_mwh"


def test_smard_fetch_day_cache_and_write(tmp_dirs, monkeypatch):
    from delukit.sources import smard

    day = date(2026, 1, 5)
    body = (
        b"<Categories><Category><Components><Component><Values>"
        b"<Value_detail><Value>1</Value></Value_detail>"
        b"</Values></Component></Components></Category></Categories>"
    )

    class FakeResp:
        status_code = 200
        content = body

        def raise_for_status(self):
            pass

    class FakeSession:
        def post(self, *a, **k):
            return FakeResp()

        def close(self):
            pass

    monkeypatch.setattr(smard.time, "sleep", lambda *a: None)
    assert smard.fetch_day("load_actual", day, session=FakeSession()) == "fetched"
    # second call same body -> unchanged (header-strip not needed here, identical)
    assert smard.fetch_day("load_actual", day, session=FakeSession()) == "unchanged"


# --- ENTSO-E ---
def test_entsoe_parse_and_comparable():
    from delukit.sources.entsoe import _comparable, _parse

    assert _parse(b"xxx No matching data found yyy") is None
    assert _parse(b"<root><TimeSeries/></root>") is not None
    assert _parse(b"<root/>") is None
    assert _parse(b"not xml <<<") is False
    a = b"<mRID>abcdef0123456789abcdef0123456789</mRID><createdDateTime>2026</createdDateTime><revisionNumber>1</revisionNumber><TimeSeries><mRID>1</mRID></TimeSeries>"
    b = b"<mRID>ffffffffffffffffffffffffffffffff</mRID><createdDateTime>2027</createdDateTime><revisionNumber>2</revisionNumber><TimeSeries><mRID>1</mRID></TimeSeries>"
    assert _comparable(a) == _comparable(b)
    # TimeSeries index mRIDs are data, kept
    assert b"<mRID>1</mRID>" in _comparable(a)


def test_entsoe_window_is_berlin_day_in_utc():
    from delukit.sources.entsoe import _window

    start, end = _window(date(2026, 1, 5))
    assert start == "202601042300"  # midnight Berlin = 23:00 UTC prev day (winter)
    assert end == "202601052300"


def test_entsoe_series_key():
    from delukit.sources.entsoe import _series_key

    assert _series_key("load_actual", {}) == "load_actual_mw"
    assert _series_key("SDAC", {"seq": "1"}) == "price_sdac_seq1_eur_mwh"
    assert _series_key("EXAA", {}) == "price_exaa_eur_mwh"
    assert (
        _series_key("generation_actual", {"psr": "B01", "in_bz": False})
        == "gen_actual_B01_mw"
    )
    assert (
        _series_key("generation_actual", {"psr": "B10", "in_bz": True})
        == "gen_actual_B10_inBZ_mw"
    )
    assert (
        _series_key("generation_actual", {"psr": "B10", "in_bz": False})
        == "gen_actual_B10_outBZ_mw"
    )
    assert (
        _series_key("generation_wind_solar_forecast", {"psr": "B16"})
        == "solar_forecast_mw"
    )


# --- Weather ---
def test_weather_parse():
    import json

    from delukit.core.config.weather import WEATHER_FIELDS, WEATHER_LOCATIONS
    from delukit.sources.weather import _parse

    assert _parse(None, "land") is None
    assert _parse(b"not json", "land") is False
    n = len(WEATHER_LOCATIONS["land"])
    good = [
        {"hourly": {"time": ["2026-01-05T00:00"], **{f: [1.0] for f in WEATHER_FIELDS}}}
        for _ in range(n)
    ]
    assert _parse(json.dumps(good).encode(), "land") is not None
    assert _parse(json.dumps(good[:1]).encode(), "land") is False  # wrong length
    assert (
        _parse(
            json.dumps(
                {"error": True, "reason": "The requested model run is not available. x"}
            ).encode(),
            "land",
        )
        is None
    )


def test_weather_fetch_day_rechecks_run_and_keeps_revision(tmp_dirs, monkeypatch):
    from delukit.sources import weather

    day = date(2026, 1, 5)
    path = tmp_dirs["raw"] / "2026-01-05" / "weather" / "land" / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old")
    monkeypatch.setattr(weather, "_download", lambda *_args: b"new")
    monkeypatch.setattr(weather, "_parse", lambda body, _group: body)
    assert weather.fetch_day("land", day, session=object()) == "updated"
    assert path.read_bytes() == b"new"
    assert weather.fetch_day("land", day, session=object()) == "unchanged"
    assert len(list((path.parent / "observations").glob("*.json"))) == 2


@pytest.mark.parametrize(
    ("source", "category", "filename"),
    [
        ("entsoe", "load_actual", "data.xml"),
        ("smard", "load_actual", "data.xml"),
        ("weather", "land", "data.json"),
    ],
)
def test_previously_fetched_provider_file_cannot_silently_go_empty(
    tmp_dirs, monkeypatch, source, category, filename
):
    from delukit.sources import entsoe, smard, weather

    module = {"entsoe": entsoe, "smard": smard, "weather": weather}[source]
    day = date(2026, 1, 5)
    path = tmp_dirs["raw"] / day.isoformat() / source / category / filename
    path.parent.mkdir(parents=True)
    path.write_bytes(b"old")
    monkeypatch.setattr(module, "_download", lambda *_args: b"empty")
    monkeypatch.setattr(module, "_parse", lambda *_args: None)
    with pytest.raises(RuntimeError, match="returned no data"):
        module.fetch_day(category, day, session=object())


# --- Calendar ---
def test_calendar_records_validation():
    import pytest

    from delukit.sources.calendar import _parse_records

    good = b'[{"startDate": "2026-01-01", "endDate": "2026-01-01", "nationwide": true, "subdivisions": [{"code": "BY"}], "name": []}]'
    assert len(_parse_records(good, "cache: x", "public")) == 1
    with pytest.raises(ValueError, match="invalid OpenHolidays"):
        _parse_records(b'{"not": "array"}', "response: x", "public")
    with pytest.raises(ValueError, match="invalid OpenHolidays"):
        _parse_records(
            b'[{"startDate": "2026-01-02", "endDate": "2026-01-01", "nationwide": true, "subdivisions": []}]',
            "response: x",
            "public",
        )


def test_calendar_document_bridge_and_nationwide():
    from delukit.sources.calendar import _document

    xmas = [
        {
            "startDate": "2026-12-25",
            "endDate": "2026-12-25",
            "nationwide": True,
            "subdivisions": [],
            "name": [],
        }
    ]
    # Thursday 2026-12-24 is a bridge eve? Friday 2026-12-25 holiday -> Thu is not bridge; Mon 2026-12-28? dow Monday with Tue holiday
    doc = _document("DE", date(2026, 12, 28), [], [])  # Monday, Tue 29th not holiday
    assert doc["day_of_week"] == 0
    assert doc["is_bridge_day"] is False
    tue_hol = [
        {
            "startDate": "2026-12-29",
            "endDate": "2026-12-29",
            "nationwide": True,
            "subdivisions": [],
            "name": [],
        }
    ]
    doc2 = _document("DE", date(2026, 12, 28), tue_hol, [])
    assert doc2["is_bridge_day"] is True
    doc3 = _document("DE", date(2026, 12, 25), xmas, [])
    assert doc3["is_holiday"] is True and doc3["is_working_day"] is False


def test_calendar_fetch_day_writes_and_unchanged(tmp_dirs, monkeypatch):
    from delukit.sources import calendar

    day = date(2026, 1, 5)
    rec = {
        "startDate": "2026-01-01",
        "endDate": "2026-01-01",
        "nationwide": True,
        "subdivisions": [],
        "name": [],
    }
    monkeypatch.setattr(calendar, "_year_records", lambda s, k, iso, y, t: [rec])
    assert calendar.fetch_day("de", day, today=date(2026, 1, 20)) == "fetched"
    assert calendar.fetch_day("de", day, today=date(2026, 1, 20)) == "unchanged"


# --- Energy-Charts ---
def test_energy_charts_parse():
    import json

    import pytest

    from delukit.sources.energy_charts import _parse, fetch_day

    assert _parse(None) is None
    assert _parse(b"nope") is False
    assert _parse(json.dumps({"unix_seconds": [], "price": []}).encode()) is None
    assert (
        _parse(json.dumps({"unix_seconds": [1], "price": [2.0]}).encode()) is not None
    )
    assert (
        _parse(json.dumps({"unix_seconds": [1, 2], "price": [1.0]}).encode()) is False
    )
    with pytest.raises(ValueError, match="unknown Energy-Charts category"):
        fetch_day("nope", date(2026, 1, 5))
