"""
╭───────────────────────────────────────────────────────────────────────────╮
│                      DELUKIT_DB · Snowflake Backend                       │
│                   Database  (Schemas + Tables + Stage)                    │
╰───────────────────────────────────────────────────────────────────────────╯

DELUKIT_DB/  [Database]                 ← snowflake database
├── BRONZE/  [Schema]                   ← raw zone
│   └── RAW_STAGE  [Stage]              ← raw ingests
├── SILVER/  [Schema]                   ← conformed zone
│   ├── LOAD  [Table]                   ← cleaned load
│   ├── GENERATION  [Table]             ← cleaned generation
│   └── WEATHER  [Table]                ← cleaned weather
├── GOLD/  [Schema]                     ← curated zone
│   ├── FORECASTING_DATASET  [Table]    ← forecasting dataset
│   └── FORECASTS  [Table]              ← model outputs
└── METADATA/  [Schema]                 ← run metadata
    └── DATASET_MANIFESTS  [Table]      ← dataset manifests

                 BRONZE ──▶ SILVER ──▶ GOLD     + METADATA
"""
