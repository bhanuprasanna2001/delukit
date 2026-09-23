"""Conservative publication lower bounds for the versioned dataset.

Observed provider fetch time can only raise a row's ``available_at`` beyond
these bounds. The rules alone do not prove when a specific revision was
public. Times are Berlin wall clock unless a name says UTC.
"""

from datetime import time as dtime
from datetime import timedelta

# Forecast moments, Berlin wall clock.
GATES = (dtime(5, 30), dtime(11, 30))

# Actuals are published after the quarter they describe.
ENTSOE_ACTUALS_DELAY = timedelta(minutes=75)  # ~04:15 at 05:30, ~10:15 at 11:30
SMARD_ACTUALS_DELAY = timedelta(hours=3)  # ~02:30 at 05:30, ~08:30 at 11:30

# Day-ahead curves for target day T are published on T-1, Berlin wall clock.
# EXAA and the ENTSO-E load forecast land between the gates: invisible at
# 05:30, visible at 11:30.
EXAA_PUBLISH = dtime(10, 30)
ENTSOE_LOAD_FC_PUBLISH = dtime(10, 30)
SMARD_DAY_AHEAD_PUBLISH = dtime(13, 0)  # after both gates
SDAC_PUBLISH = dtime(13, 30)  # after both gates
TSO_RENEWABLES_PUBLISH = dtime(18, 0)  # wind/solar/total gen forecasts

# Lower bound for the selected 00z model run, not Open-Meteo availability.
WEATHER_RUN_PUBLISH_UTC = dtime(7, 0)

# Calendar is known far ahead; the value only needs to predate the data.
CALENDAR_AVAILABLE_AT = "2020-01-01"
