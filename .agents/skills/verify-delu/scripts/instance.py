#!/usr/bin/env python3
"""Launch, inspect, and stop an isolated DELU web instance."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock_time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
DELU = ROOT / "delu"
PYTHON = DELU / ".venv/bin/python"
BERLIN = ZoneInfo("Europe/Berlin")
RUN_DAYS = (date(2026, 1, 5), date(2026, 1, 6))
TARGETS = ("load_actual_mw", "price_sdac_seq1_eur_mwh")


def seed(run_dir: Path) -> None:
    forecasts = run_dir / "forecasts"
    clean = run_dir / "clean"
    clean.mkdir()
    actual_index = pd.date_range("2026-01-05", periods=96 * 5, freq="15min", tz=UTC)
    pd.DataFrame(
        {
            "load_actual_mw": [1000.0 + i % 96 for i in range(len(actual_index))],
            "price_sdac_seq1_eur_mwh": [
                50.0 + i % 24 for i in range(len(actual_index))
            ],
        },
        index=actual_index.rename("timestamp_utc"),
    ).to_parquet(clean / "entsoe.parquet")

    for run_day in RUN_DAYS:
        for gate in ("0530", "1130"):
            for span, days in (("d1", 1), ("d10", 10)):
                start = datetime.combine(
                    run_day + timedelta(days=1), clock_time.min, BERLIN
                )
                end = datetime.combine(
                    run_day + timedelta(days=days + 1), clock_time.min, BERLIN
                )
                index = pd.date_range(
                    start.astimezone(UTC),
                    end.astimezone(UTC),
                    freq="15min",
                    inclusive="left",
                    name="timestamp",
                )
                out_dir = forecasts / run_day.isoformat() / f"{gate}_{span}"
                out_dir.mkdir(parents=True)
                for target in TARGETS:
                    base = 50.0 if target.startswith("price_") else 1000.0
                    base += (run_day.day - RUN_DAYS[0].day) * 10
                    base += 20 if gate == "1130" else 0
                    base += 5 if span == "d10" else 0
                    p50 = [base + (i % 96) / 4 for i in range(len(index))]
                    pd.DataFrame(
                        {
                            "quantile_P10": [v - 5.0 for v in p50],
                            "quantile_P50": p50,
                            "quantile_P90": [v + 5.0 for v in p50],
                            target: [float("nan")] * len(index),
                        },
                        index=index,
                    ).to_parquet(out_dir / f"{target}__xgboost.parquet")


def request(url: str):
    with urllib.request.urlopen(url, timeout=2) as response:
        return response.status, response.read().decode()


def owned_process(info: dict) -> bool:
    pid = info["pid"]
    result = subprocess.run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        text=True,
        capture_output=True,
        check=False,
    )
    return (
        result.returncode == 0 and f"n{info['run_dir']}" in result.stdout.splitlines()
    )


def launch() -> None:
    if not PYTHON.exists():
        raise SystemExit(
            "Install backend dependencies first: cd delu && uv sync --frozen"
        )
    if not (DELU / "frontend/node_modules").exists():
        raise SystemExit(
            "Install frontend dependencies first: cd delu/frontend && npm ci"
        )

    subprocess.run(
        ["npm", "run", "build"], cwd=DELU / "frontend", check=True, stdout=sys.stderr
    )
    run_id = uuid.uuid4().hex[:12]
    run_dir = Path(tempfile.mkdtemp(prefix=f"verify-delu-{run_id}-")).resolve()
    evidence_dir = Path(tempfile.gettempdir()) / "delu-verification-evidence" / run_id
    evidence_dir.mkdir(parents=True)
    shutil.copytree(
        DELU / "backend",
        run_dir / "backend",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "static"),
    )
    shutil.copytree(DELU / "frontend/dist", run_dir / "backend/static")
    seed(run_dir)

    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env.update(
        DELU_FORECASTS=str(run_dir / "forecasts"),
        DELU_ACTUALS=str(run_dir / "clean"),
        DELU_DB=str(run_dir / "app.db"),
        DELU_PUBLIC_URL=url,
        DELU_COOKIE_SECURE="0",
        RESEND_API_KEY="",
        SMTP_HOST="",
        SMTP_PASS="",
        CONTACT_TO="",
    )
    log_file = (run_dir / "server.log").open("w")
    process = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "uvicorn",
            "backend.app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=run_dir,
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    log_file.close()
    info = {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "evidence_dir": str(evidence_dir),
        "url": url,
        "pid": process.pid,
    }
    (run_dir / "instance.json").write_text(json.dumps(info, indent=2) + "\n")
    for _ in range(100):
        if process.poll() is not None:
            break
        try:
            if request(url + "/healthz")[0] == 200:
                print(json.dumps(info, indent=2))
                return
        except (OSError, TimeoutError):
            time.sleep(0.2)
    if owned_process(info):
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    raise SystemExit(
        f"DELU did not become ready. See {run_dir / 'server.log'}; then run cleanup {run_dir}"
    )


def load_info(run_dir: Path) -> dict:
    resolved = run_dir.resolve()
    scratch_root = Path(tempfile.gettempdir()).resolve()
    if resolved.parent != scratch_root or not resolved.name.startswith("verify-delu-"):
        raise SystemExit("This is not a verification scratch directory.")
    info = json.loads((resolved / "instance.json").read_text())
    if info["run_dir"] != str(resolved):
        raise SystemExit("The instance record does not match this directory.")
    return info


def doctor(run_dir: Path) -> None:
    info = load_info(run_dir)
    if not owned_process(info):
        raise SystemExit(
            "The recorded process is not running from this verification directory."
        )
    health_status, health = request(info["url"] + "/healthz")
    options_status, options = request(info["url"] + "/api/options")
    page_status, page = request(info["url"] + "/")
    parsed = json.loads(options)
    if (
        health_status != 200
        or json.loads(health) != {"ok": True}
        or options_status != 200
        or parsed["dates"] != [d.isoformat() for d in RUN_DAYS]
        or page_status != 200
        or "DELU" not in page
    ):
        raise SystemExit(
            "The running app or its isolated fixture does not match this instance."
        )
    print(json.dumps({**info, "health": "ok", "dates": parsed["dates"]}, indent=2))


def cleanup(run_dir: Path) -> None:
    info = load_info(run_dir)
    if owned_process(info):
        os.killpg(info["pid"], signal.SIGTERM)
        for _ in range(50):
            if not owned_process(info):
                break
            time.sleep(0.1)
        if owned_process(info):
            os.killpg(info["pid"], signal.SIGKILL)
    shutil.rmtree(info["run_dir"])
    print(
        json.dumps(
            {"stopped_pid": info["pid"], "evidence_dir": info["evidence_dir"]}, indent=2
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("launch", "doctor", "cleanup"))
    parser.add_argument("run_dir", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "launch":
        launch()
    elif args.run_dir is None:
        parser.error("doctor and cleanup require the run_dir printed by launch")
    elif args.action == "doctor":
        doctor(args.run_dir)
    else:
        cleanup(args.run_dir)


if __name__ == "__main__":
    main()
