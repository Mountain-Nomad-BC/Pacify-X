"""Single stable-ID gate over Pacify-X architectural cohesion requirements."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping


INVARIANT_IDS = (
    "PX-ARCH-SEMANTIC-PROFILE",
    "PX-ARCH-PROJECTION-REVISION",
    "PX-ARCH-PRIMITIVE-OWNER",
    "PX-ARCH-DUPLICATE-EXCEPTION",
    "PX-ARCH-EVIDENCE-CLASS",
    "PX-ARCH-CONFORMANCE",
    "PX-ARCH-DEPENDENCY",
    "PX-ARCH-TASK-MODEL-BINDING",
    "PX-ARCH-RELEASE-IDENTITY",
    "PX-ARCH-PARENT-CHILD-NA",
    "PX-ARCH-PROJECTION-INVALIDATION",
    "PX-ARCH-MATURITY-EVIDENCE",
    "PX-ARCH-AUTHORITY-TOPOLOGY",
)


def architecture_invariant_report(checks: Mapping[str, bool]) -> dict[str, object]:
    unknown = sorted(set(checks) - set(INVARIANT_IDS))
    if unknown:
        raise ValueError("unknown architecture invariant: " + ",".join(unknown))
    failed = [item for item in INVARIANT_IDS if checks.get(item) is not True]
    return {
        "schema_version": "px.architecture-invariants/1.0",
        "valid": not failed,
        "failed_invariant_ids": failed,
        "results": {item: checks.get(item) is True for item in INVARIANT_IDS},
    }


def validate_architecture_invariants(root: Path) -> dict[str, object]:
    """Evaluate the complete current-tree invariant set without mutating it."""
    root = root.resolve(strict=True)
    from .authority_topology import validate_authority_topology
    from .capability_maturity import load_maturity_policy, validate_maturity_policy
    from .dependency_invalidation import validate_dependency_authority
    from .evidence_claims import evidence_type_compatible, load_evidence_type_policy
    from .primitive_authority import validate_primitive_authority
    from .primitive_lint import validate_primitive_exceptions
    from .projection_dependencies import revision_for_path

    def load(relative: str):
        try:
            return json.loads((root / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    semantic = load("registry/semantic_capability_index.json")
    profiles = semantic.get("records", ()) if isinstance(semantic, Mapping) else ()
    semantic_ok = bool(profiles) and all(
        isinstance(item, Mapping)
        and isinstance(item.get("semantic_profile"), Mapping)
        and bool(item["semantic_profile"].get("positive_intents"))
        for item in profiles
    )
    projection = load("registry/projection_dependencies.json")
    try:
        projection_ok = isinstance(projection, Mapping) and all(
            isinstance(item, Mapping)
            and bool(item.get("output_revision"))
            and revision_for_path(root, str(item.get("output")))
            == item.get("output_revision")
            and all(
                isinstance(dependency, Mapping)
                and revision_for_path(root, str(dependency.get("path")))
                == dependency.get("revision")
                for dependency in item.get("dependencies", ())
            )
            for item in projection.get("projections", ())
        )
    except (OSError, ValueError):
        projection_ok = False
    primitive = load("registry/primitive_authority.json")
    primitive_report = validate_primitive_authority(root)
    primitive_ok = primitive_report["valid"]
    duplicate_ok = (
        isinstance(primitive, Mapping)
        and validate_primitive_exceptions(primitive)["valid"]
    )
    try:
        load_evidence_type_policy(root)
        evidence_ok = (
            evidence_type_compatible(root, "runtime_effect", "feature.runtime_effect")
            and not evidence_type_compatible(root, "ui_interaction", "feature.runtime_effect")
        )
    except (OSError, ValueError, json.JSONDecodeError):
        evidence_ok = False
    conformance_ok = all(
        (root / path).is_file()
        for path in (
            "tests/coordination_conformance/coordination_state_conformance_vectors.json",
            "tests/coordination_conformance/provider_execution_policy_vectors.json",
        )
    )
    dependency = load("registry/dependency_authority.json")
    dependency_ok = (
        isinstance(dependency, Mapping)
        and validate_dependency_authority(root, dependency)["valid"]
    )
    release = load(".engineering-bootstrap/processing-order/release-identity.json")
    release_ok = not (
        isinstance(release, Mapping)
        and release.get("state") in {"active", "certified"}
        and isinstance(release.get("identity"), Mapping)
        and not release["identity"].get("source_product_digest")
    )
    invalidation_ok = isinstance(projection, Mapping) and all(
        isinstance(item, Mapping)
        and item.get("invalidation_rule") == "any_dependency_revision_change"
        and item.get("rebuild_gate") in {"rebuild_before_use", "block_until_rebuilt"}
        for item in projection.get("projections", ())
    )
    try:
        maturity = load_maturity_policy(root)
        maturity_ok = validate_maturity_policy(maturity)["valid"] and all(
            item.get("required_evidence_type")
            and item.get("required_authority_class") in {"installed_host", "external_authority"}
            for item in maturity.get("levels", ())
            if item.get("level") in {"L5", "L6"}
        )
    except (OSError, ValueError, json.JSONDecodeError):
        maturity_ok = False
    topology_ok = validate_authority_topology(root)["valid"]
    checks = {
        INVARIANT_IDS[0]: semantic_ok,
        INVARIANT_IDS[1]: projection_ok,
        INVARIANT_IDS[2]: primitive_ok,
        INVARIANT_IDS[3]: duplicate_ok,
        INVARIANT_IDS[4]: evidence_ok,
        INVARIANT_IDS[5]: conformance_ok,
        INVARIANT_IDS[6]: dependency_ok,
        INVARIANT_IDS[7]: all(
            (root / path).is_file()
            for path in (
                "contracts/task_execution_plan.schema.json",
                "contracts/model_attachment.schema.json",
            )
        ),
        INVARIANT_IDS[8]: release_ok,
        INVARIANT_IDS[9]: evidence_ok,
        INVARIANT_IDS[10]: invalidation_ok,
        INVARIANT_IDS[11]: maturity_ok,
        INVARIANT_IDS[12]: topology_ok,
    }
    return architecture_invariant_report(checks)
