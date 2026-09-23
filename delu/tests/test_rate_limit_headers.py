"""A keyed client can tell when to retry after exhausting its quota."""

from fastapi.testclient import TestClient


def test_keyed_quota_response_includes_retry_headers(tmp_dirs, monkeypatch):
    from backend import app, auth, keys

    user_id = auth.signup("quota@example.test", "password123")
    _, key = keys.issue(user_id)
    monkeypatch.setattr(keys, "MIN_LIMIT", 0)

    response = TestClient(app.app).get("/v1/forecast", headers={"X-API-Key": key})

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) > 0
    assert response.headers["X-RateLimit-Minute"] == "0"
    assert response.headers["X-RateLimit-Day"] == str(keys.DAY_LIMIT)
