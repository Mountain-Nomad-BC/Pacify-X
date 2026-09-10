"""Bounded content consistency manifests; expected certification roles are external."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping

from .archive_io import member_identity, reject_path_links
from .input_files import (
    check_deadline,
    contained_file,
    cooperative_deadline,
    read_file_image,
    relative_source_path,
)
from .numeric_inputs import bounded_json_value, bounded_text

MAX_RECORDS = 10000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_CORPUS_BYTES = 256 * 1024 * 1024
_CUSTODY = frozenset({"quarantine", ".quarantine", "_quarantine"})


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _root(value: Path) -> Path:
    if type(value) is not type(Path()):
        raise ValueError("evidence root must be a filesystem path")
    bounded_text(str(value), "evidence root", maximum=4096, strip=False)
    if any(part == ".." or part.casefold() in _CUSTODY for part in value.parts):
        raise ValueError("evidence root is outside the admitted source corpus")
    reject_path_links(value)
    absolute = value.absolute()
    bounded_text(str(absolute), "absolute evidence root", maximum=4096, strip=False)
    if any(part.casefold() in _CUSTODY for part in absolute.parts):
        raise ValueError("evidence root is outside the admitted source corpus")
    reject_path_links(absolute)
    root = absolute.resolve(strict=True)
    if not stat.S_ISDIR(root.stat().st_mode):
        raise ValueError("evidence root must be a directory")
    return root


def _object(value: object, maximum: int) -> dict:
    if type(value) is not dict or len(value) > maximum:
        raise ValueError("evidence metadata must be a bounded actual object")
    for key in value:
        bounded_text(key, "evidence metadata key", maximum=4096, strip=False)
    return value


def _timestamp(value: object) -> str:
    value = bounded_text(value, "evidence timestamp", maximum=128, strip=False)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("evidence timestamp is malformed") from error
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamp requires a timezone")
    return value


def _label(value: object) -> str:
    return bounded_text(value, "evidence label", maximum=4096, strip=False)


def _sha(value: object) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or any(c not in "0123456789abcdef" for c in value)
    ):
        raise ValueError("evidence digest must be a lowercase SHA-256")
    return value


def _path(value: object) -> str:
    relative = relative_source_path(value)
    if any(part.casefold() in _CUSTODY for part in relative.split("/")):
        raise ValueError("evidence path is excluded from acquisition")
    return relative


def _preflight(
    root: Path, records: list[dict], *, verify: bool, deadline: float
) -> list[tuple[dict, Path | None, object]]:
    """Admit every original path and selected file size before any body read."""
    prepared = []
    aliases = set()
    file_ids = set()
    total = 0
    for record in records:
        check_deadline(deadline)
        relative = _path(record["path"])
        identity = member_identity(relative, allow_directory=False)
        if identity in aliases:
            raise ValueError("duplicate portable evidence path identity")
        aliases.add(identity)
        original = root / relative
        reject_path_links(original)
        # Optional missing records do not become a claim about newly appearing
        # files. The trusted expected-role/appearance policy remains external.
        if verify and record["status"] == "missing" and not record["required"]:
            if not _inside(original.resolve(strict=False), root):
                raise ValueError("evidence path escapes release root")
            prepared.append((record, None, None))
            continue
        try:
            path, info = contained_file(root, relative)
        except FileNotFoundError:
            if record["required"] or verify and record["status"] == "present":
                raise ValueError(
                    "required or previously present evidence is missing"
                ) from None
            prepared.append((record, None, None))
            continue
        if (
            verify
            and record["status"] == "present"
            and info.st_size != record["size_bytes"]
        ):
            raise ValueError("evidence file bytes changed before acquisition")
        if not 0 <= info.st_size <= MAX_FILE_BYTES:
            raise ValueError("evidence file exceeds its byte bound before acquisition")
        total += info.st_size
        if total > MAX_CORPUS_BYTES:
            raise ValueError(
                "evidence corpus exceeds its aggregate byte bound before acquisition"
            )
        file_id = (info.st_dev, info.st_ino)
        if info.st_ino and file_id in file_ids:
            raise ValueError("multiple evidence paths alias one filesystem identity")
        file_ids.add(file_id)
        prepared.append((record, path, info))
    check_deadline(deadline)
    return prepared


def _failure(error: Exception, *, timestamp: str | None = None) -> dict:
    # Never include evidence contents or an unbounded exception representation.
    message = str(error)[:4096]
    if timestamp is None:
        return {"valid": False, "record_count": None, "errors": [message]}
    return {
        "schema_version": "1.0",
        "generated_utc": timestamp,
        "evidence": [],
        "manifest_sha256": None,
        "valid": False,
        "errors": [message],
    }


def build_evidence_manifest(
    evidence_root: Path,
    *,
    roles: Mapping[str, Mapping[str, object]],
    generated_utc: str | None = None,
) -> dict[str, Any]:
    timestamp = datetime.now(timezone.utc).isoformat()
    try:
        deadline = cooperative_deadline()
        root = _root(evidence_root)
        timestamp = _timestamp(timestamp if generated_utc is None else generated_utc)
        _object(roles, MAX_RECORDS)
        for metadata in roles.values():
            _object(metadata, 4)
        bounded_json_value(roles)
        roles = json.loads(canonical_bytes(roles))
        records = []
        for relative, raw in sorted(roles.items()):
            metadata = _object(raw, 4)
            if set(metadata) - {"type", "required", "generation_gate", "producer"}:
                raise ValueError("unknown evidence role metadata field")
            required = metadata.get("required", False)
            if type(required) is not bool:
                raise ValueError("evidence required flag must be an actual boolean")
            records.append(
                {
                    "path": _path(relative),
                    "type": _label(metadata.get("type", "unknown")),
                    "required": required,
                    "status": "missing",
                    "size_bytes": None,
                    "sha256": None,
                    "generation_gate": _label(
                        metadata.get("generation_gate", "unknown")
                    ),
                    "generated_utc": timestamp,
                    "producer": _label(metadata.get("producer", "unknown")),
                }
            )
        prepared = _preflight(root, records, verify=False, deadline=deadline)
        for record, path, info in prepared:
            if path is not None:
                record.update(
                    status="present", size_bytes=info.st_size, sha256="0" * 64
                )
        payload = {
            "schema_version": "1.0",
            "generated_utc": timestamp,
            "evidence": records,
        }
        # Hash placeholders have the exact final width. Bound the complete
        # output projection before acquiring the first evidence body.
        bounded_json_value(payload)
        for record, path, info in prepared:
            if path is not None:
                data = read_file_image(
                    path, info, limit=MAX_FILE_BYTES, deadline=deadline
                )
                record["sha256"] = hashlib.sha256(data).hexdigest()
                del data
        check_deadline(deadline)
        return {
            **payload,
            "manifest_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
            "valid": True,
            "errors": [],
        }
    except (OSError, ValueError, TypeError) as error:
        return _failure(error, timestamp=timestamp)


def verify_evidence_manifest(
    evidence_root: Path, manifest: Mapping[str, object]
) -> dict[str, Any]:
    try:
        deadline = cooperative_deadline()
        root = _root(evidence_root)
        _object(manifest, 6)
        raw_records = manifest.get("evidence")
        if type(raw_records) is not list or len(raw_records) > MAX_RECORDS:
            raise ValueError("evidence manifest records must be a bounded array")
        for raw_record in raw_records:
            _object(raw_record, 9)
        bounded_json_value(manifest)
        manifest = json.loads(canonical_bytes(manifest))
        if set(manifest) != {
            "schema_version",
            "generated_utc",
            "evidence",
            "manifest_sha256",
            "valid",
            "errors",
        }:
            raise ValueError("evidence manifest shape is invalid")
        if (
            manifest["schema_version"] != "1.0"
            or manifest["valid"] is not True
            or manifest["errors"] != []
        ):
            raise ValueError("evidence manifest is not a valid complete builder result")
        timestamp = _timestamp(manifest["generated_utc"])
        records = manifest["evidence"]
        if type(records) is not list or len(records) > MAX_RECORDS:
            raise ValueError("evidence manifest records must be a bounded array")
        checked = []
        for raw in records:
            record = dict(_object(raw, 9))
            if set(record) != {
                "path",
                "type",
                "required",
                "status",
                "size_bytes",
                "sha256",
                "generation_gate",
                "generated_utc",
                "producer",
            }:
                raise ValueError("evidence manifest record shape is invalid")
            _path(record["path"])
            for label in ("type", "generation_gate", "producer"):
                _label(record[label])
            if record["generated_utc"] != timestamp:
                raise ValueError(
                    "evidence record generation differs from manifest generation"
                )
            if type(record["required"]) is not bool or record["status"] not in {
                "missing",
                "present",
            }:
                raise ValueError("evidence record status or required flag is invalid")
            if record["status"] == "missing":
                if (
                    record["required"]
                    or record["size_bytes"] is not None
                    or record["sha256"] is not None
                ):
                    raise ValueError("missing evidence record is inconsistent")
            else:
                if (
                    type(record["size_bytes"]) is not int
                    or not 0 <= record["size_bytes"] <= MAX_FILE_BYTES
                ):
                    raise ValueError("evidence record size must be a bounded integer")
                _sha(record["sha256"])
            checked.append(record)
        unsigned = {
            key: manifest[key]
            for key in ("schema_version", "generated_utc", "evidence")
        }
        if (
            _sha(manifest["manifest_sha256"])
            != hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
        ):
            raise ValueError("evidence manifest digest mismatch")
        prepared = _preflight(root, checked, verify=True, deadline=deadline)
        for record, path, info in prepared:
            if path is not None:
                data = read_file_image(
                    path, info, limit=MAX_FILE_BYTES, deadline=deadline
                )
                if (
                    len(data) != record["size_bytes"]
                    or hashlib.sha256(data).hexdigest() != record["sha256"]
                ):
                    raise ValueError("evidence file bytes changed")
        check_deadline(deadline)
        return {"valid": True, "record_count": len(checked), "errors": []}
    except (OSError, ValueError, TypeError) as error:
        return _failure(error)
