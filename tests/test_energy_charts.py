from datetime import date

import pandas as pd
import pytest
import requests

from delukit.sources.data_source import SourceError, TransientSourceError
from delukit.sources.energy_charts import EnergyChartsSource
from delukit.sources.energy_charts.sdac import PRICE_URL

TZ = "Europe/Berlin"
PRICE_JSON = (
    '{"license_info":"CC BY 4.0","unix_seconds":[1743289200,1743292800],'
    '"price":[46.31,15.89],"unit":"EUR / MWh","deprecated":false}'
)
DAY = date(2025, 10, 1)
DAY_START = pd.Timestamp("2025-10-01 00:00", tz=TZ)


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params, timeout))
        if not self.responses:
            raise AssertionError("no scripted response")
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fake_response(status, text=""):
    response = requests.Response()
    response.status_code = status
    response._content = text.encode()
    return response


def http_error(status, headers=None):
    response = requests.Response()
    response.status_code = status
    if headers:
        response.headers.update(headers)
    return requests.HTTPError(f"{status} boom", response=response)


def source(responses):
    session = FakeSession()
    session.responses = responses
    src = EnergyChartsSource(session=session, tz=TZ)
    src.limiter = None  # tests must not wait on the real 2/min limit
    return src, session


def test_one_call_per_day():
    src, session = source([fake_response(200, PRICE_JSON)] * 2)

    results = src.fetch(
        DAY, date(2025, 10, 2), method="day_ahead_price", bidding_zone="DE-LU"
    )

    assert list(results) == [date(2025, 10, 1), date(2025, 10, 2)]
    assert len(session.calls) == 2
    for i, (url, params, _) in enumerate(session.calls):
        day_start = DAY_START + pd.Timedelta(days=i)
        assert url == PRICE_URL
        assert params["bzn"] == "DE-LU"
        assert params["start"] == day_start.isoformat()
        assert (
            params["end"]
            == (day_start + pd.Timedelta(hours=23, minutes=59)).isoformat()
        )
    assert all(raws == {"day_ahead_price": PRICE_JSON} for raws in results.values())


def test_404_no_content_yields_empty_and_continues():
    src, _ = source(
        [fake_response(404, "no content available"), fake_response(200, PRICE_JSON)]
    )

    results = src.fetch(
        DAY, date(2025, 10, 2), method="day_ahead_price", bidding_zone="DE-LU"
    )

    assert results[DAY] == {}
    assert results[date(2025, 10, 2)] == {"day_ahead_price": PRICE_JSON}


def test_400_not_retried():
    src, session = source([fake_response(400, "bad zone")])

    with pytest.raises(SourceError, match="HTTP 400") as exc:
        src.fetch(DAY, DAY, method="day_ahead_price", bidding_zone="XX")

    assert len(session.calls) == 1
    assert "method=day_ahead_price" in "\n".join(exc.value.__notes__)
    assert "day=2025-10-01" in "\n".join(exc.value.__notes__)


def test_transient_429_retried_then_raises(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, session = source([http_error(429)] * 3)

    with pytest.raises(TransientSourceError, match="HTTP 429"):
        src.fetch(DAY, DAY, method="day_ahead_price", bidding_zone="DE-LU")

    assert len(session.calls) == 3


def test_html_response_raises():
    src, _ = source([fake_response(200, "<html><body>proxy error</body></html>")])

    with pytest.raises(SourceError, match="not json"):
        src.fetch(DAY, DAY, method="day_ahead_price", bidding_zone="DE-LU")


def test_unknown_method():
    src, _ = source([])

    with pytest.raises(SourceError, match="unknown method"):
        src.fetch(DAY, DAY, method="bogus", bidding_zone="DE-LU")


@pytest.mark.parametrize("day", [date(2025, 3, 30), date(2025, 10, 26)])
def test_dst_day_window(day):
    src, session = source([fake_response(200, PRICE_JSON)])

    src.fetch(
        day,
        day,
        method="day_ahead_price",
        bidding_zone="DE-LU",
    )

    _, params, _ = session.calls[0]
    assert (
        params["start"] == pd.Timestamp(f"{day.isoformat()} 00:00", tz=TZ).isoformat()
    )
    assert params["end"] == pd.Timestamp(f"{day.isoformat()} 23:59", tz=TZ).isoformat()
