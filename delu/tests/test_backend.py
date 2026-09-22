"""DELU backend: auth/keys quotas, forecast files, HTTP surface.

Why these: account enumeration, quota reset on refresh, and export/forecast
path handling are the real incidents; trivial getters are not tested.
"""

import pandas as pd
import pytest


# --- auth ---
def test_signup_login_verify_lifecycle(tmp_dirs, monkeypatch):
    from backend import auth, keys

    monkeypatch.setattr("backend.mail.send_verify", lambda *a, **k: None)
    uid = auth.signup("User@Example.com", "password123")
    assert auth.login("user@example.com", "wrongpass") is None
    token = auth.login(" user@example.com ", "password123")
    assert token
    user = auth.session_user(token)
    assert user["email"] == "user@example.com" and not user["verified"]
    vtoken = auth.issue_verify_token(uid)
    assert auth.consume_verify_token(vtoken) == uid
    assert auth.consume_verify_token(vtoken) is None  # single use
    assert auth.session_user(token)["verified"]
    assert keys.describe(uid) is None  # no key until one is issued
    _prefix, raw = keys.issue(uid)
    assert raw.startswith("delu_live_") and keys.lookup(raw)["user_id"] == uid


def test_signup_rejects_bad_input_and_duplicates(tmp_dirs):
    from backend import auth

    with pytest.raises(ValueError, match="valid email"):
        auth.signup("bad", "password123")
    with pytest.raises(ValueError, match="at least 8"):
        auth.signup("a@b.co", "short")
    auth.signup("dup@x.co", "password123")
    with pytest.raises(ValueError, match="already exists"):
        auth.signup("dup@x.co", "password123")


def test_throttle_locks_and_clears(tmp_dirs):
    from backend import auth

    key = "k1"
    for _ in range(auth.FAIL_LIMIT):
        auth.note_fail(key)
    with pytest.raises(ValueError, match="Too many attempts"):
        auth.check_throttle(key)
    auth.note_ok(key)
    auth.check_throttle(key)  # ok again


def test_delete_account_cleans_quotas(tmp_dirs):
    from backend import auth, db, keys

    uid = auth.signup("del@x.co", "password123")
    _, raw = keys.issue(uid)
    kid = keys.lookup(raw)["id"]
    assert keys.check_and_hit(kid)[0]
    with pytest.raises(ValueError, match="wrong"):
        auth.delete_account(uid, "badpass")
    auth.delete_account(uid, "password123")
    assert auth.login("del@x.co", "password123") is None
    with db.connect() as cx:
        assert (
            cx.execute("SELECT * FROM usage_day WHERE key_id=?", (kid,)).fetchall()
            == []
        )
        assert (
            cx.execute("SELECT * FROM api_keys WHERE id=?", (kid,)).fetchone() is None
        )


def test_keys_minute_quota_and_refresh_carries_day(tmp_dirs):
    from backend import auth, keys

    uid = auth.signup("q@x.co", "password123")
    _, raw = keys.issue(uid)
    kid = keys.lookup(raw)["id"]
    assert keys.lookup("wrong_prefix_key") is None
    assert keys.lookup("delu_live_" + "x" * 43) is None
    for _ in range(keys.MIN_LIMIT):
        assert keys.check_and_hit(kid)[0]
    ok, retry = keys.check_and_hit(kid)
    assert not ok and retry > 0
    _, _raw2 = keys.issue(uid)  # refresh kills the old key, carries the day quota
    assert keys.lookup(raw) is None
    desc = keys.describe(uid)
    assert (
        desc["used_today"] >= keys.MIN_LIMIT and desc["daily_limit"] == keys.DAY_LIMIT
    )
    # PARKED for atomic commits: minute-carry assertion lands with the fix.


# --- forecasts ---
def _write_forecast(fdir, target, day="2026-01-06", model="xgboost", n=96):
    fdir.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(f"{day} 00:00", periods=n, freq="15min", tz="UTC")
    pd.DataFrame(
        {
            "quantile_P10": [1.0] * n,
            "quantile_P50": [2.0] * n,
            "quantile_P90": [3.0] * n,
            target: [2.0] * n,
        },
        index=idx,
    ).to_parquet(fdir / f"{target}__{model}.parquet")


def test_forecast_options_resolve_newest(tmp_dirs):
    from backend import forecasts as F

    assert F.options()["dates"] == []
    with pytest.raises(Exception, match="No forecasts"):
        F.resolve(None, None, "d1", "load_actual_mw")
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "0530_d1", "load_actual_mw")
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1", "load_actual_mw")
    opts = F.options()
    assert opts["dates"] == ["2026-01-05"] and "load_actual_mw" in opts["targets"]
    assert F.resolve(None, None, "d1", "load_actual_mw") == ("2026-01-05", "1130")
    assert F.resolve("2026-01-05", "0530", "d1", "load_actual_mw") == (
        "2026-01-05",
        "0530",
    )


def test_forecast_load_with_actuals(tmp_dirs, actuals):
    from backend import forecasts as F

    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1", "load_actual_mw")
    out = F.load("2026-01-05", "1130", "d1", "load_actual_mw", "probabilistic")
    assert out["meta"]["model"] == "xgboost" and out["meta"]["rows"] >= 96
    assert len(out["p50"]) == len(out["timestamps"]) == len(out["actual"])
    assert out["p10"] is not None
    point = F.load("2026-01-05", "1130", "d1", "load_actual_mw", "point")
    assert point["p10"] is None and point["p90"] is None


def test_export_frame_validation_and_file(tmp_dirs):
    from backend import forecasts as F

    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1", "load_actual_mw")
    with pytest.raises(ValueError, match="Run is one of"):
        F.export_frame(
            "2026-01-05", "2026-01-05", "load_actual_mw", "9999", "point", "UTC", 1
        )
    with pytest.raises(ValueError, match="Horizon"):
        F.export_frame(
            "2026-01-05", "2026-01-05", "load_actual_mw", "1130", "point", "UTC", 11
        )
    with pytest.raises(ValueError, match="before start"):
        F.export_frame(
            "2026-01-06", "2026-01-05", "load_actual_mw", "1130", "point", "UTC", 1
        )
    df = F.export_frame(
        "2026-01-05", "2026-01-05", "load_actual_mw", "1130", "point", "UTC", 1
    )
    assert list(df.columns)[:4] == [
        "origin_date",
        "origin_time",
        "target_time",
        "horizon_in_hours",
    ]
    assert "p50" in df.columns and "p10" not in df.columns
    name, media, data = F.export_file(
        "2026-01-05", "2026-01-05", "load_actual_mw", "1130", "point", "UTC", 1, "csv"
    )
    assert name.endswith(".csv") and media == "text/csv" and len(data) > 0
    with pytest.raises(ValueError, match="Format"):
        F.export_file(
            "2026-01-05",
            "2026-01-05",
            "load_actual_mw",
            "1130",
            "point",
            "UTC",
            1,
            "xml",
        )


def test_download_files_lists_newest_days(tmp_dirs):
    from backend import forecasts as F

    assert F.download_files(7) == []
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "0530_d1", "load_actual_mw")
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-06" / "0530_d1", "load_actual_mw")
    assert len(F.download_files(1)) == 1
    assert len(F.download_files(7)) == 2


# --- app ---
def _client(tmp_dirs, monkeypatch):
    monkeypatch.setattr("backend.mail.send_verify", lambda *a, **k: None)
    monkeypatch.setattr("backend.mail.send_contact", lambda *a, **k: True)
    from fastapi.testclient import TestClient

    from backend import app as A

    return TestClient(A.app)


def _verified_client(tmp_dirs, monkeypatch):
    c = _client(tmp_dirs, monkeypatch)
    c.post("/auth/signup", json={"email": "u@x.co", "password": "password123"})
    from backend import auth, db

    with db.connect() as cx:
        uid = cx.execute("SELECT id FROM users WHERE email='u@x.co'").fetchone()["id"]
    c.get("/auth/verify", params={"token": auth.issue_verify_token(uid)})
    c.post("/auth/login", json={"email": "u@x.co", "password": "password123"})
    return c


def test_app_health_options_security(tmp_dirs, monkeypatch):
    c = _client(tmp_dirs, monkeypatch)
    r = c.get("/healthz")
    assert r.json() == {"ok": True}
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert c.get("/api/options").status_code == 200
    spec = c.get("/openapi-forecast.json").json()
    assert list(spec["paths"]) == ["/v1/forecast"]


def test_app_forecast_validation_and_v1_auth(tmp_dirs, monkeypatch, actuals):
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1", "load_actual_mw")
    c = _client(tmp_dirs, monkeypatch)
    assert c.get("/api/forecast", params={"type": "bad"}).status_code == 400
    assert c.get("/api/forecast").status_code == 200
    assert c.get("/v1/forecast").status_code == 401
    assert (
        c.get("/v1/forecast", headers={"X-API-Key": "delu_live_nope"}).status_code
        == 401
    )


def test_app_v1_quota_and_export(tmp_dirs, monkeypatch, actuals):
    from backend import db, keys

    c = _verified_client(tmp_dirs, monkeypatch)
    with db.connect() as cx:
        uid = cx.execute("SELECT id FROM users WHERE email='u@x.co'").fetchone()["id"]
    _, raw = keys.issue(uid)
    _write_forecast(tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1", "load_actual_mw")
    r = c.get("/v1/forecast", headers={"X-API-Key": raw})
    assert r.status_code == 200 and r.headers["X-RateLimit-Day"] == str(keys.DAY_LIMIT)
    kid = keys.lookup(raw)["id"]
    for _ in range(keys.MIN_LIMIT):
        keys.check_and_hit(kid)
    assert c.get("/v1/forecast", headers={"X-API-Key": raw}).status_code == 429
    assert (
        c.get(
            "/api/export", params={"start": "2026-01-05", "end": "2026-01-05"}
        ).status_code
        == 200
    )


def test_app_auth_enumeration_and_contact_throttle(tmp_dirs, monkeypatch):
    c = _client(tmp_dirs, monkeypatch)
    c.post("/auth/signup", json={"email": "e@x.co", "password": "password123"})
    bad1 = c.post("/auth/login", json={"email": "e@x.co", "password": "wrong1234"})
    bad2 = c.post("/auth/login", json={"email": "nouser@x.co", "password": "wrong1234"})
    assert bad1.status_code == bad2.status_code == 401
    assert bad1.json() == bad2.json()  # same error, no enumeration
    body = {"name": "Ab", "email": "a@b.co", "topic": "Hi", "message": "hello world!"}
    assert c.post("/api/contact", json=body).status_code == 200
    assert c.post("/api/contact", json={**body, "email": "bad"}).status_code == 400
    for _ in range(4):
        c.post("/api/contact", json=body)
    assert c.post("/api/contact", json=body).status_code == 429


def test_mail_never_raises_without_config(monkeypatch):
    from backend import mail

    monkeypatch.setattr(mail, "RESEND_API_KEY", "")
    monkeypatch.setattr(mail, "SMTP_HOST", "")
    mail.send_verify("a@b.co", "http://x/?verify=t")  # logs, no raise
    assert mail.send_contact("N", "a@b.co", "T", "hello world") is False
