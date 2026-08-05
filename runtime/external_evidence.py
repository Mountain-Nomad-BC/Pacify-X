"""Portable, content-addressed external-evidence reference validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import validate_instance


def validate_external_evidence(
    root: Path, *, strict: bool = False, evidence_root: Path | None = None
) -> dict[str, Any]:
    root = root.resolve()
    index_path = root / "evidence/externalized-payload-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    errors = []
    verified = 0
    schema = root / "contracts/evidence-reference.schema.json"
    for record in index.get("records", []):
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
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "references": len(index.get("records", [])),
        "verified": verified,
        "strict": strict,
        "errors": errors,
    }
