"""Gate runs consume only the validated pre-gate dataset commit."""

from datetime import date, datetime, time

import pytest


def test_snapshot_marker_detects_late_and_partial_builds(tmp_dirs):
    from delukit.core.clean import BERLIN
    from delukit.dagster_app.definitions import (
        REQUIRED_VERSIONED_PARTS,
        _commit_snapshot,
        _require_prepared_snapshot,
    )

    for name in REQUIRED_VERSIONED_PARTS:
        (tmp_dirs["versioned"] / f"{name}.parquet").write_bytes(b"part")
    day = date(2026, 1, 5)
    with pytest.raises(RuntimeError, match="no validated commit marker"):
        _require_prepared_snapshot(day, 5, time(5, 30))

    _commit_snapshot(datetime(2026, 1, 5, 5, 10, tzinfo=BERLIN))
    _require_prepared_snapshot(day, 5, time(5, 30))

    (tmp_dirs["versioned"] / "weather.parquet").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="changed after validation"):
        _require_prepared_snapshot(day, 5, time(5, 30))

    _commit_snapshot(datetime(2026, 1, 5, 5, 31, tzinfo=BERLIN))
    with pytest.raises(RuntimeError, match="pre-run refresh window"):
        _require_prepared_snapshot(day, 5, time(5, 30))
