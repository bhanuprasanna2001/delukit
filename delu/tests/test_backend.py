"""DELU backend: auth/keys quotas, forecast files, HTTP surface.

Why these: account enumeration, quota reset on refresh, and export/forecast
path handling are the real incidents; trivial getters are not tested.
"""

import io
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

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
    # Loop until the quota trips: usage buckets are wall-clock minutes,
    # so a fixed count can straddle a boundary on slow runners.
    for _ in range(2 * keys.MIN_LIMIT):
        ok, retry = keys.check_and_hit(kid)
        if not ok:
            break
    assert not ok and retry > 0
    _, _raw2 = keys.issue(uid)  # refresh kills the old key, carries the quotas
    assert keys.lookup(raw) is None
    desc = keys.describe(uid)
    assert (
        desc["used_today"] >= keys.MIN_LIMIT and desc["daily_limit"] == keys.DAY_LIMIT
    )
    # Minute quota carries too: a refresh must never mint fresh allowance.
    # (SQLite reuses the key id here, which used to wipe the carried row.)
    ok2, retry2 = keys.check_and_hit(keys.lookup(_raw2)["id"])
    assert not ok2 and retry2 > 0


# --- forecasts ---
def _write_forecast(fdir, target, day="2026-01-06", model="xgboost", n=96):
    fdir.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range(
        f"{day} 00:00", periods=n, freq="15min", tz="Europe/Berlin"
    ).tz_convert("UTC")
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


def test_export_rejects_missing_origin_and_incomplete_delivery(tmp_dirs):
    from backend import forecasts as F

    path = tmp_dirs["forecasts"] / "2026-01-05" / "1130_d1"
    _write_forecast(path, "load_actual_mw")
    with pytest.raises(F.Missing, match="2026-01-06"):
        F.export_frame(
            "2026-01-05",
            "2026-01-06",
            "load_actual_mw",
            "1130",
            "point",
            "Europe/Berlin",
            1,
        )
    with pytest.raises(F.Missing, match="d10"):
        F.export_frame(
            "2026-01-05",
            "2026-01-05",
            "load_actual_mw",
            "1130",
            "point",
            "Europe/Berlin",
            2,
        )
    file = path / "load_actual_mw__xgboost.parquet"
    frame = pd.read_parquet(file).iloc[1:]
    frame.to_parquet(file)
    with pytest.raises(F.Missing, match="Incomplete 1-day"):
        F.export_frame(
            "2026-01-05",
            "2026-01-05",
            "load_actual_mw",
            "1130",
            "point",
            "Europe/Berlin",
            1,
        )


@pytest.mark.parametrize("gate", ["0530", "1130"])
@pytest.mark.parametrize(
    (
        "origin_day",
        "delivery_day",
        "expected_rows",
        "first_target_time",
        "last_target_time",
    ),
    [
        (
            "2026-01-05",
            "2026-01-06",
            96,
            "2026-01-06T00:00:00+01:00",
            "2026-01-06T23:45:00+01:00",
        ),
        (
            "2026-03-28",
            "2026-03-29",
            92,
            "2026-03-29T00:00:00+01:00",
            "2026-03-29T23:45:00+02:00",
        ),
        (
            "2026-10-24",
            "2026-10-25",
            100,
            "2026-10-25T00:00:00+02:00",
            "2026-10-25T23:45:00+01:00",
        ),
    ],
)
def test_export_delivers_complete_local_day(
    tmp_dirs,
    monkeypatch,
    gate,
    origin_day,
    delivery_day,
    expected_rows,
    first_target_time,
    last_target_time,
):
    berlin = ZoneInfo("Europe/Berlin")
    start = datetime.combine(date.fromisoformat(delivery_day), time.min, berlin)
    end = datetime.combine(
        date.fromisoformat(delivery_day) + timedelta(days=1), time.min, berlin
    )
    index = pd.date_range(start, end, freq="15min", inclusive="left").tz_convert("UTC")
    outdir = tmp_dirs["forecasts"] / origin_day / f"{gate}_d1"
    outdir.mkdir(parents=True)
    pd.DataFrame(
        {
            "quantile_P10": range(len(index)),
            "quantile_P50": range(len(index)),
            "quantile_P90": range(len(index)),
            "load_actual_mw": range(len(index)),
        },
        index=index,
    ).to_parquet(outdir / "load_actual_mw__xgboost.parquet")

    client = _verified_client(tmp_dirs, monkeypatch)
    response = client.get(
        "/api/export",
        params={
            "start": origin_day,
            "end": origin_day,
            "target": "load_actual_mw",
            "gate": gate,
            "kind": "point",
            "tz": "Europe/Berlin",
            "horizon_days": 1,
            "format": "csv",
        },
    )
    assert response.status_code == 200
    exported = pd.read_csv(io.BytesIO(response.content))
    assert len(exported) == expected_rows
    assert exported["origin_date"].unique().tolist() == [origin_day]
    assert exported["origin_time"].unique().tolist() == [f"{gate[:2]}:{gate[2:]}"]
    assert exported["target_time"].iloc[0] == first_target_time
    assert exported["target_time"].iloc[-1] == last_target_time
    assert exported["p50"].iloc[-1] == expected_rows - 1


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
    # Loop until the quota trips (see above): a fixed count can straddle
    # a wall-clock minute boundary on slow runners.
    for _ in range(2 * keys.MIN_LIMIT):
        if not keys.check_and_hit(kid)[0]:
            break
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
