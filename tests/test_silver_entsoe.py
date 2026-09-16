import pandas as pd
import pytest

from delukit.layers.silver.entsoe import parse_day

TZ = "Europe/Berlin"


def price_xml(
    points, start="2025-09-30T22:00Z", end="2025-10-01T22:00Z", resolution="PT60M"
):
    point_xml = "".join(
        f"<Point><position>{i + 1}</position><price.amount>{value}</price.amount></Point>"
        for i, value in enumerate(points)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>doc</mRID><revisionNumber>1</revisionNumber><type>A44</type>
  <createdDateTime>2025-10-01T08:00:00Z</createdDateTime>
  <TimeSeries>
    <mRID>1</mRID><businessType>A01</businessType>
    <in_Domain.mRID codingScheme="A01">10Y1001A1001A82H</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10Y1001A1001A82H</out_Domain.mRID>
    <currency_Unit.name>EUR</currency_Unit.name>
    <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
    <curveType>A01</curveType>
    <Period>
      <timeInterval><start>{start}</start><end>{end}</end></timeInterval>
      <resolution>{resolution}</resolution>
      {point_xml}
    </Period>
  </TimeSeries>
</Publication_MarketDocument>"""


def load_xml(quantities, start="2025-09-30T22:00Z", end="2025-10-01T22:00Z"):
    point_xml = "".join(
        f"<Point><position>{i + 1}</position><quantity>{value}</quantity></Point>"
        for i, value in enumerate(quantities)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>doc</mRID><revisionNumber>1</revisionNumber><type>A65</type>
  <createdDateTime>2025-10-01T08:00:00Z</createdDateTime>
  <TimeSeries>
    <mRID>1</mRID><businessType>A01</businessType><objectAggregation>A01</objectAggregation>
    <in_Domain.mRID codingScheme="A01">10Y1001A1001A82H</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10Y1001A1001A82H</out_Domain.mRID>
    <quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name>
    <curveType>A01</curveType>
    <Period>
      <timeInterval><start>{start}</start><end>{end}</end></timeInterval>
      <resolution>PT60M</resolution>
      {point_xml}
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


def generation_xml(
    psr_type, quantities, start="2025-09-30T22:00Z", end="2025-10-01T22:00Z"
):
    point_xml = "".join(
        f"<Point><position>{i + 1}</position><quantity>{value}</quantity></Point>"
        for i, value in enumerate(quantities)
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>doc</mRID><revisionNumber>1</revisionNumber><type>A75</type>
  <createdDateTime>2025-10-01T08:00:00Z</createdDateTime>
  <TimeSeries>
    <mRID>1</mRID><businessType>A01</businessType><objectAggregation>A01</objectAggregation>
    <in_Domain.mRID codingScheme="A01">10Y1001A1001A82H</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10Y1001A1001A82H</out_Domain.mRID>
    <MktPSRType><psrType>{psr_type}</psrType></MktPSRType>
    <quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name>
    <curveType>A01</curveType>
    <Period>
      <timeInterval><start>{start}</start><end>{end}</end></timeInterval>
      <resolution>PT60M</resolution>
      {point_xml}
    </Period>
  </TimeSeries>
</GL_MarketDocument>"""


def wind_solar_xml(psr_quantities):
    timeseries = ""
    for i, (psr_type, quantities) in enumerate(psr_quantities.items()):
        point_xml = "".join(
            f"<Point><position>{j + 1}</position><quantity>{value}</quantity></Point>"
            for j, value in enumerate(quantities)
        )
        timeseries += f"""
  <TimeSeries>
    <mRID>{i}</mRID><businessType>A01</businessType><objectAggregation>A01</objectAggregation>
    <in_Domain.mRID codingScheme="A01">10Y1001A1001A82H</in_Domain.mRID>
    <out_Domain.mRID codingScheme="A01">10Y1001A1001A82H</out_Domain.mRID>
    <MktPSRType><psrType>{psr_type}</psrType></MktPSRType>
    <quantity_Measure_Unit.name>MAW</quantity_Measure_Unit.name>
    <curveType>A01</curveType>
    <Period>
      <timeInterval><start>2025-09-30T22:00Z</start><end>2025-10-01T22:00Z</end></timeInterval>
      <resolution>PT60M</resolution>
      {point_xml}
    </Period>
  </TimeSeries>"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<GL_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:3">
  <mRID>doc</mRID><revisionNumber>1</revisionNumber><type>A69</type>
  <createdDateTime>2025-10-01T08:00:00Z</createdDateTime>
  {timeseries}
</GL_MarketDocument>"""


def test_day_ahead_60min():
    raws = {"day_ahead_price/1": price_xml([50.1, 51.2, 49.9])}

    frame = parse_day(raws, "day_ahead_price", sequences=(1,), tz=TZ)

    assert list(frame.columns) == ["timestamp", "price_eur_per_mwh", "sequence"]
    assert frame["price_eur_per_mwh"].tolist() == [50.1, 51.2, 49.9]
    assert frame["sequence"].tolist() == [1, 1, 1]
    assert frame["timestamp"].dt.tz.key == TZ


def test_day_ahead_prefers_15min():
    raws = {"day_ahead_price/1": price_xml([10.0, 11.0], resolution="PT15M")}

    frame = parse_day(raws, "day_ahead_price", sequences=(1,), tz=TZ)

    assert len(frame) == 2
    assert frame["timestamp"].diff().iloc[1] == pd.Timedelta("15min")


def test_day_ahead_both_sequences():
    raws = {
        "day_ahead_price/1": price_xml([1.0, 2.0]),
        "day_ahead_price/2": price_xml([3.0, 4.0]),
    }

    frame = parse_day(raws, "day_ahead_price", sequences=(1, 2), tz=TZ)

    assert frame["sequence"].tolist() == [1, 1, 2, 2]
    assert frame["price_eur_per_mwh"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_day_ahead_missing_sequence():
    raws = {"day_ahead_price/2": price_xml([3.0])}

    frame = parse_day(raws, "day_ahead_price", sequences=(1, 2), tz=TZ)

    assert frame["sequence"].tolist() == [2]


def test_day_ahead_no_docs_is_empty():
    assert parse_day({}, "day_ahead_price", sequences=(1, 2), tz=TZ).empty


def test_dst_day_has_23_rows():
    points = list(range(1, 24))
    raws = {
        "day_ahead_price/1": price_xml(
            points, start="2025-03-29T23:00Z", end="2025-03-30T22:00Z"
        )
    }

    frame = parse_day(raws, "day_ahead_price", sequences=(1,), tz=TZ)

    assert len(frame) == 23
    assert frame["timestamp"].iloc[0] == pd.Timestamp("2025-03-30 00:00", tz=TZ)
    assert frame["timestamp"].iloc[-1] == pd.Timestamp("2025-03-30 23:00", tz=TZ)
    assert "02" not in frame["timestamp"].dt.strftime("%H").tolist()


def test_load_actual():
    raws = {"load_actual": load_xml([12345, 12400])}

    frame = parse_day(raws, "load_actual", tz=TZ)

    assert list(frame.columns) == ["timestamp", "load_mw"]
    assert frame["load_mw"].tolist() == [12345.0, 12400.0]


def test_load_forecast():
    raws = {"load_forecast": load_xml([13000, 13100])}

    frame = parse_day(raws, "load_forecast", tz=TZ)

    assert list(frame.columns) == ["timestamp", "load_mw"]
    assert frame["load_mw"].tolist() == [13000.0, 13100.0]


def test_generation_actual():
    raws = {
        "generation_actual/B16": generation_xml("B16", [1, 2]),
        "generation_actual/B18": generation_xml("B18", [3, 4]),
        "generation_actual/B19": generation_xml("B19", [5, 6]),
    }

    frame = parse_day(raws, "generation_actual", psr_types=["B16", "B18", "B19"], tz=TZ)

    assert list(frame.columns) == ["timestamp", "generation_mw", "psr_type"]
    assert frame["psr_type"].tolist() == ["B16", "B16", "B18", "B18", "B19", "B19"]
    assert frame["generation_mw"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]


def test_generation_forecast_filters_psr():
    raws = {
        "generation_forecast": wind_solar_xml(
            {"B18": [100, 110], "B19": [200, 210], "B16": [300, 310]}
        )
    }

    frame = parse_day(raws, "generation_forecast", psr_types=["B16", "B19"], tz=TZ)

    assert sorted(frame["psr_type"].unique()) == ["B16", "B19"]
    assert list(frame.columns) == ["timestamp", "generation_mw", "psr_type"]
    assert len(frame) == 4


def test_unknown_method():
    with pytest.raises(ValueError, match="unknown entsoe method"):
        parse_day({}, "bogus")


def test_malformed_xml_raises_clean_error():
    truncated = (
        "<GL_MarketDocument><TimeSeries><mRID>1</mRID><businessType>A01</businessType>"
        "<Period><timeInterval><start>2025-09-30T22:00Z</start></timeInterval>"
    )

    with pytest.raises(ValueError, match="unparseable load_actual"):
        parse_day({"load_actual": truncated}, "load_actual", tz=TZ)
