"""Modeled availability rules for the versioned dataset.

Every row in data/versioned carries an assigned ``available_at`` timestamp.
The rules model publication timing for the 05:30 and 11:30 Berlin forecast
runs. They do not record when a specific provider revision was observed.

Moving a rule later admits fewer rows at a gate. It cannot reconstruct a
provider revision that the raw daily file no longer retains. Times use the
Berlin wall clock unless a name says UTC.
"""

from datetime import time as dtime
from datetime import timedelta

# Forecast moments, Berlin wall clock.
GATES = (dtime(5, 30), dtime(11, 30))

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

# ECMWF IFS 00z run publication (UTC). Both gates are insensitive to the
# exact hour: any value in (04:30, 09:30] UTC gives "previous run at 05:30,
# today's run at 11:30" in winter and summer alike.
WEATHER_RUN_PUBLISH_UTC = dtime(7, 0)

# Calendar is known far ahead; the value only needs to predate the data.
CALENDAR_AVAILABLE_AT = "2020-01-01"
