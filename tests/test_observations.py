"""Provider revisions retain the time each value was actually observed."""

from datetime import UTC, datetime

import pytest


def test_returned_old_payload_is_a_new_vintage(tmp_path, monkeypatch):
    from delukit.sources import observations

    current = tmp_path / "data.xml"
    moments = iter(
        [
            datetime(2026, 1, 5, 4, 30, tzinfo=UTC),
            datetime(2026, 1, 5, 5, 45, tzinfo=UTC),
            datetime(2026, 1, 5, 11, 0, tzinfo=UTC),
            datetime(2026, 1, 5, 12, 0, tzinfo=UTC),
        ]
    )

    class Clock(datetime):
        @classmethod
        def now(cls, _zone):
            return next(moments)

    monkeypatch.setattr(observations, "datetime", Clock)
    for payload in (b"A", b"A", b"B", b"A"):
        observations.observe(current, payload)
        current.write_bytes(payload)

    assert observations.known_at(current) == datetime(2026, 1, 5, 12, tzinfo=UTC)
    assert len(list((tmp_path / "observations").glob("*.json"))) == 4
    assert len(list((tmp_path / "observations" / "payloads").glob("*.xml"))) == 2


def test_missing_or_corrupt_provenance_fails_closed(tmp_path):
    from delukit.sources.observations import known_at, observe

    current = tmp_path / "data.xml"
    current.write_bytes(b"A")
    with pytest.raises(ValueError, match="no observed provenance"):
        known_at(current)
    observe(current, b"A")
    payload = next((tmp_path / "observations" / "payloads").glob("*.xml"))
    payload.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="corrupt raw observation"):
        known_at(current)


def test_bootstrap_stamps_legacy_only_once(tmp_path):
    from delukit.sources.observations import bootstrap_legacy, known_at

    current = tmp_path / "2026-01-05" / "weather" / "land" / "data.json"
    current.parent.mkdir(parents=True)
    current.write_bytes(b'[{"hourly": {}}]')
    assert bootstrap_legacy(tmp_path) == 1
    first = known_at(current)
    assert bootstrap_legacy(tmp_path) == 0
    assert known_at(current) == first
