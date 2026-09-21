from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TIMEZONE = "Europe/Berlin"

BASE_DIR = Path("data/bronze")

# Days with no local file yet are always fetched. Files younger than this are
# re-fetched every run because providers revise recent data in place.
REFRESH_DAYS = 7

START = date(2025, 10, 1)


def end_date():
    return datetime.now(ZoneInfo("Europe/Berlin")).date() + timedelta(days=1)


# ENTSO-E Transparency API, DE-LU bidding zone. Same queries entsoe-py makes,
# but we keep the raw XML instead of parsed CSVs.
ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
ENTSOE_AREA = "10Y1001A1001A82H"  # DE-LU

entsoe_params = {
    "SDAC": {
        "documentType": "A44",
        "in_Domain": ENTSOE_AREA,
        "out_Domain": ENTSOE_AREA,
        "contract_MarketAgreement.type": "A01",
    },
    # EXAA local auction, published in 15min resolution only.
    "EXAA": {
        "documentType": "A44",
        "in_Domain": ENTSOE_AREA,
        "out_Domain": ENTSOE_AREA,
        "contract_MarketAgreement.type": "A01",
        "classificationSequence_AttributeInstanceComponent.position": 2,
    },
    "load_actual": {
        "documentType": "A65",
        "processType": "A16",
        "outBiddingZone_Domain": ENTSOE_AREA,
        "out_Domain": ENTSOE_AREA,
    },
    "load_forecast": {
        "documentType": "A65",
        "processType": "A01",
        "outBiddingZone_Domain": ENTSOE_AREA,
    },
    "generation_actual": {
        "documentType": "A75",
        "processType": "A16",
        "in_Domain": ENTSOE_AREA,
    },
    "generation_forecast": {
        "documentType": "A71",
        "processType": "A01",
        "in_Domain": ENTSOE_AREA,
    },
    "generation_wind_solar_forecast": {
        "documentType": "A69",
        "processType": "A01",
        "in_Domain": ENTSOE_AREA,
    },
}

# SMARD download manager, DE-LU region, 15min resolution. One XML per category.
SMARD_URL = "https://www.smard.de/nip-download-manager/nip/download/market-data"
SMARD_REGION = "DE-LU"
SMARD_RESOLUTION = "quarterhour"

smard_modules = {
    "day_ahead_prices": (8004169,),
    "load_actual": (5000410,),
    "load_forecast": (6000411,),
    "generation_actual": (
        1001224,
        1004066,
        1004067,
        1004068,
        1001223,
        1004069,
        1004071,
        1004070,
        1001226,
        1001228,
        1001227,
        1001225,
    ),
    "generation_forecast": (
        2000715,
        2003791,
        2000123,
        2000125,
        2000122,
        2005097,
    ),
}
