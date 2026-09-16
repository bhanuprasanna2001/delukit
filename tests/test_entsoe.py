from datetime import date

import pandas as pd
import pytest
import requests
from entsoe import Area
from entsoe.exceptions import NoMatchingDataError

from delukit.sources.data_source import SourceError, TransientSourceError
from delukit.sources.entsoe import EntsoeSource

TZ = "Europe/Berlin"
DUMMY_XML = "<GL_MarketDocument><TimeSeries/></GL_MarketDocument>"


class FakeClient:
    def __init__(self):
        self.calls = []
        self.responses = []

    def _respond(self, name, args, kwargs):
        self.calls.append((name, args, kwargs))
        if not self.responses:
            raise AssertionError(f"no scripted response for {name}")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def query_day_ahead_prices(self, *args, **kwargs):
        return self._respond("query_day_ahead_prices", args, kwargs)

    def query_load(self, *args, **kwargs):
        return self._respond("query_load", args, kwargs)

    def query_load_forecast(self, *args, **kwargs):
        return self._respond("query_load_forecast", args, kwargs)

    def query_generation(self, *args, **kwargs):
        return self._respond("query_generation", args, kwargs)

    def query_wind_and_solar_forecast(self, *args, **kwargs):
        return self._respond("query_wind_and_solar_forecast", args, kwargs)


def http_error(status, headers=None):
    response = requests.Response()
    response.status_code = status
    if headers:
        response.headers.update(headers)
    return requests.HTTPError(f"{status} boom", response=response)


def source(responses):
    client = FakeClient()
    client.responses = responses
    return EntsoeSource(client=client, tz=TZ), client


DAY = date(2025, 10, 1)
DAY_START = pd.Timestamp("2025-10-01 00:00", tz=TZ)
DAY_END = pd.Timestamp("2025-10-02 00:00", tz=TZ)


def test_fetch_one_call_per_day():
    src, client = source([DUMMY_XML] * 3)

    results = src.fetch(
        DAY, date(2025, 10, 3), method="day_ahead_price", area="DE_LU", sequences=(1,)
    )

    assert list(results) == [date(2025, 10, 1), date(2025, 10, 2), date(2025, 10, 3)]
    assert len(client.calls) == 3
    for i, (_, args, kwargs) in enumerate(client.calls):
        assert args[0] == Area.DE_LU
        assert args[1] == DAY_START + pd.Timedelta(days=i)
        assert args[2] == DAY_END + pd.Timedelta(days=i)
        assert kwargs["sequence"] == 1
    assert all(raws == {"day_ahead_price/1": DUMMY_XML} for raws in results.values())


def test_sequences_split():
    src, client = source([DUMMY_XML, DUMMY_XML])

    raws = src.fetch(
        DAY, DAY, method="day_ahead_price", area="DE_LU", sequences=(1, 2)
    )[DAY]

    assert [kwargs["sequence"] for _, _, kwargs in client.calls] == [1, 2]
    assert set(raws) == {"day_ahead_price/1", "day_ahead_price/2"}


def test_missing_sequence_is_skipped():
    src, _ = source([DUMMY_XML, NoMatchingDataError()])

    raws = src.fetch(
        DAY, DAY, method="day_ahead_price", area="DE_LU", sequences=(1, 2)
    )[DAY]

    assert set(raws) == {"day_ahead_price/1"}


def test_no_matching_data_yields_empty_and_continues():
    src, _ = source([NoMatchingDataError(), DUMMY_XML])

    results = src.fetch(DAY, date(2025, 10, 2), method="load_actual", area="DE_LU")

    assert results[DAY] == {}
    assert results[date(2025, 10, 2)] == {"load_actual": DUMMY_XML}


def test_dst_day_window():
    src, client = source([DUMMY_XML])

    src.fetch(date(2025, 3, 30), date(2025, 3, 30), method="load_actual", area="DE_LU")

    _, args, _ = client.calls[0]
    assert args[1] == pd.Timestamp("2025-03-30 00:00", tz=TZ)
    assert args[2] == pd.Timestamp("2025-03-31 00:00", tz=TZ)


def test_generation_actual_one_doc_per_psr():
    src, client = source([DUMMY_XML] * 3)

    raws = src.fetch(
        DAY,
        DAY,
        method="generation_actual",
        area="DE_LU",
        psr_types=["B16", "B18", "B19"],
    )[DAY]

    assert len(client.calls) == 3
    assert [kwargs["psr_type"] for _, _, kwargs in client.calls] == [
        "B16",
        "B18",
        "B19",
    ]
    assert set(raws) == {
        "generation_actual/B16",
        "generation_actual/B18",
        "generation_actual/B19",
    }


def test_generation_actual_skips_missing_psr():
    src, _ = source([DUMMY_XML, NoMatchingDataError(), DUMMY_XML])

    raws = src.fetch(
        DAY,
        DAY,
        method="generation_actual",
        area="DE_LU",
        psr_types=["B16", "B18", "B19"],
    )[DAY]

    assert set(raws) == {"generation_actual/B16", "generation_actual/B19"}


def test_generation_forecast_one_call():
    src, client = source([DUMMY_XML])

    raws = src.fetch(
        DAY, DAY, method="generation_forecast", area="DE_LU", psr_types=["B16", "B19"]
    )[DAY]

    assert len(client.calls) == 1
    assert "psr_type" not in client.calls[0][2]
    assert raws == {"generation_forecast": DUMMY_XML}


def test_transient_599_retried_then_raises(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, client = source([http_error(599)] * 3)

    with pytest.raises(TransientSourceError, match="HTTP 599"):
        src.fetch(DAY, DAY, method="load_actual", area="DE_LU")

    assert len(client.calls) == 3


def test_transient_honors_retry_after(monkeypatch):
    slept = []
    monkeypatch.setattr("delukit.sources.data_source.sleep", slept.append)
    src, _ = source([http_error(503, headers={"Retry-After": "42"})] * 3)

    with pytest.raises(TransientSourceError):
        src.fetch(DAY, DAY, method="load_actual", area="DE_LU")

    assert slept == [42.0, 42.0]


def test_permanent_400_not_retried():
    src, client = source([http_error(400)])

    with pytest.raises(SourceError, match="HTTP 400") as exc:
        src.fetch(DAY, DAY, method="load_actual", area="DE_LU")

    assert len(client.calls) == 1
    assert "method=load_actual" in "\n".join(exc.value.__notes__)
    assert "day=2025-10-01" in "\n".join(exc.value.__notes__)


def test_401_hints_api_key():
    src, _ = source([http_error(401)])

    with pytest.raises(SourceError, match="ENTSOE_API_KEY"):
        src.fetch(DAY, DAY, method="load_actual", area="DE_LU")


def test_html_response_raises():
    src, _ = source(["<html><body>proxy error</body></html>"])

    with pytest.raises(SourceError, match="TimeSeries"):
        src.fetch(DAY, DAY, method="load_actual", area="DE_LU")


def test_unknown_method():
    src, _ = source([])

    with pytest.raises(SourceError, match="unknown method"):
        src.fetch(DAY, DAY, method="bogus", area="DE_LU")


def test_unknown_area():
    src, _ = source([])

    with pytest.raises(SourceError, match="unknown area"):
        src.fetch(DAY, DAY, method="load_actual", area="XX")


def test_limiter_is_400_per_minute():
    rate = EntsoeSource.limiter.buckets()[0].rates[0]

    assert rate.limit == 400
    assert rate.interval == 60_000
