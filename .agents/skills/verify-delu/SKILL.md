---
name: verify-delu
description: Verify the DELU React web app and FastAPI serving layer in an isolated local instance. Use when checking a browser feature, forecast response, export, account flow, or API behavior after a change.
---

# Verify DELU

DELU's primary surface is the React browser app served by FastAPI. The same process also exposes public and keyed HTTP APIs. This skill starts the built app against synthetic forecast files and a disposable SQLite database. It proves serving and user interaction; it does not prove forecast generation, provider availability, or point-in-time validity of real data.

Read [the feature map](features/README.md) before driving a feature. Keep each run's shell variables or record the JSON printed by launch. Two runs can coexist because each has its own port, files, database, and PID.

## Launch

From the repository root, install missing dependencies only if the helper requests them (`cd delu && uv sync --frozen`; `cd delu/frontend && npm ci`). Then run:

```bash
RUN_INFO=$(mktemp)
delu/.venv/bin/python .agents/skills/verify-delu/scripts/instance.py launch | tee "$RUN_INFO"
RUN_DIR=$(jq -r .run_dir "$RUN_INFO")
URL=$(jq -r .url "$RUN_INFO")
EVIDENCE_DIR=$(jq -r .evidence_dir "$RUN_INFO")
printf 'RUN_INFO=%s\n' "$RUN_INFO"
```

Launch builds the frontend, copies the backend and built UI to `RUN_DIR`, writes producer-shaped forecast Parquet for 5-6 January 2026, and starts one Uvicorn process on an available loopback port. `DELU_FORECASTS`, `DELU_ACTUALS`, and `DELU_DB` point only into that run. Mail transports are disabled; the production local-log fallback records verification links and contact messages in `RUN_DIR/server.log`. Readiness is `GET /healthz` returning `{"ok":true}`. The JSON output records the URL, PID, scratch path, and evidence path. If each tool call opens a new shell, reassign `RUN_INFO` to its printed path and reload the other values with the `jq` lines above. Do not reuse another run's instance.

## Doctor

Run this before driving and whenever the page, data, or request looks wrong:

```bash
delu/.venv/bin/python .agents/skills/verify-delu/scripts/instance.py doctor "$RUN_DIR"
```

Doctor is read-only. It checks that the recorded PID has `RUN_DIR` as its working directory, `/healthz` responds, `/api/options` lists exactly the two seeded run days, and `/` serves the built DELU page. If it fails, inspect `RUN_DIR/server.log`, clean up this run, and launch again.

## Drive

Use the computer-use browser harness for UI actions. On this macOS setup, Dia is available through `cua_repl`: bind with `cua.getApp("Dia")`, open a fresh tab with `app.pressKey("super+t")`, type `URL`, press Return, and inspect `app.getAXState()`. The URL suggestion may require a second Return. Read the fresh accessibility tree after each action. Use named controls from the feature map, such as `Run day`, `05:30`, `10-day`, `Series`, `Point`, and `Probabilistic`. If Dia's AX click leaves a button unchanged, focus it with keyboard navigation and press Return; confirm the new selection in a screenshot and the HTTP response. Do not infer success from a click call alone.

For the forecast chart, open `URL`, capture the initial `11:30` view, activate `05:30`, and capture the changed view. Corroborate the browser action through the public HTTP boundary:

```bash
curl -fsS "$URL/api/forecast?date=2026-01-06&gate=1130&span=d1&target=load_actual_mw&type=probabilistic" > "$EVIDENCE_DIR/forecast-1130.json"
curl -fsS "$URL/api/forecast?date=2026-01-06&gate=0530&span=d1&target=load_actual_mw&type=probabilistic" > "$EVIDENCE_DIR/forecast-0530.json"
jq -e '.meta.gate == "1130" and ([.p50[] | select(. != null)][0]) == 1030 and ([.p50[] | select(. != null)] | length) == 96' "$EVIDENCE_DIR/forecast-1130.json"
jq -e '.meta.gate == "0530" and ([.p50[] | select(. != null)][0]) == 1010 and ([.p50[] | select(. != null)] | length) == 96' "$EVIDENCE_DIR/forecast-0530.json"
```

The browser must show the changed selected run and chart. The response includes one day of realised history before the 96 forecast quarters, so the first P50 array entry is null. The response checks alone do not prove UI wiring. Feature files give the remaining paths and their observable end states.

## Evidence

Keep proof under `EVIDENCE_DIR`, which is outside the repository and separate from scratch state. Capture a screenshot before and after the action, the corresponding accessibility state or a brief action record, response bodies where relevant, and any side effect such as a downloaded file, SQLite row, or local mail log entry. For CUA screenshots, call `app.getScreenshot({emit:false})` and save its bytes with `node:fs/promises.writeFile` to the printed evidence directory. Record which run day, gate, horizon, target, and type were selected. Run `cp "$RUN_INFO" "$EVIDENCE_DIR/instance.json"` for provenance.

Exercise the real user path, not React setters or test-only endpoints. The helper seeds files at the existing producer-to-serving boundary; it does not mock FastAPI or the frontend. For exports, inspect the downloaded rows, dates, and file format, not just the success banner. For contact and verification, confirm the log entry because local mail fallback does not send an email. This fixture has no source-availability timestamps, so it cannot establish that live forecasts are leakage-safe.

## Cleanup

Stop only the recorded process and remove only its scratch directory:

```bash
delu/.venv/bin/python .agents/skills/verify-delu/scripts/instance.py cleanup "$RUN_DIR"
test -d "$EVIDENCE_DIR"
rm "$RUN_INFO"
```

The helper checks PID ownership before signaling and leaves `EVIDENCE_DIR` intact. Run cleanup after failures too. Never kill by process name or delete another run's directory.

## Helpers

`scripts/instance.py` is executable and has three commands: `launch`, `doctor RUN_DIR`, and `cleanup RUN_DIR`. Invoke it with `delu/.venv/bin/python` as shown above so its pandas and Parquet dependencies come from DELU's environment. It builds the UI, seeds isolated data, starts the server, checks ownership/readiness, and stops only its own instance.
