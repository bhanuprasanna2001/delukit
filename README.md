# delukit

German energy data pipeline: day-ahead prices, load, generation, and weather
forecasts — from raw APIs into versioned bronze storage, with clean silver
parsers already built and a point-in-time feature layer planned next.

Sources: SMARD, ENTSO-E, Energy-Charts, Open-Meteo (ECMWF IFS).

## Quickstart

```python
import delukit

delukit.fetch(
    "entsoe", "2025-10-01", "2025-10-02", method="day_ahead_price", area="DE_LU"
)
```

Raw ingest (APIs → bronze):

```bash
uv sync
uv run delukit configs/data.json
```
