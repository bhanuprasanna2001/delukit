"""SMARD download manager, DE-LU region, 15min resolution.

One XML per category.
"""

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
