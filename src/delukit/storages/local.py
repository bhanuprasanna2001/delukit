"""
╭───────────────────────────────────────────────────────────────────────────╮
│                       delukit_store · Local Backend                       │
│                      Filesystem  (Parquet + DuckDB)                       │
╰───────────────────────────────────────────────────────────────────────────╯

delukit_store/                ← local data root
├── bronze/                   ← raw landing zone
│   └── raw files             ← immutable ingests
├── silver/                   ← cleaned & conformed
│   └── *.parquet             ← load · generation · weather
├── gold/                     ← curated marts
│   └── *.parquet             ← forecasting_dataset
├── forecasts/                ← model outputs
│   └── *.parquet             ← forecasts
├── manifests/                ← run metadata
│   └── *.json                ← dataset manifests
└── catalog.duckdb            ← local catalog index

                 bronze ──▶ silver ──▶ gold ──▶ forecasts
"""
