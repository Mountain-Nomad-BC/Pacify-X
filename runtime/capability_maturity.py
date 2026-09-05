"""Evidence-derived capability maturity from L0 through L6."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence_claims import AUTHORITY_CLASSES


SCHEMA_VERSION = "px.capability-maturity-policy/1.0"
LEVELS = tuple(f"L{index}" for index in range(7))
AUTHORITY_RANK = {"contained": 0, "installed_host": 1, "external_authority": 2}


def load_maturity_policy(root: Path) -> dict[str, Any]:
    payload = json.loads(
        (root.resolve() / "registry/capability_maturity_policy.json").read_text(
            encoding="utf-8"
        )
    )
    if not isinstance(payload, dict):
        raise ValueError("capability maturity policy must be an object")
    return payload


def validate_maturity_policy(policy: Mapping[str, object]) -> dict[str, object]:
    errors: list[str] = []
    if policy.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    requirements = policy.get("levels")
    if not isinstance(requirements, list):
        requirements = []
        errors.append("levels must be a list")
    observed_levels: list[str] = []
    evidence_types: set[str] = set()
    previous_authority = -1
    for index, record in enumerate(requirements):
        label = f"levels[{index}]"
        if not isinstance(record, Mapping):
            errors.append(f"{label} must be an object")
            continue
        level = str(record.get("level") or "")
        observed_levels.append(level)
        evidence_type = str(record.get("required_evidence_type") or "")
        if not evidence_type or evidence_type in evidence_types:
            errors.append(f"{label} required_evidence_type must be non-empty and unique")
        evidence_types.add(evidence_type)
        authority = str(record.get("required_authority_class") or "")
        if authority not in AUTHORITY_CLASSES:
            errors.append(f"{label} authority class is invalid")
            continue
        rank = AUTHORITY_RANK[authority]
        if rank < previous_authority:
            errors.append(f"{label} authority cannot be weaker than the previous level")
        previous_authority = rank
        if not record.get("name"):
            errors.append(f"{label} name is required")
    if tuple(observed_levels) != LEVELS:
        errors.append(f"levels must be exactly {list(LEVELS)}")
    if policy.get("level_count") != len(requirements):
        errors.append("level_count does not match levels")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "level_count": len(requirements),
        "errors": errors,
    }


def _revision_map(value: object) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    result = {str(key): str(revision) for key, revision in value.items()}
    return dict(sorted(result.items()))


def evaluate_capability_maturity(
    capability: Mapping[str, object],
    *,
    current_source_revision: str,
    current_dependency_revisions: Mapping[str, object],
    policy: Mapping[str, object],
) -> dict[str, object]:
    """Return the highest contiguous maturity level supported by current evidence."""
    policy_report = validate_maturity_policy(policy)
    if not policy_report["valid"]:
        raise ValueError("invalid maturity policy: " + "; ".join(policy_report["errors"]))
    capability_id = str(capability.get("capability_id") or "")
    if not capability_id:
        raise ValueError("capability_id is required")
    evidence = capability.get("evidence")
    rows: Sequence[object] = evidence if isinstance(evidence, list) else ()
    expected_dependencies = _revision_map(current_dependency_revisions) or {}
    current_by_type: dict[str, list[Mapping[str, object]]] = {}
    stale_types: set[str] = set()
    invalid_types: set[str] = set()
    for item in rows:
        if not isinstance(item, Mapping):
            continue
        evidence_type = str(item.get("evidence_type") or "")
        if not evidence_type:
            continue
        authority = str(item.get("authority_class") or "")
        dependencies = _revision_map(item.get("dependency_revisions"))
        current = (
            item.get("valid") is True
            and str(item.get("source_revision") or "") == current_source_revision
            and dependencies == expected_dependencies
        )
        if not current:
            stale_types.add(evidence_type)
            continue
        if authority not in AUTHORITY_RANK:
            invalid_types.add(evidence_type)
            continue
        current_by_type.setdefault(evidence_type, []).append(item)

    achieved: list[str] = []
    used_evidence: list[str] = []
    missing: list[str] = []
    reasons: list[str] = []
    level_name: str | None = None
    for requirement in policy["levels"]:  # type: ignore[index]
        level = str(requirement["level"])
        evidence_type = str(requirement["required_evidence_type"])
        minimum = AUTHORITY_RANK[str(requirement["required_authority_class"])]
        candidates = [
            item
            for item in current_by_type.get(evidence_type, ())
            if AUTHORITY_RANK[str(item["authority_class"])] >= minimum
        ]
        if not candidates:
            missing.append(evidence_type)
            reason = (
                f"stale_evidence:{evidence_type}"
                if evidence_type in stale_types
                else f"invalid_authority:{evidence_type}"
                if evidence_type in invalid_types or current_by_type.get(evidence_type)
                else f"missing_evidence:{evidence_type}"
            )
            reasons.append(reason)
            break
        achieved.append(level)
        level_name = str(requirement["name"])
        selected = sorted(candidates, key=lambda item: str(item.get("evidence_id") or ""))[0]
        used_evidence.append(str(selected.get("evidence_id") or evidence_type))

    level = achieved[-1] if achieved else None
    if level != "L6" and any(
        str(item.get("evidence_type")) == "external_certification"
        and str(item.get("authority_class")) != "external_authority"
        for item in rows
        if isinstance(item, Mapping)
    ):
        reasons.append("external_certification_requires_external_authority")
    return {
        "schema_version": "px.capability-maturity-decision/1.0",
        "capability_id": capability_id,
        "level": level,
        "level_name": level_name,
        "verified": level is not None,
        "complete": level == "L6",
        "achieved_levels": achieved,
        "evidence_ids": used_evidence,
        "missing_evidence": missing,
        "reasons": sorted(set(reasons)),
        "source_revision": current_source_revision,
        "dependency_revisions": expected_dependencies,
    }
