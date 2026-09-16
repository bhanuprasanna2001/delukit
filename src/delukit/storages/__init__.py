"""
╭───────────────────────────────────────────────────────────────────────────╮
│                                  delukit                                  │
│                           Storage Abstractions                            │
├─────────────────────────────────────┬─────────────────────────────────────┤
│            ✦ DataStore ✦            │        ✦ ExperimentTracker ✦        │
├───────────┬───────────┬─────────────┼───────────┬───────────┬─────────────┤
│   Local   │    DBX    │  Snowflake  │   Local   │    DBX    │  Snowflake  │
├───────────┼───────────┼─────────────┼───────────┼───────────┼─────────────┤
│  Parquet  │   Delta   │   Tables    │  MLflow   │  MLflow   │ Experiments │
├───────────────────────────────────────────────────────────────────────────┤
│   Local = filesystem   ·   DBX = Databricks   ·   Snowflake = Snowflake   │
╰───────────────────────────────────────────────────────────────────────────╯

◆ DataStore          datasets · medallion (bronze ──▶ silver ──▶ gold)
◆ ExperimentTracker  runs · forecasts · manifests (MLflow / Snowflake)
"""
