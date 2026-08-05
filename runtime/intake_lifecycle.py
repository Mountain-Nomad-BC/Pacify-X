"""Append-only source-intake lifecycle with stable freeze verification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Mapping


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def snapshot_tree(root: Path, *, source_alias: str) -> dict[str, object]:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise ValueError("source intake root must be a directory")
    records: list[dict[str, object]] = []
    for path in sorted(
        resolved.rglob("*"), key=lambda item: item.as_posix().casefold()
    ):
        if not path.is_file():
            continue
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        records.append(
            {
                "path": path.relative_to(resolved).as_posix(),
                "sha256": digest,
                "bytes": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
            }
        )
    canonical = "\n".join(
        f"{item['path']}\0{item['sha256']}\0{item['bytes']}\0{item['mtime_ns']}"
        for item in records
    )
    return {
        "source_alias": source_alias,
        "captured_utc": _timestamp(_utc_now()),
        "file_count": len(records),
        "byte_count": sum(int(item["bytes"]) for item in records),
        "tree_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "records": records,
    }


def load_events(state_dir: Path) -> tuple[dict[str, object], ...]:
    if not state_dir.exists():
        return ()
    if not state_dir.is_dir():
        raise ValueError("intake state path must be a directory")
    events = []
    for path in sorted(state_dir.glob("*.json")):
        event = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(event, dict)
            or "event" not in event
            or "sequence" not in event
        ):
            raise ValueError(f"invalid intake event: {path.name}")
        events.append(event)
    expected = list(range(1, len(events) + 1))
    if [int(event["sequence"]) for event in events] != expected:
        raise ValueError("intake event sequence is incomplete or reordered")
    return tuple(events)


def _append_event(
    state_dir: Path, event: str, payload: Mapping[str, object]
) -> dict[str, object]:
    state_dir.mkdir(parents=True, exist_ok=True)
    for _ in range(8):
        sequence = len(load_events(state_dir)) + 1
        record = {
            "schema_version": "1.0",
            "sequence": sequence,
            "event": event,
            "created_utc": _timestamp(_utc_now()),
            **dict(payload),
        }
        path = state_dir / f"{sequence:06d}-{event}.json"
        try:
            with path.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(record, stream, indent=2)
                stream.write("\n")
            return record
        except FileExistsError:
            continue
    raise RuntimeError("intake event ledger is receiving concurrent writes")


def intake_status(state_dir: Path) -> dict[str, object]:
    events = load_events(state_dir)
    if not events:
        return {"status": "uninitialized", "event_count": 0, "source_alias": None}
    status = "open"
    for event in events:
        if event["event"] in {"open", "reopen"}:
            status = "open"
        elif event["event"] == "close":
            status = "closed"
    return {
        "status": status,
        "event_count": len(events),
        "source_alias": events[-1].get("source_alias"),
        "last_event": events[-1]["event"],
        "last_event_utc": events[-1]["created_utc"],
    }


def open_intake(
    state_dir: Path, *, source_alias: str, opened_by: str
) -> dict[str, object]:
    if not source_alias.strip() or not opened_by.strip():
        raise ValueError("source alias and opener are required")
    status = intake_status(state_dir)
    if status["status"] == "open":
        raise ValueError("source intake is already open")
    event = "open" if status["status"] == "uninitialized" else "reopen"
    return _append_event(
        state_dir, event, {"source_alias": source_alias, "opened_by": opened_by}
    )


def record_snapshot(
    source: Path, state_dir: Path, *, source_alias: str
) -> dict[str, object]:
    status = intake_status(state_dir)
    if status["status"] != "open":
        raise ValueError("source intake must be open before recording a snapshot")
    if status["source_alias"] != source_alias:
        raise ValueError("source alias does not match the intake ledger")
    snapshot = snapshot_tree(source, source_alias=source_alias)
    return _append_event(
        state_dir, "snapshot", {"source_alias": source_alias, "snapshot": snapshot}
    )


def close_intake(
    source: Path,
    state_dir: Path,
    *,
    source_alias: str,
    approved_by: str,
    minimum_stability_seconds: float = 30.0,
) -> dict[str, object]:
    if not approved_by.strip():
        raise ValueError("explicit closure approver is required")
    if minimum_stability_seconds < 0:
        raise ValueError("minimum stability window cannot be negative")
    status = intake_status(state_dir)
    if status["status"] != "open" or status["source_alias"] != source_alias:
        raise ValueError("matching source intake is not open")
    snapshots = [
        event for event in load_events(state_dir) if event["event"] == "snapshot"
    ]
    if len(snapshots) < 2:
        raise ValueError("two recorded snapshots are required before closure")
    first, second = snapshots[-2:]
    left = first["snapshot"]
    right = second["snapshot"]
    elapsed = (
        datetime.fromisoformat(str(second["created_utc"]))
        - datetime.fromisoformat(str(first["created_utc"]))
    ).total_seconds()
    if (
        left["tree_sha256"] != right["tree_sha256"]
        or left["records"] != right["records"]
    ):
        raise ValueError("the two latest source snapshots are not identical")
    if elapsed < minimum_stability_seconds:
        raise ValueError("source snapshots do not satisfy the stability window")
    current = snapshot_tree(source, source_alias=source_alias)
    if (
        current["tree_sha256"] != right["tree_sha256"]
        or current["records"] != right["records"]
    ):
        raise ValueError("source changed after the accepted snapshot")
    return _append_event(
        state_dir,
        "close",
        {
            "source_alias": source_alias,
            "approved_by": approved_by,
            "minimum_stability_seconds": minimum_stability_seconds,
            "accepted_snapshot": current,
        },
    )


def require_closed_stable(
    source: Path, state_dir: Path, *, source_alias: str
) -> dict[str, object]:
    events = load_events(state_dir)
    status = intake_status(state_dir)
    if status["status"] != "closed" or status["source_alias"] != source_alias:
        raise ValueError("source intake is not explicitly closed")
    closure = next(event for event in reversed(events) if event["event"] == "close")
    accepted = closure["accepted_snapshot"]
    current = snapshot_tree(source, source_alias=source_alias)
    if (
        current["tree_sha256"] != accepted["tree_sha256"]
        or current["records"] != accepted["records"]
    ):
        raise ValueError(
            "closed source intake has drifted; reopen it before processing"
        )
    return current


def quarantine_closed_intake(
    source: Path,
    destination: Path,
    state_dir: Path,
    *,
    workspace: Path,
    source_alias: str,
    manifest_name: str = "QUARANTINE_MANIFEST.json",
) -> dict[str, object]:
    """Move an explicitly closed intake into recoverable quarantine without deletion."""
    workspace = workspace.resolve()
    source = source.resolve()
    destination = destination.resolve()
    if not workspace.is_dir() or not source.is_dir():
        raise ValueError("workspace and source intake must exist")
    try:
        source_relative = source.relative_to(workspace)
        destination_relative = destination.relative_to(workspace)
    except ValueError as error:
        raise ValueError(
            "source and quarantine destination must stay inside the workspace"
        ) from error
    if source == workspace or destination == workspace or source == destination:
        raise ValueError("source or quarantine destination is too broad")
    if "quarantine" not in {part.casefold() for part in destination_relative.parts}:
        raise ValueError("destination must be inside an explicit quarantine tree")
    if destination.exists():
        raise ValueError("quarantine destination already exists")
    if not manifest_name or Path(manifest_name).name != manifest_name:
        raise ValueError("manifest name must be one bounded filename")

    accepted = require_closed_stable(source, state_dir, source_alias=source_alias)
    expected_records = accepted["records"]
    # Repeat immediately before the move to close the validation window.
    immediate = snapshot_tree(source, source_alias=source_alias)
    if (
        immediate["tree_sha256"] != accepted["tree_sha256"]
        or immediate["records"] != expected_records
    ):
        raise ValueError("source changed during quarantine preflight")

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    moved = snapshot_tree(destination, source_alias=source_alias)
    if (
        source.exists()
        or moved["tree_sha256"] != accepted["tree_sha256"]
        or moved["records"] != expected_records
    ):
        raise RuntimeError("post-move quarantine reconciliation failed")

    receipt = {
        "schema_version": "1.0",
        "operation": "recoverable_move_to_quarantine",
        "source_alias": source_alias,
        "source_path": source_relative.as_posix(),
        "quarantine_path": destination_relative.as_posix(),
        "source_file_count": moved["file_count"],
        "source_byte_count": moved["byte_count"],
        "source_tree_sha256": moved["tree_sha256"],
        "intake_closed": True,
        "pre_move_equality_verified": True,
        "post_move_inventory_reconciled": True,
        "hard_delete": False,
        "recovery": "Move the quarantined source tree back to its recorded source path only after an approved reopen operation.",
        "files": [
            {"path": item["path"], "sha256": item["sha256"], "bytes": item["bytes"]}
            for item in moved["records"]
        ],
    }
    manifest = destination / manifest_name
    with manifest.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    return receipt
