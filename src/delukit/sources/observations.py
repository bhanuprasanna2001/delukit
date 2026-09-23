"""Immutable fetch observations beside the current raw provider file."""

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path


def observe(
    current: Path,
    payload: bytes,
    *,
    semantic: bytes | None = None,
    source_issued_at: datetime | None = None,
) -> None:
    """Keep the exact response and when this process first saw it."""
    fetched = datetime.now(UTC)
    name = f"{fetched:%Y%m%dT%H%M%S%fZ}_{uuid.uuid4().hex}"
    directory = current.parent / "observations"
    directory.mkdir(parents=True, exist_ok=True)
    payload_hash = hashlib.sha256(payload).hexdigest()
    payload_dir = directory / "payloads"
    payload_dir.mkdir(exist_ok=True)
    payload_path = payload_dir / f"{payload_hash}{current.suffix}"
    metadata_path = directory / f"{name}.json"
    metadata = {
        "fetched_at": fetched.isoformat(),
        "known_at": fetched.isoformat(),
        "source_issued_at": source_issued_at.isoformat() if source_issued_at else None,
        "payload_hash": payload_hash,
        "semantic_hash": hashlib.sha256(
            semantic if semantic is not None else payload
        ).hexdigest(),
        "payload_file": str(payload_path.relative_to(directory)),
    }
    try:
        with payload_path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError:
        if hashlib.sha256(payload_path.read_bytes()).hexdigest() != payload_hash:
            raise ValueError(f"corrupt raw observation: {payload_path}") from None
    with metadata_path.open("x") as output:
        json.dump(metadata, output, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def known_at(current: Path, *, semantic: bytes | None = None) -> datetime:
    """Start of the latest uninterrupted run of the current semantic value."""
    if not current.exists():
        raise FileNotFoundError(current)
    body = current.read_bytes()
    digest = hashlib.sha256(semantic if semantic is not None else body).hexdigest()
    events = []
    for path in (current.parent / "observations").glob("*.json"):
        observation = json.loads(path.read_text())
        payload = path.parent / observation["payload_file"]
        if (
            hashlib.sha256(payload.read_bytes()).hexdigest()
            != observation["payload_hash"]
        ):
            raise ValueError(f"corrupt raw observation: {payload}")
        events.append(
            (
                datetime.fromisoformat(observation["known_at"]),
                observation["semantic_hash"],
            )
        )
    if not events:
        raise ValueError(f"no observed provenance for current raw file: {current}")
    events.sort()
    if events[-1][1] != digest:
        raise ValueError(
            f"latest observed revision differs from current raw file: {current}"
        )
    start = events[-1][0]
    for event_time, event_hash in reversed(events[:-1]):
        if event_hash != digest:
            break
        start = event_time
    return start


def bootstrap_legacy(base: Path) -> int:
    """Stamp existing latest-only raw files with a conservative known time."""
    from delukit.sources.entsoe import _comparable as entsoe_comparable
    from delukit.sources.smard import _comparable as smard_comparable

    added = 0
    for current in base.glob("????-??-??/*/*/data.*"):
        if current.suffix not in (".xml", ".json"):
            continue
        if any((current.parent / "observations").glob("*.json")):
            continue
        payload = current.read_bytes()
        source = current.parent.parent.name
        if source == "entsoe":
            semantic = entsoe_comparable(payload)
        elif source == "smard":
            semantic = smard_comparable(payload)
        else:
            semantic = payload
        observe(current, payload, semantic=semantic)
        added += 1
    return added
