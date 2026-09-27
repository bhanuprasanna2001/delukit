ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
ENTSOE_AREA = "10Y1001A1001A82H"

entsoe_params = {
    "SDAC": {
        "documentType": "A44",
        "in_Domain": ENTSOE_AREA,
        "out_Domain": ENTSOE_AREA,
        "contract_MarketAgreement.type": "A01",
    },
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
