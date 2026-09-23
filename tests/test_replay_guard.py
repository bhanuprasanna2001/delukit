"""Strict backtests do not assume current raw values existed at older origins."""

from datetime import UTC, datetime, timedelta

import pytest


def test_strict_replay_rejects_unobserved_and_late_revisions(tmp_dirs, monkeypatch):
    import delukit.dataset as dataset
    from delukit.sources import observations

    path = tmp_dirs["raw"] / "2026-01-05" / "weather" / "land" / "data.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"A")
    start = datetime.now(UTC) - timedelta(hours=1)
    end = start + timedelta(minutes=15)
    with pytest.raises(ValueError, match="no observed provenance"):
        dataset.assert_replayable(start, end)

    observations.observe(path, b"A")
    with pytest.raises(ValueError, match="starts before latest observed"):
        dataset.assert_replayable(start, end)

    after_capture = datetime.now(UTC) + timedelta(minutes=1)
    dataset.assert_replayable(after_capture, after_capture + timedelta(minutes=15))
