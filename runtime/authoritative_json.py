"""Fail-closed JSON loading with explicit authority classification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .paths import declared_file_available


class AuthoritativeStateError(RuntimeError):
    """Raised after authoritative state is refused or safely quarantined."""

    def __init__(self, message: str, *, receipt: Path | None = None) -> None:
        super().__init__(message)
        self.receipt = receipt


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _has_link_boundary(path: Path, root: Path) -> bool:
    cursor = path
    while True:
        if cursor.is_symlink() or (
            hasattr(cursor, "is_junction") and cursor.is_junction()
        ):
            return True
        if cursor == root:
            return False
        parent = cursor.parent
        if parent == cursor:
            return True
        cursor = parent


def _snapshot(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        stat = os.fstat(stream.fileno())
        data = stream.read()
    return {
        "size": len(data),
        "mtime_ns": stat.st_mtime_ns,
        "device": stat.st_dev,
        "inode": stat.st_ino,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": data,
    }


def _snapshot_metadata(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        key: snapshot[key]
        for key in ("size", "mtime_ns", "device", "inode", "sha256")
    }


def _write_record(path: Path, record: Mapping[str, object]) -> str:
    encoded = (json.dumps(dict(record), indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(encoded).hexdigest()


def load_state_classifications(root: Path) -> dict[str, dict[str, str]]:
    """Load and strictly validate the state-artifact classification registry."""
    path = root / "registry" / "state_artifact_classes.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != {"schema_version", "policy", "classes"}:
        raise ValueError("state classification registry fields are not exact")
    if payload["schema_version"] != "1.0" or not isinstance(payload["classes"], list):
        raise ValueError("state classification registry header is invalid")
    result: dict[str, dict[str, str]] = {}
    required = {"artifact_kind", "classification", "owner", "corruption_disposition"}
    for raw in payload["classes"]:
        if not isinstance(raw, dict) or set(raw) != required:
            raise ValueError("state classification record fields are not exact")
        record = {key: str(value) for key, value in raw.items()}
        kind = record["artifact_kind"]
        if not kind or kind in result:
            raise ValueError(f"duplicate or empty artifact kind: {kind}")
        expected = {
            "authoritative": "quarantine_fail_closed",
            "derived": "rebuild",
        }.get(record["classification"])
        if expected is None or record["corruption_disposition"] != expected:
            raise ValueError(f"invalid classification/disposition for {kind}")
        if not declared_file_available(root, record["owner"]):
            raise ValueError(f"missing artifact owner for {kind}: {record['owner']}")
        result[kind] = record
    return result


def _quarantine_corrupt(
    path: Path,
    *,
    artifact_kind: str,
    allowed_root: Path,
    quarantine_root: Path,
    parse_error: Exception,
) -> Path:
    source = path.resolve(strict=True)
    allowed = allowed_root.resolve(strict=True)
    quarantine = quarantine_root.resolve() if quarantine_root.exists() else quarantine_root.absolute()
    if not _inside(source, allowed) or not _inside(quarantine, allowed):
        raise AuthoritativeStateError("source and quarantine must remain below allowed root")
    if source == quarantine or _inside(quarantine, source):
        raise AuthoritativeStateError("quarantine boundary is invalid")
    if _has_link_boundary(source, allowed) or _has_link_boundary(quarantine.parent, allowed):
        raise AuthoritativeStateError("link or junction boundary refused")
    first = _snapshot(source)
    second = _snapshot(source)
    identity = ("size", "mtime_ns", "device", "inode", "sha256")
    if any(first[key] != second[key] for key in identity):
        raise AuthoritativeStateError("source changed during quarantine snapshots")
    destination_dir = quarantine / "corrupt" / artifact_kind
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"{str(second['sha256'])[:16]}-{source.name}"
    receipt = destination.with_suffix(destination.suffix + ".receipt.json")
    intent = Path(str(destination) + ".intent.json")
    recovery = Path(str(destination) + ".recovery.json")
    if any(item.exists() for item in (destination, receipt, intent, recovery)):
        raise AuthoritativeStateError("quarantine destination already exists")
    immediate = _snapshot(source)
    if any(second[key] != immediate[key] for key in identity):
        raise AuthoritativeStateError("source changed immediately before quarantine")
    created = datetime.now(timezone.utc).isoformat()
    intent_record = {
        "schema_version": "1.0",
        "artifact_kind": artifact_kind,
        "classification": "authoritative",
        "decision": "quarantine_intent",
        "original_path": source.as_posix(),
        "planned_custody_path": destination.as_posix(),
        "expected": _snapshot_metadata(immediate),
        "error_type": type(parse_error).__name__,
        "created_utc": created,
    }
    intent_sha256 = _write_record(intent, intent_record)
    moved = False
    try:
        os.replace(source, destination)
        moved = True
        observed = _snapshot(destination)
        if any(immediate[key] != observed[key] for key in identity):
            raise RuntimeError("filesystem_identity_mismatch")
    except (OSError, RuntimeError) as error:
        failure = str(error) if isinstance(error, RuntimeError) else type(error).__name__
        custody = destination if moved and destination.exists() else source
        recovery_record = {
            "schema_version": "1.0",
            "artifact_kind": artifact_kind,
            "classification": "authoritative",
            "decision": "quarantine_recovery_required",
            "original_path": source.as_posix(),
            "custody_path": custody.as_posix(),
            "moved": moved,
            "failure": failure,
            "expected": _snapshot_metadata(immediate),
            "intent_path": intent.as_posix(),
            "intent_sha256": intent_sha256,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        recovery_receipt = intent
        try:
            _write_record(recovery, recovery_record)
            recovery_receipt = recovery
        except OSError:
            pass
        raise AuthoritativeStateError(
            "authoritative quarantine recovery required", receipt=recovery_receipt
        ) from error
    record = {
        "schema_version": "1.0",
        "artifact_kind": artifact_kind,
        "classification": "authoritative",
        "decision": "quarantined_fail_closed",
        "original_path": source.as_posix(),
        "quarantined_path": destination.as_posix(),
        "sha256": immediate["sha256"],
        "bytes": immediate["size"],
        "filesystem_identity": {
            "device": immediate["device"],
            "inode": immediate["inode"],
        },
        "intent_path": intent.as_posix(),
        "intent_sha256": intent_sha256,
        "error_type": type(parse_error).__name__,
        "created_utc": created,
    }
    try:
        _write_record(receipt, record)
    except OSError as error:
        recovery_record = {
            "schema_version": "1.0",
            "artifact_kind": artifact_kind,
            "classification": "authoritative",
            "decision": "quarantine_recovery_required",
            "original_path": source.as_posix(),
            "custody_path": destination.as_posix(),
            "moved": True,
            "failure": "receipt_write_failed",
            "expected": _snapshot_metadata(immediate),
            "intent_path": intent.as_posix(),
            "intent_sha256": intent_sha256,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        recovery_receipt = intent
        try:
            _write_record(recovery, recovery_record)
            recovery_receipt = recovery
        except OSError:
            pass
        raise AuthoritativeStateError(
            "authoritative quarantine recovery required", receipt=recovery_receipt
        ) from error
    return receipt


def load_classified_json(
    root: Path,
    path: Path,
    *,
    artifact_kind: str,
    allowed_root: Path,
    quarantine_root: Path,
    validator: Callable[[Mapping[str, object]], None] | None = None,
) -> dict[str, Any]:
    """Load classified JSON; preserve corrupt authority and never invent fallback."""
    classes = load_state_classifications(root)
    record = classes.get(artifact_kind)
    if record is None:
        raise AuthoritativeStateError(f"unclassified state refused: {artifact_kind}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("state root must be an object")
        if validator is not None:
            validator(value)
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
        if record["classification"] == "derived":
            return {
                "schema_version": "1.0",
                "status": "rebuild_required",
                "artifact_kind": artifact_kind,
                "path": path.resolve().as_posix(),
                "error_type": type(error).__name__,
                "data": None,
            }
        if not path.is_file():
            raise AuthoritativeStateError(
                f"authoritative state unavailable: {artifact_kind}"
            ) from error
        receipt = _quarantine_corrupt(
            path,
            artifact_kind=artifact_kind,
            allowed_root=allowed_root,
            quarantine_root=quarantine_root,
            parse_error=error,
        )
        raise AuthoritativeStateError(
            f"authoritative state quarantined: {artifact_kind}", receipt=receipt
        ) from error
    return {
        "schema_version": "1.0",
        "status": "valid",
        "artifact_kind": artifact_kind,
        "path": path.resolve().as_posix(),
        "data": value,
    }
