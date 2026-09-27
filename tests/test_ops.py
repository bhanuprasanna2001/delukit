import sqlite3
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd


def test_alerts_dedupe_and_record_recovery(tmp_path, monkeypatch):
    from delukit.ops import alerts

    monkeypatch.setattr(alerts, "ALERT_DB", tmp_path / "alerts.db")
    log = tmp_path / "alerts.log"
    assert alerts.record("gate/2026-01-05/0530", True, "missing", log_path=log)
    assert not alerts.record("gate/2026-01-05/0530", True, "missing", log_path=log)
    assert alerts.record("gate/2026-01-05/0530", False, "available", log_path=log)
    with sqlite3.connect(alerts.ALERT_DB) as cx:
        assert cx.execute("SELECT active FROM events ORDER BY id").fetchall() == [
            (1,),
            (0,),
        ]
    assert len(log.read_text().splitlines()) == 2


def test_score_drift_uses_mature_daily_scores(tmp_path):
    from delukit.ops.monitor import score_drift

    rows = []
    for i in range(17):
        rows.append(
            {
                "day": date(2026, 1, 1 + i).isoformat(),
                "gate": "0530",
                "span": "d10",
                "target": "load_actual_mw",
                "lead_day": 4,
                "rmae": 0.2 if i >= 14 else 0.1,
                "evaluated_at": datetime(
                    2026, 2, 1, tzinfo=ZoneInfo("UTC")
                ).isoformat(),
            }
        )
    path = tmp_path / "scores.parquet"
    pd.DataFrame(rows).to_parquet(path)
    events = score_drift(path)
    assert events == [
        (
            "score-drift/0530/d10/load_actual_mw/d4",
            True,
            "mature rMAE median 0.200 over 3 origins; prior 14 origins 0.100; threshold 1.50x",
        )
    ]
