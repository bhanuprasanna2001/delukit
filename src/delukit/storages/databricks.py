"""
╭───────────────────────────────────────────────────────────────────────────╮
│                       delukit · Databricks Backend                        │
│                  Unity Catalog  (Delta Tables + Volumes)                  │
╰───────────────────────────────────────────────────────────────────────────╯

delukit/  [Catalog]                     ← unity catalog root
├── bronze/  [Schema]                   ← raw zone
│   └── raw_payloads  [Volume]          ← raw ingests
├── silver/  [Schema]                   ← conformed zone
│   ├── load  [Table]                   ← cleaned load
│   ├── generation  [Table]             ← cleaned generation
│   └── weather  [Table]                ← cleaned weather
├── gold/  [Schema]                     ← curated zone
│   ├── forecasting_dataset  [Table]    ← forecasting dataset
│   └── forecasts  [Table]              ← model outputs
└── metadata/  [Schema]                 ← run metadata
    └── dataset_manifests  [Table]      ← dataset manifests

                 bronze ──▶ silver ──▶ gold     + metadata
"""
