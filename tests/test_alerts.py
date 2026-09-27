import json


def test_daily_report_uses_alert_outbox_without_repeat_delivery(monkeypatch, tmp_path):
    from delukit.ops import alerts

    monkeypatch.setattr(alerts, "ALERT_DB", tmp_path / "alerts.db")
    monkeypatch.setenv("DELUKIT_ALERT_WEBHOOK", "https://example.test/webhook")
    sent = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def urlopen(request, timeout):
        sent.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(alerts.urllib.request, "urlopen", urlopen)
    assert alerts.record(
        "daily-report/2026-01-08",
        True,
        "2 complete; 1 pending.",
        log_path=tmp_path / "alerts.log",
    )
    assert alerts.deliver_pending() == 1
    assert alerts.deliver_pending() == 0
    assert sent == [
        {"text": "*delukit REPORT* `daily-report/2026-01-08`\n2 complete; 1 pending."}
    ]
