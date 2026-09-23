"""The operational digest is one real HTTP POST for a completed day."""

import json
import threading
from contextlib import nullcontext
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace


def test_score_digest_posts_once_to_local_receiver(tmp_path, monkeypatch):
    from delukit.dagster_app import definitions as pipeline

    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            received.append(json.loads(self.rfile.read(length)))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv(
            "DELUKIT_ALERT_WEBHOOK", f"http://127.0.0.1:{server.server_port}/score"
        )
        monkeypatch.setattr(
            pipeline, "SCORE_NOTIFICATIONS_LOG", tmp_path / "notifications.jsonl"
        )
        rows = [
            {
                "gate": "0530",
                "span": "d1",
                "lead_day": 1,
                "target": "load_actual_mw",
                "status": "complete",
                "reason": None,
                "as_of": "2026-01-06T14:30:00+00:00",
                "model": "xgboost",
                "rmae": 0.1,
                "rcrps": 0.2,
                "obs_p10": 0.1,
                "obs_p90": 0.9,
            },
            {
                "gate": "1130",
                "span": "d1",
                "lead_day": 1,
                "target": "load_actual_mw",
                "status": "incomplete",
                "reason": "truth_unavailable_at_cutoff",
                "as_of": "2026-01-06T14:30:00+00:00",
                "model": "median",
                "rmae": None,
                "rcrps": None,
            },
        ]
        score_path = tmp_path / "delivery.parquet"
        assert pipeline.send_score_digest(date(2026, 1, 5), rows, score_path)
        assert not pipeline.send_score_digest(date(2026, 1, 5), rows, score_path)
        assert len(received) == 1
        message = received[0]["text"]
        assert "Complete 1/2; incomplete 1" in message
        assert "0530 load_actual_mw: rMAE 0.100, rCRPS 0.200" in message
        assert "P10-P90 coverage 80.0%" in message
        assert "1130 load_actual_mw: incomplete" in message
        assert "Fallback forecasts: 1" in message
        assert str(score_path) in message
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_failure_alert_keeps_provider_error_text_out_of_slack(tmp_path, monkeypatch):
    import urllib.request

    from delukit.dagster_app import definitions as pipeline

    sent = []

    def capture(request, timeout):
        sent.append(json.loads(request.data))
        return nullcontext()

    monkeypatch.setenv("DELUKIT_ALERT_WEBHOOK", "https://hooks.slack.com/test")
    monkeypatch.setattr(urllib.request, "urlopen", capture)
    monkeypatch.setattr(pipeline, "ALERTS_LOG", tmp_path / "alerts.jsonl")
    context = SimpleNamespace(
        dagster_run=SimpleNamespace(job_name="source_refresh", run_id="run-1"),
        dagster_event=SimpleNamespace(
            step_key="raw_data", message="securityToken=provider-secret"
        ),
        log=SimpleNamespace(error=lambda *_args: None, warning=lambda *_args: None),
    )

    pipeline.ops_failure_alert._run_status_sensor_fn(context)
    assert len(sent) == 1
    assert "raw_data" in sent[0]["text"]
    assert "provider-secret" not in sent[0]["text"]
    assert "provider-secret" not in pipeline.ALERTS_LOG.read_text()
