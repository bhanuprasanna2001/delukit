# delukit

German energy data pipeline: day-ahead prices, load, generation, and weather
forecasts — from raw APIs into versioned bronze storage, clean silver
tables, and a point-in-time gold feature layer planned next.

Sources: SMARD, ENTSO-E, Energy-Charts, Open-Meteo (ECMWF IFS).

## Quickstart

```python
import delukit

delukit.fetch(
    "entsoe", "2025-10-01", "2025-10-02", method="day_ahead_price", area="DE_LU"
)
```

Run the whole pipeline (APIs → bronze → silver), or one stage:

```bash
uv sync
uv run delukit                     # all stages, configs/pipeline.json
uv run delukit bronze              # fetch APIs into bronze stores
uv run delukit silver              # parse bronze into silver tables
uv run delukit sync                # replay local bronze into remotes
```

## Layout

    sources/     API clients, one folder per provider
    layers/      storage per medallion layer: bronze, silver, gold
    transforms/  pure silver-to-gold computation (no I/O)
    pipelines/   one stage module per layer, composed by the CLI
    backends/    SQL mechanics shared by every layer
    core/        config and logging
