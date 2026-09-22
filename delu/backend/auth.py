import hashlib
import re
import secrets
import time
from datetime import UTC, datetime, timedelta

from backend import db

SESSION_DAYS = 7
VERIFY_HOURS = 24
SESSION_COOKIE = "delu_session"
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

FAIL_LIMIT = 10
LOCK_SECONDS = 900
_fails: dict[str, tuple[int, float]] = {}


def check_throttle(key: str) -> None:
    """Raise if this identity has failed too many times recently."""
    entry = _fails.get(key)
    if entry and entry[0] >= FAIL_LIMIT and time.monotonic() < entry[1] + LOCK_SECONDS:
        wait = int(LOCK_SECONDS - (time.monotonic() - entry[1]))
        raise ValueError(f"Too many attempts. Try again in {wait // 60 + 1} minutes.")


def note_fail(key: str) -> None:
    count, started = _fails.get(key, (0, time.monotonic()))
    _fails[key] = (count + 1, started if count else time.monotonic())


def note_ok(key: str) -> None:
    _fails.pop(key, None)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)


def signup(email: str, password: str) -> int:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise ValueError("Enter a valid email address.")
    if len(password) < 8:
        raise ValueError("Use a password of at least 8 characters.")
    salt = secrets.token_bytes(16)
    with db.connect() as cx:
        try:
            cur = cx.execute(
                "INSERT INTO users (email, pw_hash, salt, created) VALUES (?, ?, ?, ?)",
                (email, hash_password(password, salt), salt, _iso(_now())),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise ValueError("An account with this email already exists.")
            raise
        return cur.lastrowid


def issue_verify_token(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with db.connect() as cx:
        cx.execute("DELETE FROM email_tokens WHERE user_id = ?", (user_id,))
        cx.execute(
            "INSERT INTO email_tokens (token_hash, user_id, expires) VALUES (?, ?, ?)",
            (_sha(token), user_id, _iso(_now() + timedelta(hours=VERIFY_HOURS))),
        )
    return token


def consume_verify_token(token: str) -> int | None:
    with db.connect() as cx:
        row = cx.execute(
            "SELECT user_id, expires FROM email_tokens WHERE token_hash = ?",
            (_sha(token),),
        ).fetchone()
        if row is None:
            return None
        if datetime.fromisoformat(row["expires"]) < _now():
            cx.execute(
                "DELETE FROM email_tokens WHERE token_hash = ?", (_sha(token),)
            )
            return None
        cx.execute("UPDATE users SET verified = 1 WHERE id = ?", (row["user_id"],))
        cx.execute("DELETE FROM email_tokens WHERE token_hash = ?", (_sha(token),))
        return row["user_id"]


def login(email: str, password: str) -> str | None:
    email = email.strip().lower()
    with db.connect() as cx:
        row = cx.execute(
            "SELECT id, pw_hash, salt FROM users WHERE email = ?", (email,)
        ).fetchone()
        if row is None:
            return None
        if hash_password(password, row["salt"]) != row["pw_hash"]:
            return None
        token = secrets.token_urlsafe(32)
        cx.execute(
            "INSERT INTO sessions (token_hash, user_id, expires) VALUES (?, ?, ?)",
            (_sha(token), row["id"], _iso(_now() + timedelta(days=SESSION_DAYS))),
        )
        return token


def logout(token: str) -> None:
    with db.connect() as cx:
        cx.execute("DELETE FROM sessions WHERE token_hash = ?", (_sha(token),))


def session_user(token: str | None):
    if not token:
        return None
    with db.connect() as cx:
        row = cx.execute(
            "SELECT u.id, u.email, u.verified FROM sessions s "
            "JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
            (_sha(token),),
        ).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "email": row["email"], "verified": bool(row["verified"])}
