"""Fail-closed JSON loading with explicit authority classification."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .paths import resolve_declared_path
import time
from .input_files import (
    contained_file,
    read_file_image,
    relative_source_path,
    check_deadline,
)
from .archive_io import reject_path_links, member_identity
from .numeric_inputs import bounded_text, bounded_sequence
from .json_io import decode_json_object, validate_json_value


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
    bounded_text(str(path), "snapshot path", maximum=4096, strip=False)
    candidate, info = contained_file(path.parent, path.name)
    data = read_file_image(
        candidate, info, limit=8 * 1024 * 1024, deadline=time.monotonic() + 60.0
    )
    return {
        "size": len(data),
        "mtime_ns": info.st_mtime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": bytes(data),
    }


def _snapshot_metadata(snapshot: Mapping[str, object]) -> dict[str, object]:
    return {
        key: snapshot[key] for key in ("size", "mtime_ns", "device", "inode", "sha256")
    }


def _write_record(path: Path, record: Mapping[str, object]) -> str:
    encoded = (json.dumps(dict(record), indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(encoded).hexdigest()


def load_state_classifications(root: Path) -> dict[str, dict[str, str]]:
    """Read one bounded strict classification image; metadata grants no authority."""
    deadline = time.monotonic() + 60.0
    root = _checked_root(root)
    path, info = contained_file(root, "registry/state_artifact_classes.json")
    raw = read_file_image(path, info, limit=1024 * 1024, deadline=deadline)
    payload = decode_json_object(
        raw, max_bytes=1024 * 1024, max_depth=32, max_nodes=100000
    )
    if set(payload) != {"schema_version", "policy", "classes"}:
        raise ValueError("state classification registry fields are not exact")
    if payload["schema_version"] != "1.0":
        raise ValueError("state classification registry header is invalid")
    bounded_text(
        payload["policy"], "state classification policy", maximum=4096, strip=False
    )
    rows = bounded_sequence(payload["classes"], "state classifications", maximum=10000)
    result = {}
    identities = set()
    required = {"artifact_kind", "classification", "owner", "corruption_disposition"}
    for row in rows:
        check_deadline(deadline)
        if type(row) is not dict or set(row) != required:
            raise ValueError("state classification record fields are not exact")
        kind = _artifact_kind(row["artifact_kind"])
        identity = member_identity(kind, allow_directory=False)
        if identity in identities:
            raise ValueError("duplicate or ambiguous artifact kind")
        identities.add(identity)
        classification = bounded_text(
            row["classification"], "classification", maximum=32, strip=False
        )
        disposition = bounded_text(
            row["corruption_disposition"],
            "corruption disposition",
            maximum=64,
            strip=False,
        )
        expected = {
            "authoritative": "quarantine_fail_closed",
            "derived": "rebuild",
        }.get(classification)
        if expected is None or disposition != expected:
            raise ValueError("invalid classification/disposition")
        owner = relative_source_path(row["owner"])
        # Source checkout and installed asset/package roots have distinct layouts.
        # The existing resolver owns source-only availability semantics.
        reject_path_links(root / owner)
        resolved = resolve_declared_path(root, owner)
        if resolved is not None:
            reject_path_links(resolved)
            if not resolved.is_file():
                raise ValueError("missing artifact owner")
        result[kind] = {
            "artifact_kind": kind,
            "classification": classification,
            "owner": owner,
            "corruption_disposition": disposition,
        }
    check_deadline(deadline)
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
    quarantine = (
        quarantine_root.resolve()
        if quarantine_root.exists()
        else quarantine_root.absolute()
    )
    if not _inside(source, allowed) or not _inside(quarantine, allowed):
        raise AuthoritativeStateError(
            "source and quarantine must remain below allowed root"
        )
    if source == quarantine or _inside(quarantine, source):
        raise AuthoritativeStateError("quarantine boundary is invalid")
    if _has_link_boundary(source, allowed) or _has_link_boundary(
        quarantine.parent, allowed
    ):
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
    except (OSError, RuntimeError, ValueError) as error:
        failure = (
            str(error) if isinstance(error, RuntimeError) else type(error).__name__
        )
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
    """Separate bounded admission, demonstrated parse corruption and validation."""
    deadline = time.monotonic() + 60.0
    try:
        path = _state_location(path, allowed_root)
        artifact_kind = _artifact_kind(artifact_kind)
        if validator is not None and not callable(validator):
            raise ValueError("validator must be callable")
    except (OSError, ValueError, TypeError) as error:
        raise AuthoritativeStateError("state input boundary refused") from error
    classes = load_state_classifications(root)
    record = classes.get(artifact_kind)
    if record is None:
        raise AuthoritativeStateError(f"unclassified state refused: {artifact_kind}")

    def rebuild(error: Exception) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": "rebuild_required",
            "artifact_kind": artifact_kind,
            "path": path.as_posix(),
            "error_type": type(error).__name__,
            "data": None,
        }

    try:
        check_deadline(deadline)
        candidate, info = contained_file(path.parent, path.name)
        raw = read_file_image(candidate, info, limit=8 * 1024 * 1024, deadline=deadline)
    except FileNotFoundError as error:
        if record["classification"] == "derived":
            return rebuild(error)
        raise AuthoritativeStateError(
            f"authoritative state unavailable: {artifact_kind}"
        ) from error
    except (OSError, ValueError) as error:
        raise AuthoritativeStateError(
            "state acquisition refused without custody effects"
        ) from error
    try:
        value = decode_json_object(
            raw, max_bytes=8 * 1024 * 1024, max_depth=32, max_nodes=100000
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        if record["classification"] == "derived":
            return rebuild(error)
        # This preserves the existing custody owner. Binding this exact failed
        # image to subsequent snapshots and the move remains a D/E obligation.
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
    except ValueError as error:
        raise AuthoritativeStateError(
            "state JSON contract or budget refused without custody effects"
        ) from error
    try:
        check_deadline(deadline)
        if validator is not None and validator(value) is not None:
            raise ValueError("validator must return None")
        if validator is not None:
            validate_json_value(value, max_depth=32, max_nodes=100000)
        check_deadline(deadline)
    except Exception as error:
        raise AuthoritativeStateError(
            "state validator or deadline refused without custody effects"
        ) from error
    return {
        "schema_version": "1.0",
        "status": "valid",
        "artifact_kind": artifact_kind,
        "path": path.as_posix(),
        "data": value,
    }


def _checked_root(value: Path) -> Path:
    if not isinstance(value, Path):
        raise ValueError("state root must be a Path")
    bounded_text(str(value), "state root", maximum=4096, strip=False)
    reject_path_links(value)
    if not value.is_dir():
        raise ValueError("state root must be an existing directory")
    return value.absolute()


def _artifact_kind(value: object) -> str:
    result = relative_source_path(
        bounded_text(value, "artifact kind", maximum=256, strip=False)
    )
    if "/" in result:
        raise ValueError("artifact kind must be one portable component")
    return result


def _state_location(path: Path, allowed_root: Path) -> Path:
    allowed = _checked_root(allowed_root)
    if not isinstance(path, Path):
        raise ValueError("state path must be a Path")
    bounded_text(str(path), "state path", maximum=4096, strip=False)
    original = path.absolute()
    relative = relative_source_path(original.relative_to(allowed).as_posix())
    candidate = allowed / relative
    reject_path_links(candidate)
    if not candidate.resolve(strict=False).is_relative_to(allowed.resolve(strict=True)):
        raise ValueError("state path escapes allowed root")
    return candidate
