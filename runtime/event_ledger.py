"""Tamper-evident append-only event ledgers with protected head anchors."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Mapping

from .file_lock import FileLock


ZERO_SHA256 = "0" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _event_hash(record: Mapping[str, object]) -> str:
    return _sha({key: value for key, value in record.items() if key != "event_sha256"})


def _paths(ledger: Path) -> tuple[Path, Path]:
    authority = ledger.parent / ".ledger-authority" / ledger.name
    return authority / "head.json", authority / "anchors"


def validate_event_ledger(
    ledger: Path, *, require_head: bool = True
) -> dict[str, object]:
    ledger = ledger.resolve()
    event_paths = tuple(sorted(ledger.glob("*.json"))) if ledger.is_dir() else ()
    errors: list[str] = []
    previous = ZERO_SHA256
    events: list[dict[str, object]] = []
    for expected, path in enumerate(event_paths, start=1):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            errors.append(f"{path.name}: unreadable event: {type(error).__name__}")
            continue
        required = {
            "schema_version",
            "sequence",
            "kind",
            "created_utc",
            "payload",
            "payload_sha256",
            "previous_event_sha256",
            "event_sha256",
        }
        if set(record) != required:
            errors.append(f"{path.name}: event fields are not exact")
            continue
        if record.get("sequence") != expected or not path.name.startswith(
            f"{expected:08d}-"
        ):
            errors.append(f"{path.name}: event sequence is not contiguous")
        payload = record.get("payload")
        if not isinstance(payload, Mapping) or record.get("payload_sha256") != _sha(
            payload
        ):
            errors.append(f"{path.name}: payload digest mismatch")
        if record.get("previous_event_sha256") != previous:
            errors.append(f"{path.name}: previous-event link mismatch")
        actual = _event_hash(record)
        if record.get("event_sha256") != actual:
            errors.append(f"{path.name}: event digest mismatch")
        previous = str(record.get("event_sha256", ""))
        events.append(record)
    head_path, anchors = _paths(ledger)
    if require_head and event_paths:
        try:
            head = json.loads(head_path.read_text(encoding="utf-8"))
            if head != {
                "schema_version": "1.0",
                "sequence": len(event_paths),
                "event_sha256": previous,
            }:
                errors.append("protected ledger head does not match event chain")
            anchor = anchors / f"{len(event_paths):08d}-{previous}.json"
            if (
                not anchor.is_file()
                or json.loads(anchor.read_text(encoding="utf-8")) != head
            ):
                errors.append("protected ledger-head anchor is missing or mismatched")
        except (OSError, UnicodeError, json.JSONDecodeError):
            errors.append("protected ledger head is missing or unreadable")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "event_count": len(event_paths),
        "head_sha256": previous,
        "errors": errors,
        "events": events,
    }


def read_event_tail(
    ledger: Path, *, limit: int = 100, require_head: bool = True
) -> dict[str, object]:
    """Stream the valid event prefix and return a bounded tail plus ancestry health."""
    if limit < 0 or limit > 10_000:
        raise ValueError("event tail limit must be between zero and 10000")
    ledger = ledger.resolve()
    event_paths = tuple(sorted(ledger.glob("*.json"))) if ledger.is_dir() else ()
    if not event_paths:
        return {
            "schema_version": "1.0",
            "events": [],
            "health": {
                "status": "missing",
                "valid_prefix_count": 0,
                "failed_file": None,
                "ignored_suffix_files": 0,
                "reason": None,
                "ancestry_head_sha256": ZERO_SHA256,
            },
        }
    required = {
        "schema_version",
        "sequence",
        "kind",
        "created_utc",
        "payload",
        "payload_sha256",
        "previous_event_sha256",
        "event_sha256",
    }
    previous = ZERO_SHA256
    records: list[dict[str, object]] = []
    failure: tuple[str, str] | None = None
    for expected, path in enumerate(event_paths, start=1):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or set(record) != required:
                raise ValueError("event fields are not exact")
            if record.get("sequence") != expected or not path.name.startswith(
                f"{expected:08d}-"
            ):
                raise ValueError("event sequence is not contiguous")
            payload = record.get("payload")
            if not isinstance(payload, Mapping) or record.get("payload_sha256") != _sha(
                payload
            ):
                raise ValueError("payload digest mismatch")
            if record.get("previous_event_sha256") != previous:
                raise ValueError("previous-event link mismatch")
            if record.get("event_sha256") != _event_hash(record):
                raise ValueError("event digest mismatch")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            reason = (
                "truncated-or-malformed-event"
                if isinstance(error, json.JSONDecodeError)
                else str(error)
            )
            failure = (path.name, reason)
            break
        previous = str(record["event_sha256"])
        records.append(record)
    if failure is None and require_head:
        head_path, anchors = _paths(ledger)
        expected_head = {
            "schema_version": "1.0",
            "sequence": len(records),
            "event_sha256": previous,
        }
        try:
            head = json.loads(head_path.read_text(encoding="utf-8"))
            anchor = anchors / f"{len(records):08d}-{previous}.json"
            if head != expected_head or json.loads(
                anchor.read_text(encoding="utf-8")
            ) != expected_head:
                raise ValueError("protected ledger head mismatch")
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            failure = (head_path.name, str(error))
    failed_index = len(records)
    health = {
        "status": "degraded" if failure else "healthy",
        "valid_prefix_count": len(records),
        "failed_file": failure[0] if failure else None,
        "ignored_suffix_files": len(event_paths) - failed_index if failure else 0,
        "reason": failure[1] if failure else None,
        "ancestry_head_sha256": previous,
    }
    return {
        "schema_version": "1.0",
        "events": records[-limit:] if limit else [],
        "health": health,
    }


def _publish_head(ledger: Path, sequence: int, event_sha256: str) -> None:
    head_path, anchors = _paths(ledger)
    anchors.mkdir(parents=True, exist_ok=True)
    head = {"schema_version": "1.0", "sequence": sequence, "event_sha256": event_sha256}
    anchor = anchors / f"{sequence:08d}-{event_sha256}.json"
    with anchor.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(head, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    head_path.parent.mkdir(parents=True, exist_ok=True)
    if head_path.is_file():
        history = head_path.parent / "history" / f"{sequence - 1:08d}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        with history.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(head_path.read_text(encoding="utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    temporary = head_path.with_name(f".{head_path.name}.{sequence:08d}.prepared")
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(head, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, head_path)


def append_chained_event(
    ledger: Path, kind: str, payload: Mapping[str, object]
) -> Path:
    ledger = ledger.resolve()
    if not kind or not all(
        character.isalnum() or character in "-_" for character in kind
    ):
        raise ValueError("event kind must be a bounded identifier")
    ledger.mkdir(parents=True, exist_ok=True)
    with FileLock(ledger / ".event-ledger.lock"):
        current = validate_event_ledger(ledger, require_head=any(ledger.glob("*.json")))
        if not current["valid"]:
            raise ValueError(
                "event ledger integrity failure: " + "; ".join(current["errors"])
            )
        sequence = int(current["event_count"]) + 1
        record: dict[str, object] = {
            "schema_version": "1.0",
            "sequence": sequence,
            "kind": kind,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "payload": dict(payload),
            "payload_sha256": _sha(payload),
            "previous_event_sha256": current["head_sha256"],
        }
        record["event_sha256"] = _event_hash(record)
        name = f"{sequence:08d}-{kind}-{str(record['event_sha256'])[:12]}.json"
        prepared = ledger / f".{name}.prepared"
        target = ledger / name
        with prepared.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(prepared, target)
        _publish_head(ledger, sequence, str(record["event_sha256"]))
        return target
