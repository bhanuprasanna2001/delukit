import json
from datetime import date

import pandas as pd
import pytest
import requests

from delukit.sources.data_source import SourceError, TransientSourceError
from delukit.sources.smard import SmardSource

TZ = "Europe/Berlin"
DAY = date(2025, 10, 1)
WEEK_STAMP = 1759096800000  # Monday 2025-09-29 00:00 Berlin, in ms UTC
NEXT_WEEK_STAMP = WEEK_STAMP + 604800000
BASE = "https://www.smard.de/app/chart_data"


def day_points(day, n=96, start_value=0.0):
    start = pd.Timestamp(day).tz_localize(TZ)
    return [
        [
            (start + pd.Timedelta(minutes=15 * i)).value // 1_000_000,
            start_value + i,
        ]
        for i in range(n)
    ]


def week_json(points):
    return json.dumps({"meta_data": {"version": 1}, "series": points})


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


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} boom", response=response)


def source(responses):
    session = FakeSession()
    session.responses = responses
    src = SmardSource(session=session, tz=TZ)
    src.limiter = None  # tests must not wait on the real 30/min limit
    return src, session


def fetch(src, start, end, **params):
    params.setdefault("area", "DE_LU")
    params.setdefault("resolution", "15min")
    return src.fetch(start, end, **params)


def test_two_days_same_week_one_request():
    src, session = source(
        [
            fake_response(
                200, week_json(day_points(DAY) + day_points(DAY + pd.Timedelta(days=1)))
            )
        ]
    )

    results = fetch(src, DAY, date(2025, 10, 2), method="day_ahead_price")

    assert list(results) == [date(2025, 10, 1), date(2025, 10, 2)]
    assert len(session.calls) == 1
    url, _, _ = session.calls[0]
    assert url == f"{BASE}/4169/DE-LU/4169_DE-LU_quarterhour_{WEEK_STAMP}.json"
    for day in (date(2025, 10, 1), date(2025, 10, 2)):
        series = json.loads(results[day]["day_ahead_price"])["series"]
        assert len(series) == 96
        assert series[0][0] == pd.Timestamp(day).tz_localize(TZ).value // 1_000_000


def test_days_across_weeks_two_requests():
    sunday = date(2025, 10, 5)
    monday = date(2025, 10, 6)
    src, session = source(
        [
            fake_response(200, week_json(day_points(sunday))),
            fake_response(200, week_json(day_points(monday))),
        ]
    )

    results = fetch(src, sunday, monday, method="day_ahead_price")

    assert len(session.calls) == 2
    assert session.calls[0][0].endswith(f"_{WEEK_STAMP}.json")
    assert session.calls[1][0].endswith(f"_{NEXT_WEEK_STAMP}.json")
    assert list(results[sunday]) == ["day_ahead_price"]
    assert list(results[monday]) == ["day_ahead_price"]


def test_404_week_yields_empty_and_continues():
    src, _ = source(
        [
            fake_response(404, "no data"),
            fake_response(200, week_json(day_points(date(2025, 10, 6)))),
        ]
    )

    results = fetch(src, date(2025, 10, 1), date(2025, 10, 6), method="load_actual")

    assert results[date(2025, 10, 1)] == {}
    assert list(results[date(2025, 10, 6)]) == ["load_actual"]


def test_transient_429_retried_then_raises(monkeypatch):
    monkeypatch.setattr("delukit.sources.data_source.sleep", lambda seconds: None)
    src, session = source([http_error(429)] * 3)

    with pytest.raises(TransientSourceError, match="HTTP 429"):
        fetch(src, DAY, DAY, method="load_actual")

    assert len(session.calls) == 3


def test_permanent_400_not_retried():
    src, session = source([http_error(400)])

    with pytest.raises(SourceError, match="HTTP 400") as exc:
        fetch(src, DAY, DAY, method="load_actual")

    assert len(session.calls) == 1
    assert "method=load_actual" in "\n".join(exc.value.__notes__)
    assert "day=2025-10-01" in "\n".join(exc.value.__notes__)


def test_not_json_response_raises():
    src, _ = source([fake_response(200, "<html><body>proxy error</body></html>")])

    with pytest.raises(SourceError, match="not json"):
        fetch(src, DAY, DAY, method="load_actual")


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"method": "bogus"}, "unknown method"),
        ({"method": "load_actual", "area": "XX"}, "unknown area"),
        ({"method": "load_actual", "resolution": "5min"}, "unknown resolution"),
    ],
)
def test_unknown_catalog(kwargs, match):
    src, _ = source([])

    with pytest.raises(SourceError, match=match):
        fetch(src, DAY, DAY, **kwargs)


def test_hour_resolution_24_points():
    points = [
        [
            (pd.Timestamp(DAY).tz_localize(TZ) + pd.Timedelta(hours=i)).value
            // 1_000_000,
            float(i),
        ]
        for i in range(24)
    ]
    src, session = source([fake_response(200, week_json(points))])

    results = fetch(src, DAY, DAY, method="load_forecast", resolution="hour")

    url, _, _ = session.calls[0]
    assert url == f"{BASE}/411/DE-LU/411_DE-LU_hour_{WEEK_STAMP}.json"
    series = json.loads(results[DAY]["load_forecast"])["series"]
    assert len(series) == 24


def test_generation_actual_one_request_per_type():
    src, session = source(
        [
            fake_response(200, week_json(day_points(DAY))),
            fake_response(200, week_json(day_points(DAY))),
        ]
    )

    results = fetch(
        src,
        DAY,
        DAY,
        method="generation_actual",
        generation_types=["solar", "wind_onshore"],
    )

    urls = [call[0] for call in session.calls]
    assert "/4068/DE-LU/4068_DE-LU_quarterhour_" in urls[0]
    assert "/4067/DE-LU/4067_DE-LU_quarterhour_" in urls[1]
    assert set(results[DAY]) == {
        "generation_actual/solar",
        "generation_actual/wind_onshore",
    }


def test_unknown_generation_type():
    src, _ = source([])

    with pytest.raises(SourceError, match="unknown generation type 'fusion'"):
        fetch(src, DAY, DAY, method="generation_actual", generation_types=["fusion"])

    src, _ = source([])

    with pytest.raises(SourceError, match="supported: total, solar"):
        fetch(
            src,
            DAY,
            DAY,
            method="generation_forecast_day_ahead",
            generation_types=["biomass"],
        )


def test_forecast_day_ahead_maps_catalog_filters():
    src, session = source(
        [
            fake_response(200, week_json(day_points(DAY))),
            fake_response(200, week_json(day_points(DAY))),
            fake_response(200, week_json(day_points(DAY))),
        ]
    )

    results = fetch(
        src,
        DAY,
        DAY,
        method="generation_forecast_day_ahead",
        generation_types=["solar", "wind_onshore", "wind_offshore"],
    )

    urls = [call[0] for call in session.calls]
    assert "/125/DE-LU/125_DE-LU_quarterhour_" in urls[0]
    assert "/123/DE-LU/123_DE-LU_quarterhour_" in urls[1]
    assert "/3791/DE-LU/3791_DE-LU_quarterhour_" in urls[2]
    assert set(results[DAY]) == {
        "generation_forecast_day_ahead/solar",
        "generation_forecast_day_ahead/wind_onshore",
        "generation_forecast_day_ahead/wind_offshore",
    }


@pytest.mark.parametrize(
    ("day", "expected_len"),
    [(date(2025, 10, 1), 96), (date(2025, 10, 26), 100)],
)
def test_day_payload_excludes_next_day_points(day, expected_len):
    start = pd.Timestamp(day).tz_localize(TZ)
    if day == date(2025, 10, 26):
        points = [
            [(start + pd.Timedelta(minutes=15 * i)).value // 1_000_000, float(i)]
            for i in range(100)
        ]
    else:
        points = day_points(day) + day_points(
            day + pd.Timedelta(days=1), start_value=1000
        )
    src, _ = source([fake_response(200, week_json(points))])

    results = fetch(src, day, day, method="day_ahead_price")

    series = json.loads(results[day]["day_ahead_price"])["series"]
    assert len(series) == expected_len
    if expected_len == 96:
        assert max(point[1] for point in series) == 95.0
