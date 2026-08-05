"""Content-addressed release evidence manifests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


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


def build_evidence_manifest(
    evidence_root: Path,
    *,
    roles: Mapping[str, Mapping[str, object]],
    generated_utc: str | None = None,
) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    timestamp = generated_utc or datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    for relative, metadata in sorted(roles.items()):
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            errors.append(f"evidence path escapes release root: {relative}")
            continue
        path = (root / candidate).resolve(strict=False)
        if not _inside(path, root):
            errors.append(f"evidence path escapes release root: {relative}")
            continue
        required = metadata.get("required") is True
        if not path.is_file():
            if required:
                errors.append(f"required evidence is missing: {relative}")
            records.append(
                {
                    "path": candidate.as_posix(),
                    "type": str(metadata.get("type", "unknown")),
                    "required": required,
                    "status": "missing",
                    "size_bytes": None,
                    "sha256": None,
                    "generation_gate": str(metadata.get("generation_gate", "unknown")),
                    "generated_utc": timestamp,
                    "producer": str(metadata.get("producer", "unknown")),
                }
            )
            continue
        if path.is_symlink():
            errors.append(f"evidence path is a symbolic link: {relative}")
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": candidate.as_posix(),
                "type": str(metadata.get("type", "unknown")),
                "required": required,
                "status": "present",
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "generation_gate": str(metadata.get("generation_gate", "unknown")),
                "generated_utc": timestamp,
                "producer": str(metadata.get("producer", "unknown")),
            }
        )
    payload = {"schema_version": "1.0", "generated_utc": timestamp, "evidence": records}
    return {
        **payload,
        "manifest_sha256": hashlib.sha256(canonical_bytes(payload)).hexdigest(),
        "valid": not errors,
        "errors": errors,
    }


def verify_evidence_manifest(
    evidence_root: Path, manifest: Mapping[str, object]
) -> dict[str, Any]:
    root = evidence_root.resolve(strict=True)
    errors: list[str] = []
    unsigned = {
        key: manifest[key]
        for key in ("schema_version", "generated_utc", "evidence")
        if key in manifest
    }
    expected = hashlib.sha256(canonical_bytes(unsigned)).hexdigest()
    if manifest.get("manifest_sha256") != expected:
        errors.append("evidence manifest digest mismatch")
    records = manifest.get("evidence")
    if not isinstance(records, list):
        return {
            "valid": False,
            "errors": [*errors, "evidence manifest records are malformed"],
        }
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, Mapping):
            errors.append("evidence manifest record is malformed")
            continue
        relative = str(record.get("path", ""))
        candidate = Path(relative)
        if (
            not relative
            or candidate.is_absolute()
            or ".." in candidate.parts
            or relative in seen
        ):
            errors.append(f"invalid or duplicate evidence path: {relative}")
            continue
        seen.add(relative)
        path = (root / candidate).resolve(strict=False)
        if not _inside(path, root):
            errors.append(f"evidence path escapes release root: {relative}")
            continue
        if record.get("status") == "missing" and record.get("required") is not True:
            continue
        if not path.is_file() or path.is_symlink():
            errors.append(f"evidence file is missing or unsafe: {relative}")
            continue
        data = path.read_bytes()
        if len(data) != record.get("size_bytes") or hashlib.sha256(
            data
        ).hexdigest() != record.get("sha256"):
            errors.append(f"evidence file bytes changed: {relative}")
    return {"valid": not errors, "record_count": len(records), "errors": errors}
