<div align="center">

<img src="public/delu.svg" alt="delu logo" width="120" />

# ⚡ delukit

**Day-ahead & 10-day power forecasts for the DE-LU zone — load, solar, wind, generation, price.**

Rebuilt at **05:30** and **11:30** Berlin time · served as chart, API & export

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?style=flat-square&logo=python)](pyproject.toml)
[![Dagster](https://img.shields.io/badge/orchestrated_with-dagster-1C3D5A?style=flat-square)](src/delukit/dagster_app/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square&logo=fastapi)](delu/backend/)
[![React](https://img.shields.io/badge/UI-React_19-61DAFB?style=flat-square&logo=react)](delu/frontend/)
[![Docker](https://img.shields.io/badge/run-docker_compose-2496ED?style=flat-square&logo=docker)](compose.yaml)

[🚀 Quickstart](#-quickstart-60-seconds) ·
[📊 What you get](#-what-you-get) ·
[🔄 How it flows](#-how-it-flows) ·
[⌨️ CLI](#️-cli) ·
[🔌 API](delu/README.md)

</div>

---

<p align="center">
  <img src="public/delu.png" alt="DE-LU forecast chart with P10/P50/P90 bands and actuals" width="100%" />
  <br />
  <sub>The app at <code>:8000</code> — P10/P50/P90 bands, actuals overlay, run-day stepper.</sub>
</p>

## ✨ Why delukit

- 🔮 **24 XGBoost models** — 6 targets × 2 gates × 2 spans, point *and* probabilistic
- 🕰️ **Point-in-time correct** — every row knows when it became known, so gates never train on the future
- ⚡ **Two fresh forecasts a day** — full chain runs at 05:30 / 11:30 Berlin time
- 📈 **1-day + 10-day horizons** — day-ahead precision meets 10-day planning
- 📦 **One command to run** — `docker compose up --build` gives you app + pipeline
- 🔑 **API with keys & quotas** — anonymous exploration, keyed `/v1` for real use

> Forecasts are model output, **not trading advice**.

## 📊 What you get

| Surface | Where | What |
|---|---|---|
| 📈 Forecast chart | `http://localhost:8000` | P10/P50/P90 bands, actuals, 05:30/11:30 toggle, D+1 / 10-day switch |
| 📥 Self-serve export | `/api/export` | CSV / Parquet / XLSX by range, horizon, timezone — verified login only |
| 🔑 API + dashboard | `/v1/forecast` | Keyed endpoint (60/min, 5000/day), usage bar, in-app Swagger |
| 🛠️ Pipeline UI | `http://localhost:3000` | Dagster asset graph, schedules, checks, retries |

<p align="center">
  <img src="public/dagster.svg" alt="Dagster asset graph from raw sync to forecasts" width="100%" />
  <br />
  <sub>Six assets, four schedules — the 05:30/11:30 gates run the full chain; scoring and retraining follow.</sub>
</p>

## 🚀 Quickstart — 60 seconds

```bash
cp .env.example .env  # add ENTSOE_API_KEY
docker compose up --build
```

App → http://localhost:8000 · Pipeline → http://localhost:3000

That's it. The only required key is `ENTSOE_API_KEY`.

## 🔄 How it flows

```mermaid
flowchart LR
    E[ENTSO-E] --> R[raw]
    S[SMARD] --> R
    W[Open-Meteo] --> R
    H[Holidays] --> R
    R --> C[clean]
    C --> V[versioned\navailable_at]
    V --> G{05:30 / 11:30}
    G --> F[forecasts]
```

Raw provider payloads → quarter-hour clean tables → point-in-time versioned parts → **24 XGBoost models** → parquet + plots in `data/forecasts`. Serving lives in [`delu/`](delu/README.md) — one FastAPI process serves UI *and* API.

## ⌨️ CLI

| Command | Does |
|---|---|
| `delukit` | Sync ENTSO-E, SMARD, weather, calendar into `data/raw` |
| `delukit-clean` | Raw → `data/clean/*.parquet` |
| `delukit-dataset` | Clean → `data/versioned` + gate-replay validation (`--validate-only` to just check) |
| `delukit-forecast` | Fit + predict one gate, e.g. `--gate 1130 --span d1 [--date 2026-09-21]` |
| `delukit-backtest` | Replay a product over history, score per lead day |
| `delukit-tune` | Optuna-tune one product into `data/tuning` |

## 🔌 API taste

```bash
# anonymous, rate-limited per IP
curl 'localhost:8000/api/forecast?span=d1&target=load_actual_mw&type=probabilistic'

# keyed — 60/min, 5000/day
curl -H 'X-API-Key: delu_live_...' \
  'localhost:8000/v1/forecast?span=d10&target=gen_actual_photovoltaics_mwh&type=probabilistic'

# export — verified login, cookies included
curl -b cookies.txt \
  'localhost:8000/api/export?start=2026-09-01&end=2026-09-15&target=load_actual_mw&gate=1130&kind=point&tz=Europe/Berlin&horizon_days=1&format=csv' -o export.csv
```

Full reference in [`delu/README`](delu/README.md).

## 🗂️ Project structure

```
src/delukit/
  main.py clean.py dataset.py forecast.py backtest.py tune.py
  core/         # grain, config, availability, products
  sources/      # entsoe, smard, weather, calendar
  dagster_app/  # assets, schedules, checks, run.py
delu/
  backend/      # FastAPI app
  frontend/     # React app
tests/ delu/tests/
compose.yaml Dockerfile delu/Dockerfile
data/           # gitignored: raw, clean, versioned, forecasts, scores, mlflow
```

## 🛠️ Develop without Docker

Python ≥3.12 with `uv`, Node 22.

```bash
uv sync
uv run delukit && uv run delukit-clean && uv run delukit-dataset
uv run delukit-forecast --gate 1130 --span d1
```

```bash
cd delu && uv sync && uv run uvicorn backend.app:app --port 8000
cd delu/frontend && npm ci && npm run dev
```

Dagster UI:

```bash
mkdir -p data/.dagster && export DAGSTER_HOME=$PWD/data/.dagster
uv run dagster dev -m delukit.dagster_app.definitions -p 3000
```

## ⏰ Operations

| Schedule | Runs |
|---|---|
| 🌅 05:30 + 11:30 daily | Full chain: sync → clean → versioned → both spans |
| 🧮 15:30 daily | Score yesterday's gates against arrived actuals |
| 🏆 Sunday 02:00 | Retrain all products, registry keeps the champion |
| 🎛️ 1st of month 03:00 | Re-tune all products |

The versioned-data check **blocks forecasts on bad data**. Writes are idempotent, partitions retry twice, failures append to `data/ops/alerts.log` and POST `DELUKIT_ALERT_WEBHOOK` when set.

## ⚙️ Configuration

`.env.example` → `.env`. Only `ENTSOE_API_KEY` is required.

| Variable | Purpose |
|---|---|
| `RESEND_API_KEY` | Verify + contact mail (falls back to SMTP, logs locally if empty) |
| `DELU_PUBLIC_URL` | Host baked into verify links |
| `DELUKIT_ALERT_WEBHOOK` | Slack alert on failed runs |
| `DELU_COOKIE_SECURE` | Set `1` over https |

## 🙏 Data attribution

ENTSO-E Transparency · SMARD · Open-Meteo ECMWF IFS · OpenHolidays.

## 🤝 Contributing

Small PRs with a test. `uv run pre-commit install` once, then `uv run pytest -q` at root and in `delu/`, `npm run lint` in the frontend. Merging needs `all-checks-passed` green. New providers follow the existing `sync` / `fetch_day` / `to_clean` shape.

---

<div align="center">
  <sub>Built by <a href="mailto:bhanu.prasanna2001@gmail.com">Bhanu Prasanna</a> — forecasts that respect what was known when.</sub>
</div>
