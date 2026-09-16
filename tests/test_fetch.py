from datetime import UTC, date, datetime, timedelta

import pytest

import delukit
from delukit.sources.data_source import DataSource


class FakeSource:
    def __init__(self):
        self.seen = None

    def fetch(self, start, end, **params):
        self.seen = (start, end, params)
        day = start
        out = {}
        while day <= end:
            out[day] = dict(params)
            day += timedelta(days=1)
        return out


def test_fetch_coerces_iso_and_passes_through(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr("delukit.sources.build.build_source", lambda n, c, t: fake)

    out = delukit.fetch(
        "entsoe", "2025-10-01", "2025-10-02", method="load_actual", area="DE_LU"
    )

    assert fake.seen == (
        date(2025, 10, 1),
        date(2025, 10, 2),
        {"method": "load_actual", "area": "DE_LU"},
    )
    assert out == {
        date(2025, 10, 1): {"method": "load_actual", "area": "DE_LU"},
        date(2025, 10, 2): {"method": "load_actual", "area": "DE_LU"},
    }


def test_fetch_weather_strips_constructor_params(monkeypatch):
    fake = FakeSource()
    captured = {}

    def spy(name, config, tz):
        captured.update(config)
        return fake

    monkeypatch.setattr("delukit.sources.build.build_source", spy)

    out = delukit.fetch(
        "weather",
        date(2025, 10, 1),
        date(2025, 10, 1),
        locations=[],
        fields=["temperature_2m"],
    )

    assert captured == {"locations": [], "fields": ["temperature_2m"]}
    assert fake.seen == (date(2025, 10, 1), date(2025, 10, 1), {})
    assert out == {date(2025, 10, 1): {}}


def test_fetch_rejects_reversed_range(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr("delukit.sources.build.build_source", lambda n, c, t: fake)

    with pytest.raises(ValueError, match="start .* is after end"):
        delukit.fetch("entsoe", "2025-10-02", "2025-10-01", method="load_actual")


def test_fetch_weather_requires_locations_and_fields():
    with pytest.raises(ValueError, match="locations.*fields|missing"):
        delukit.fetch("weather", "2025-10-01", "2025-10-02")
    with pytest.raises(ValueError, match="missing"):
        delukit.fetch("weather", "2025-10-01", "2025-10-02", locations=[])


def test_fetch_weather_rejects_non_forecast_method(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr("delukit.sources.build.build_source", lambda n, c, t: fake)

    with pytest.raises(ValueError, match="forecast"):
        delukit.fetch(
            "weather",
            "2025-10-01",
            "2025-10-01",
            method="day_ahead_price",
            locations=[],
            fields=["temperature_2m"],
        )


def test_fetch_weather_accepts_explicit_forecast_method(monkeypatch):
    fake = FakeSource()
    captured = {}

    def spy(name, config, tz):
        captured.update(config)
        return fake

    monkeypatch.setattr("delukit.sources.build.build_source", spy)

    delukit.fetch(
        "weather",
        "2025-10-01",
        "2025-10-01",
        method="forecast",
        locations=[],
        fields=["temperature_2m"],
    )

    assert captured == {"locations": [], "fields": ["temperature_2m"]}
    assert fake.seen == (date(2025, 10, 1), date(2025, 10, 1), {})


def test_fetch_coerces_datetime_to_date(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr("delukit.sources.build.build_source", lambda n, c, t: fake)

    out = delukit.fetch(
        "entsoe",
        datetime(2025, 10, 1, 15, 30, tzinfo=UTC),
        datetime(2025, 10, 2, 9, 0, tzinfo=UTC),
        method="load_actual",
    )

    assert fake.seen[0] == date(2025, 10, 1)
    assert fake.seen[1] == date(2025, 10, 2)
    assert set(out) == {date(2025, 10, 1), date(2025, 10, 2)}
    assert all(type(day) is date for day in out)


def test_fetch_rejects_bad_day_type(monkeypatch):
    fake = FakeSource()
    monkeypatch.setattr("delukit.sources.build.build_source", lambda n, c, t: fake)

    with pytest.raises(TypeError, match="date or ISO"):
        delukit.fetch("entsoe", None, "2025-10-02", method="load_actual")
    with pytest.raises(TypeError, match="date or ISO"):
        delukit.fetch("entsoe", "2025-10-01", 20251002, method="load_actual")


def test_data_source_rejects_reversed_range():
    class DaySource(DataSource):
        def _fetch_day(self, day, **params):
            raise AssertionError("must not be called")

    with pytest.raises(ValueError, match="start .* is after end"):
        DaySource().fetch(date(2025, 10, 2), date(2025, 10, 1))
