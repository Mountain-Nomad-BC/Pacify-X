"""Portable, content-addressed external-evidence reference validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any

from .contracts import validate_instance


def validate_external_evidence(
    root: Path, *, strict: bool = False, evidence_root: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    index_path = root / "evidence/externalized-payload-index.json"
    if not index_path.is_file():
        errors = ["externalized payload index is missing"] if strict else []
        return {
            "schema_version": "1.0",
            "valid": not errors,
            "references": 0,
            "verified": 0,
            "strict": strict,
            "errors": errors,
        }
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "references": 0,
            "verified": 0,
            "strict": strict,
            "errors": [
                f"externalized payload index is unreadable: {type(error).__name__}"
            ],
        }
    errors = []
    verified = 0
    current_references = 0
    historical_references = 0
    schema = root / "contracts/evidence-reference.schema.json"
    records = index.get("records", [])
    if not isinstance(records, list):
        records = []
        errors.append("externalized payload records must be a list")
    seen_ids: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            errors.append("externalized payload record must be an object")
            continue
        reference_id = record.get("reference_id")
        if not isinstance(reference_id, str) or not reference_id or reference_id in seen_ids:
            errors.append("externalized payload reference ID is missing or repeated")
            continue
        seen_ids.add(reference_id)
        if record.get("availability") == "external_custody":
            historical_references += 1
            allowed = {"reference_id", "required_for", "availability", "custody_root",
                       "custody_relative_path", "restoration_manifest", "path", "sha256",
                       "retention", "verification_mode", "runtime_required"}
            relative = record.get("custody_relative_path")
            product_path = record.get("path")
            if (
                set(record) != allowed
                or record.get("required_for") != ["historical_corrective_release_evidence"]
                or record.get("runtime_required") is not False
                or record.get("verification_mode") != "external_custody_sha256"
                or not isinstance(record.get("custody_root"), str)
                or not record["custody_root"]
                or not isinstance(record.get("retention"), str)
                or not record["retention"]
                or not isinstance(record.get("sha256"), str)
                or re.fullmatch(r"[a-f0-9]{64}", record["sha256"]) is None
                or not isinstance(relative, str)
                or not isinstance(product_path, str)
                or not isinstance(record.get("restoration_manifest"), str)
                or not record["restoration_manifest"]
                or "\\" in relative
                or "\\" in product_path
                or any(p.is_absolute() or ".." in p.parts or not p.parts
                       for p in (PurePosixPath(relative or "."), PurePosixPath(product_path or ".")))
                or not product_path.startswith("evidence/")
            ):
                errors.append(f"{reference_id}: invalid superseded historical custody declaration")
            continue
        current_references += 1
        try:
            validate_instance(record, schema)
        except (ValueError, OSError) as error:
            errors.append(f"{record.get('reference_id')}: invalid reference: {error}")
            continue
        relative = Path(str(record["manifest"]))
        if relative.is_absolute() or ".." in relative.parts:
            errors.append(
                f"{record['reference_id']}: manifest path must be product-relative and traversal-free"
            )
            continue
        base = evidence_root.resolve() if evidence_root else root
        manifest_path = (base / relative).resolve()
        if base not in manifest_path.parents:
            errors.append(f"{record['reference_id']}: manifest escapes evidence root")
            continue
        if not manifest_path.is_file():
            if strict or record["availability"].startswith("bundled"):
                errors.append(f"{record['reference_id']}: required manifest is missing")
            continue
        actual = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        if actual != record["sha256"]:
            errors.append(f"{record['reference_id']}: manifest hash mismatch")
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        inventory_path = manifest_path.parent / str(manifest["inventory"])
        if (
            not inventory_path.is_file()
            or hashlib.sha256(inventory_path.read_bytes()).hexdigest()
            != manifest["inventory_sha256"]
        ):
            errors.append(
                f"{record['reference_id']}: bundled inventory is missing or mismatched"
            )
            continue
        if record["bundle_id"] != f"sha256:{manifest['inventory_sha256']}":
            errors.append(
                f"{record['reference_id']}: bundle ID does not bind the inventory"
            )
            continue
        verified += 1
    if index.get("schema_version") == "2.0" and index.get("superseded_record_count") != len(records):
        errors.append("superseded record count differs from the retained index")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "references": current_references,
        "superseded_references": historical_references,
        "verified": verified,
        "strict": strict,
        "errors": errors,
    }
