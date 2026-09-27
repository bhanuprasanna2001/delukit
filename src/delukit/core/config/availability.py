from datetime import time as dtime
from datetime import timedelta

GATES = (dtime(5, 30), dtime(11, 30))

ENTSOE_ACTUALS_DELAY = timedelta(minutes=75)
SMARD_ACTUALS_DELAY = timedelta(hours=3)

EXAA_PUBLISH = dtime(10, 30)
ENTSOE_LOAD_FC_PUBLISH = dtime(10, 30)
SMARD_DAY_AHEAD_PUBLISH = dtime(13, 0)
SDAC_PUBLISH = dtime(13, 30)
TSO_RENEWABLES_PUBLISH = dtime(18, 0)

WEATHER_RUN_PUBLISH_UTC = dtime(7, 0)

CALENDAR_AVAILABLE_AT = "2020-01-01"
