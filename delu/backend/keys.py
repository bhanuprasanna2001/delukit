import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from backend import db

KEY_PREFIX = "delu_live_"
MIN_LIMIT = 60
DAY_LIMIT = 5000


def _now() -> datetime:
    return datetime.now(UTC)


def _sha(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _prefix_of(raw: str) -> str:
    return raw[: len(KEY_PREFIX) + 8]


def issue(user_id: int) -> tuple[str, str]:
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    now = _now()
    with db.connect() as cx:
        old = cx.execute(
            "SELECT id FROM api_keys WHERE user_id = ?", (user_id,)
        ).fetchone()
        old_id = old["id"] if old else None
        cx.execute("DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        cur = cx.execute(
            "INSERT INTO api_keys (user_id, prefix, key_hash, created) "
            "VALUES (?, ?, ?, ?)",
            (user_id, _prefix_of(raw), _sha(raw), now.isoformat()),
        )
        if old_id is not None:
            # Quota is per user per day, not per key: carry today's usage
            # over so a refresh can never reset or double the allowance.
            day = now.date().isoformat()
            minute = int(now.timestamp()) // 60
            cx.execute(
                "UPDATE usage_day SET key_id = ? WHERE key_id = ? AND day = ?",
                (cur.lastrowid, old_id, day),
            )
            cx.execute(
                "UPDATE usage_min SET key_id = ? WHERE key_id = ? AND minute = ?",
                (cur.lastrowid, old_id, minute),
            )
            cx.execute("DELETE FROM usage_min WHERE key_id = ?", (old_id,))
    return _prefix_of(raw), raw


def lookup(raw: str):
    if not raw.startswith(KEY_PREFIX):
        return None
    with db.connect() as cx:
        row = cx.execute(
            "SELECT id, user_id, key_hash FROM api_keys WHERE prefix = ?",
            (_prefix_of(raw),),
        ).fetchone()
        if row is None or row["key_hash"] != _sha(raw):
            return None
        return {"id": row["id"], "user_id": row["user_id"]}


def touch(key_id: int) -> None:
    with db.connect() as cx:
        cx.execute(
            "UPDATE api_keys SET last_used = ? WHERE id = ?",
            (_now().isoformat(), key_id),
        )


def describe(user_id: int):
    with db.connect() as cx:
        row = cx.execute(
            "SELECT prefix, created, last_used FROM api_keys WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        day = _now().date().isoformat()
        used = cx.execute(
            "SELECT count FROM usage_day WHERE key_id = "
            "(SELECT id FROM api_keys WHERE user_id = ?) AND day = ?",
            (user_id, day),
        ).fetchone()
        return {
            "prefix": row["prefix"],
            "created": row["created"],
            "last_used": row["last_used"],
            "used_today": used["count"] if used else 0,
            "daily_limit": DAY_LIMIT,
        }


def check_and_hit(key_id: int) -> tuple[bool, int]:
    now = _now()
    minute = int(now.timestamp()) // 60
    day = now.date().isoformat()
    with db.connect() as cx:
        m = cx.execute(
            "SELECT count FROM usage_min WHERE key_id = ? AND minute = ?",
            (key_id, minute),
        ).fetchone()
        d = cx.execute(
            "SELECT count FROM usage_day WHERE key_id = ? AND day = ?",
            (key_id, day),
        ).fetchone()
        if (m["count"] if m else 0) >= MIN_LIMIT:
            return False, 60 - now.second
        if (d["count"] if d else 0) >= DAY_LIMIT:
            midnight = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
            return False, int((midnight - now).total_seconds())
        cx.execute(
            "INSERT INTO usage_min (key_id, minute, count) VALUES (?, ?, 1) "
            "ON CONFLICT (key_id, minute) DO UPDATE SET count = count + 1",
            (key_id, minute),
        )
        cx.execute(
            "INSERT INTO usage_day (key_id, day, count) VALUES (?, ?, 1) "
            "ON CONFLICT (key_id, day) DO UPDATE SET count = count + 1",
            (key_id, day),
        )
        cx.execute("DELETE FROM usage_min WHERE minute < ?", (minute - 120,))
    return True, 0
