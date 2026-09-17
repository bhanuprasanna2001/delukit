from datetime import date

import pytest
import requests

from delukit.sources.data_source import SourceError, TransientSourceError
from delukit.sources.weather import WeatherSource

TZ = "Europe/Berlin"
URL = "https://single-runs-api.open-meteo.com/v1/forecast"
RUN_NOT_AVAILABLE = (
    "The requested model run is not available. Model: ecmwf_ifs, run: 2026-09-16T00:00Z"
)

LOCATIONS = [
    {"name": "berlin", "latitude": 52.52, "longitude": 13.41, "cell_selection": "land"},
    {"name": "hamburg", "latitude": 53.55, "longitude": 9.99, "cell_selection": "land"},
    {
        "name": "north_sea_west",
        "latitude": 54.75,
        "longitude": 6.30,
        "cell_selection": "sea",
    },
]
FIELDS = ["temperature_2m", "wind_speed_100m"]


def item(latitude=52.52):
    return {
        "latitude": latitude,
        "longitude": 13.41,
        "elevation": 38.0,
        "hourly": {
            "time": ["2025-10-01T02:00"],
            "temperature_2m": [12.5],
            "wind_speed_100m": [20.0],
        },
    }


class FakeResponse:
    def __init__(self, status=200, payload=None, reason=None):
        self.status_code = status
        self._payload = payload
        self._reason = reason

    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(f"{self.status_code} boom", response=response)

    def json(self):
        if self._reason is not None:
            return {"error": True, "reason": self._reason}
        if isinstance(self._payload, str):
            raise requests.exceptions.JSONDecodeError(
                "Expecting value", self._payload, 0
            )
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.calls = []
        self.responses = list(responses)

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        response = self.responses.pop(0)
        if isinstance(response, requests.HTTPError):
            raise response
        return response


def source(responses):
    session = FakeSession(responses)
    src = WeatherSource(LOCATIONS, FIELDS, session=session, tz=TZ)
    src.limiter = None  # tests must not wait on the real 10/min limit
    return src, session


DAY = date(2025, 10, 1)


def test_fetch_one_day_groups_by_cell_selection():
    src, session = source(
        [
            FakeResponse(payload=[item(), item(53.55)]),
            FakeResponse(payload=[item(54.75)]),
        ]
    )

    results = src.fetch(DAY, DAY)

    assert list(results) == [DAY]
    payload = results[DAY]["forecast"]
    assert payload["run"] == "2025-10-01T00:00"
    assert payload["model"] == "ecmwf_ifs"
    assert set(payload["locations"]) == {"berlin", "hamburg", "north_sea_west"}
    assert payload["locations"]["north_sea_west"]["latitude"] == 54.75

    assert len(session.calls) == 2
    land_params = session.calls[0][1]
    sea_params = session.calls[1][1]
    assert session.calls[0][0] == session.calls[1][0] == URL
    assert land_params["latitude"] == "52.52,53.55"
    assert land_params["longitude"] == "13.41,9.99"
    assert land_params["cell_selection"] == "land"
    assert sea_params["latitude"] == "54.75"
    assert sea_params["cell_selection"] == "sea"
    for params in (land_params, sea_params):
        assert params["models"] == "ecmwf_ifs"
        assert params["hourly"] == "temperature_2m,wind_speed_100m"
        assert params["forecast_days"] == 16
        assert params["timezone"] == TZ
        assert params["run"] == "2025-10-01T00:00"


def test_missing_run_returns_empty_day():
    src, session = source([FakeResponse(status=400, reason=RUN_NOT_AVAILABLE)])

    results = src.fetch(DAY, DAY)

    assert results == {DAY: {}}
    assert len(session.calls) == 1


def test_missing_run_with_200_error_body_returns_empty_day():
    src, _ = source([FakeResponse(status=200, reason=RUN_NOT_AVAILABLE)])

    results = src.fetch(DAY, DAY)

    assert results == {DAY: {}}


def test_other_bad_request_raises():
    src, _ = source(
        [FakeResponse(status=400, reason="Cannot initialize WeatherVariable")]
    )

    with pytest.raises(SourceError, match="Cannot initialize WeatherVariable"):
        src.fetch(DAY, DAY)


def test_non_json_2xx_returns_empty_day():
    src, _ = source([FakeResponse(status=200, payload="")])

    results = src.fetch(DAY, DAY)

    assert results == {DAY: {}}


def test_non_json_4xx_raises():
    src, _ = source([FakeResponse(status=400, payload="<html>bad</html>")])

    with pytest.raises(SourceError, match="HTTP 400"):
        src.fetch(DAY, DAY)


def test_transient_failure_is_retried(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    session = FakeSession(
        [
            FakeResponse(status=500),
            FakeResponse(status=429),
            FakeResponse(payload=[item()]),
        ]
    )
    src = WeatherSource(LOCATIONS[:1], FIELDS, session=session, tz=TZ)
    src.limiter = None

    results = src.fetch(DAY, DAY)

    assert len(session.calls) == 3
    assert set(results[DAY]["forecast"]["locations"]) == {"berlin"}


def test_transient_failure_exhausts_retries(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, _ = source([FakeResponse(status=500)] * 3)

    with pytest.raises(TransientSourceError, match="after 3 attempts"):
        src.fetch(DAY, DAY)


def test_fetch_multiple_days():
    land = FakeResponse(payload=[item(), item(53.55)])
    sea = FakeResponse(payload=[item(54.75)])
    src, session = source([land, sea, land, sea])
    end = date(2025, 10, 2)

    results = src.fetch(DAY, end)

    assert list(results) == [DAY, end]
    assert len(session.calls) == 4
    assert [call[1]["run"] for call in session.calls] == [
        "2025-10-01T00:00",
        "2025-10-01T00:00",
        "2025-10-02T00:00",
        "2025-10-02T00:00",
    ]


def test_mismatched_item_count_raises():
    src, _ = source([FakeResponse(payload=[item()])])

    with pytest.raises(ValueError, match="zip"):
        src.fetch(DAY, DAY)


RATE_LIMITED = "Minutely API request limit exceeded. Please try again in one minute."


def test_rate_limit_json_is_retried(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, session = source(
        [
            FakeResponse(status=429, reason=RATE_LIMITED),
            FakeResponse(payload=[item(), item(53.55)]),
            FakeResponse(payload=[item(54.75)]),
        ]
    )

    results = src.fetch(DAY, DAY)

    assert len(session.calls) == 3
    assert set(results[DAY]["forecast"]["locations"]) == {
        "berlin",
        "hamburg",
        "north_sea_west",
    }


def test_rate_limit_json_exhausts_retries(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, session = source([FakeResponse(status=429, reason=RATE_LIMITED)] * 3)

    with pytest.raises(TransientSourceError, match="HTTP 429"):
        src.fetch(DAY, DAY)

    assert len(session.calls) == 3


def test_rate_limit_backoff_waits_a_minute(monkeypatch):
    slept = []
    monkeypatch.setattr("delukit.sources.data_source.sleep", slept.append)
    src, _ = source([FakeResponse(status=429, reason=RATE_LIMITED)] * 3)

    with pytest.raises(TransientSourceError):
        src.fetch(DAY, DAY)

    assert slept == [60.0, 60.0]


def test_limiter_is_10_per_minute():
    rate = WeatherSource.limiter.buckets()[0].rates[0]

    assert rate.limit == 10
    assert rate.interval == 60_000
