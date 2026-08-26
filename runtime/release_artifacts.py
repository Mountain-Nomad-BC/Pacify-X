"""Classify release artifacts and compute deterministic product/harness digests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .bounded_walk import FilesystemWalkError, WalkLimits, bounded_walk
from .repository_scope import is_external_environment_relative


def _load_policy(root: Path) -> dict[str, Any]:
    return json.loads(
        (root / "policies/release-artifact-policy.json").read_text(encoding="utf-8")
    )


def _canonical_digest(records: list[dict[str, Any]]) -> str:
    payload = b"".join(
        (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        for record in records
    )
    return hashlib.sha256(payload).hexdigest()


def _is_release_walk_excluded(relative: str | Path) -> bool:
    """Prune external custody without hiding policy-governed evidence.

    The repository source boundary intentionally excludes evidence from normal
    source discovery.  Release classification has a different obligation: it
    must see evidence payloads so executable or unapproved files cannot hide in
    that namespace.  Evidence remains non-product and its content is not hashed.
    """
    path = Path(relative)
    if any(part.casefold() == "evidence" for part in path.parts):
        return False
    return is_external_environment_relative(path)


def classify_tree(root: Path) -> dict[str, Any]:
    root = root.resolve()
    policy = _load_policy(root)
    product_roots = {item.casefold() for item in policy["product_roots"]}
    product_files = {item.casefold() for item in policy["product_root_files"]}
    evidence_roots = {item.casefold() for item in policy["evidence_roots"]}
    audit_roots = {item.casefold() for item in policy.get("audit_roots", [])}
    audit_root_files = {item.casefold() for item in policy.get("audit_root_files", [])}
    audit_suffixes = {item.casefold() for item in policy.get("audit_allowed_suffixes", [])}
    intermediate_names = {item.casefold() for item in policy["intermediate_names"]}
    intermediate_name_suffixes = {
        item.casefold() for item in policy.get("intermediate_name_suffixes", [])
    }
    intermediate_suffixes = {
        item.casefold() for item in policy["intermediate_suffixes"]
    }
    control_outputs = {item.casefold() for item in policy["control_output_paths"]}
    evidence_suffixes = {
        item.casefold() for item in policy["evidence_allowed_suffixes"]
    }
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    product_errors: list[str] = []
    normalized_seen: dict[str, str] = {}
    try:
        walk = bounded_walk(
            root,
            limits=WalkLimits(
                max_files=250_000,
                max_depth=128,
                max_bytes=64 * 1024 * 1024 * 1024,
            ),
            symlink_policy="reject",
            exclude=_is_release_walk_excluded,
        )
    except FilesystemWalkError as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "product_valid": False,
            "policy_version": policy["policy_version"],
            "policy_sha256": hashlib.sha256(
                (root / "policies/release-artifact-policy.json").read_bytes()
            ).hexdigest(),
            "file_count": 0,
            "counts": {},
            "product_digest": _canonical_digest([]),
            "harness_digest": _canonical_digest([]),
            "product_records": [],
            "records": [],
            "errors": [f"bounded filesystem walk failed: {error.code}"],
        }
    for entry in walk.entries:
        relative = entry.relative
        normalized = relative.casefold()
        prior = normalized_seen.get(normalized)
        if prior is not None and prior != relative:
            collision = f"case-fold path collision: {prior} vs {relative}"
            errors.append(collision)
            product_errors.append(collision)
        normalized_seen[normalized] = relative
        if entry.kind == "file":
            path = entry.path
            parts = relative.split("/")
            folded_parts = [item.casefold() for item in parts]
            folded = relative.casefold()
            suffix = path.suffix.casefold()
            if (
                any(item in intermediate_names for item in folded_parts)
                or any(
                    item.endswith(ending)
                    for item in folded_parts
                    for ending in intermediate_name_suffixes
                )
                or suffix in intermediate_suffixes
            ):
                classification = "generated_intermediate"
                reason = "narrow generated-artifact exclusion"
            elif folded in control_outputs:
                classification = "control_output"
                reason = "recoverable release transaction control"
            elif any(part in evidence_roots for part in folded_parts):
                classification = "evidence_output"
                reason = "non-executable evidence namespace"
                if suffix not in evidence_suffixes:
                    errors.append(
                        f"executable or unapproved evidence payload: {relative}"
                    )
            elif folded_parts[0] in audit_roots or (len(parts) == 1 and folded in audit_root_files):
                classification = "audit_artifact"
                reason = "bounded final audit handoff surface"
                if suffix not in audit_suffixes:
                    errors.append(f"unapproved audit artifact payload: {relative}")
            elif folded_parts[0] in product_roots or (
                len(parts) == 1 and folded in product_files
            ):
                classification = "product_input"
                reason = "declared product surface"
            else:
                classification = "unclassified"
                reason = "no release policy rule"
                errors.append(f"unclassified release artifact: {relative}")
            if path.is_file():
                if classification in {"control_output", "evidence_output"}:
                    content_sha256 = None
                else:
                    try:
                        content_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
                    except OSError as error:
                        content_sha256 = None
                        unreadable = (
                            f"unreadable release artifact: {relative}: "
                            f"{type(error).__name__}"
                        )
                        errors.append(unreadable)
                        if classification == "product_input":
                            product_errors.append(unreadable)
                records.append(
                    {
                        "path": relative,
                        "classification": classification,
                        "reason": reason,
                        "size": entry.size,
                        "sha256": content_sha256,
                    }
                )
    records.sort(key=lambda item: item["path"].casefold())
    product_records = [
        {key: item[key] for key in ("path", "size", "sha256")}
        for item in records
        if item["classification"] == "product_input"
    ]
    harness_paths = {
        "runtime/release_artifacts.py",
        "runtime/release_certification.py",
        "runtime/release_audit.py",
        "runtime/structural_integrity.py",
        "runtime/exact_tool_certification.py",
        "policies/release-artifact-policy.json",
        "registry/test_profiles.json",
    }
    harness_records = [
        item
        for item in product_records
        if item["path"] in harness_paths
        or item["path"].startswith("tests/test_release")
        or item["path"].startswith("tests/test_structural")
    ]
    counts: dict[str, int] = {}
    for item in records:
        counts[item["classification"]] = counts.get(item["classification"], 0) + 1
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "product_valid": not product_errors,
        "policy_version": policy["policy_version"],
        "policy_sha256": hashlib.sha256(
            (root / "policies/release-artifact-policy.json").read_bytes()
        ).hexdigest(),
        "file_count": len(records),
        "counts": dict(sorted(counts.items())),
        "product_digest": _canonical_digest(product_records),
        "harness_digest": _canonical_digest(harness_records),
        "product_records": product_records,
        "records": records,
        "errors": errors,
    }


def verify_frozen_product(root: Path, frozen: dict[str, Any]) -> dict[str, Any]:
    current = classify_tree(root)
    errors = list(current["errors"])
    if current["product_digest"] != frozen.get("product_digest"):
        errors.append("product input digest changed after freeze")
    if current["harness_digest"] != frozen.get("harness_digest"):
        errors.append("certification harness digest changed after freeze")
    return {
        "valid": not errors,
        "product_digest": current["product_digest"],
        "harness_digest": current["harness_digest"],
        "errors": errors,
    }
