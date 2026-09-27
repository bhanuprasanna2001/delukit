import json
import os
import sqlite3
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ALERT_DB = Path("data/ops/alerts.db")
ALERT_LOG = Path("data/ops/alerts.log")


def record(
    condition: str, active: bool, message: str, *, log_path: Path = ALERT_LOG
) -> bool:
    ALERT_DB.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    with sqlite3.connect(ALERT_DB, timeout=30) as cx:
        cx.execute(
            "CREATE TABLE IF NOT EXISTS conditions (key TEXT PRIMARY KEY, active INTEGER NOT NULL)"
        )
        cx.execute(
            "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, key TEXT NOT NULL, "
            "active INTEGER NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL, sent_at TEXT)"
        )
        cx.execute("BEGIN IMMEDIATE")
        previous = cx.execute(
            "SELECT active FROM conditions WHERE key = ?", (condition,)
        ).fetchone()
        if previous is None and not active:
            return False
        if previous is not None and bool(previous[0]) == active:
            return False
        cx.execute(
            "INSERT INTO conditions (key, active) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET active = excluded.active",
            (condition, int(active)),
        )
        cx.execute(
            "INSERT INTO events (key, active, message, created_at) VALUES (?, ?, ?, ?)",
            (condition, int(active), message, now),
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as out:
        out.write(
            json.dumps(
                {
                    "time": now,
                    "condition": condition,
                    "active": active,
                    "message": message,
                }
            )
            + "\n"
        )
    return True


def deliver_pending() -> int:
    webhook = os.getenv("DELUKIT_ALERT_WEBHOOK")
    if not webhook or not ALERT_DB.exists():
        return 0
    delivered = 0
    with sqlite3.connect(ALERT_DB, timeout=30) as cx:
        pending = cx.execute(
            "SELECT id, key, active, message FROM events WHERE sent_at IS NULL ORDER BY id"
        ).fetchall()
        for event_id, condition, active, message in pending:
            status = "ALERT" if active else "RECOVERED"
            payload = json.dumps(
                {"text": f"*delukit {status}* `{condition}`\n{message}"}
            )
            with urllib.request.urlopen(
                urllib.request.Request(
                    webhook,
                    data=payload.encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                ),
                timeout=10,
            ):
                pass
            cx.execute(
                "UPDATE events SET sent_at = ? WHERE id = ?",
                (datetime.now(UTC).isoformat(), event_id),
            )
            cx.commit()
            delivered += 1
    return delivered


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Record and deliver an operational alert"
    )
    parser.add_argument("condition")
    parser.add_argument("state", choices=["alert", "recovered"])
    parser.add_argument("message")
    args = parser.parse_args()
    record(args.condition, args.state == "alert", args.message)
    deliver_pending()
