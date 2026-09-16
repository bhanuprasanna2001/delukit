"""
SMARD (Bundesnetzagentur) — German electricity market fundamentals.

Extract:
    Day-ahead price:
        1. SDAC DE-LU (filter 4169)

    Load:
        2. Actual total load (410)
        3. Day-ahead load forecast (411)

    Generation, actual, per type (filter id):
        biomass 4066, wind_onshore 4067, solar 4068, lignite 1223,
        nuclear 1224, hard_coal 4069, gas 4071, pumped_storage 4070,
        hydro 1226, other_renewables 1228, other_conventional 1227,
        wind_offshore 1225

    Generation forecasts, per type (filter id):
        day-ahead: total 122, solar 125, wind_onshore 123,
                   wind_offshore 3791, other 715, pv_wind 5097

Rate limit: no token required; weekly stamps only, 30 req/min (self-imposed).
"""

from delukit.sources.smard.source import SmardSource

__all__ = ["SmardSource"]
