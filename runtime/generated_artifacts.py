"""Deterministic generated-output reconciliation without tree mutation."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def validate_generated_artifacts(root: Path) -> dict[str, Any]:
    from .artifact_reachability import build_artifact_reachability
    from .effect_surface import discover_effect_surfaces
    from .evidence_portability import discover_historical_references
    from .graph_registry import validate_graph_artifacts
    from .build_claims import validate_build_claims
    from .generated_dependency import generated_dependency_graph
    import json

    root = root.resolve()
    studio_owner = root / "registry/studio_operations.json"
    studio_projections = (
        root / "runtime/studio_operations.json",
        root / "extension/resources/studio-operations.json",
    )
    studio_projection_check = {
        "valid": studio_owner.is_file()
        and all(
            target.is_file() and target.read_bytes() == studio_owner.read_bytes()
            for target in studio_projections
        )
    }
    source_checkout = (root / "pyproject.toml").is_file() and (
        root / "scripts"
    ).is_dir()
    if not source_checkout:
        domain_owner = root / "templates/generated/domain_tool.py"
        domain_targets = sorted((root / ".px/skills").glob("*/scripts/domain_tool.py"))
        template_owner = root / "templates/declared_suite/authoritative-pack"
        template_targets = sorted(
            (root / "templates/declared_suite").glob("pack-*.json")
        )
        profile_owner = root / "bootstrap/profiles"
        profile_target = root / ".engineering-bootstrap/profiles"
        checks = {
            "domain_wrappers": {
                "valid": domain_owner.is_file()
                and len(domain_targets) == 7
                and all(
                    path.read_bytes() == domain_owner.read_bytes()
                    for path in domain_targets
                )
            },
            "declared_suite_templates": {
                "valid": len(template_targets) == 21
                and all(
                    path.read_bytes()
                    == (template_owner / path.name.split("-", 2)[2]).read_bytes()
                    for path in template_targets
                )
            },
            "profile_projections": {
                "valid": all(
                    (profile_target / path.name).is_file()
                    and (profile_target / path.name).read_bytes() == path.read_bytes()
                    for path in profile_owner.glob("*.toml")
                )
            },
            "graphs": validate_graph_artifacts(root),
            "studio_operation_projections": studio_projection_check,
        }
        failed = [name for name, result in checks.items() if not result["valid"]]
        return {
            "schema_version": "1.0",
            "valid": not failed,
            "check_count": len(checks),
            "failed": failed,
            "checks": checks,
            "mode": "installed_projection_validation",
        }
    from scripts.build_declared_suite_template_projections import reconcile as templates
    from scripts.build_domain_tool_projections import reconcile as wrappers
    from scripts.build_profile_projections import reconcile as profiles
    from scripts.build_registry_envelope_inventory import build_inventory
    from scripts.reconcile_commissioned_skill_registry import (
        reconcile as commissioned_skills,
    )
    from scripts.reconcile_declared_tool_hashes import expected as declared_tool_outputs
    from scripts.build_contract_ownership_registry import build as contract_ownership
    from scripts.build_python_dependency_ownership import build as dependency_ownership

    checks = {
        "domain_wrappers": wrappers(root, check=True),
        "declared_suite_templates": templates(root, check=True),
        "profile_projections": profiles(root, check=True),
        "commissioned_skill_registry": commissioned_skills(root, check=True),
        "build_claims": validate_build_claims(root),
        "studio_operation_projections": studio_projection_check,
    }
    inventory = root / "registry/registry_envelope_inventory.json"
    expected = json.dumps(build_inventory(), indent=2, sort_keys=True) + "\n"
    checks["registry_envelope_inventory"] = {
        "valid": inventory.is_file()
        and inventory.read_text(encoding="utf-8") == expected
    }
    reachability = root / "registry/artifact_reachability.json"
    checks["artifact_reachability"] = {
        "valid": reachability.is_file()
        and json.loads(reachability.read_text(encoding="utf-8"))
        == build_artifact_reachability(root)
    }
    effects = root / "registry/effect_surface_ownership.json"
    checks["effect_surface_ownership"] = {
        "valid": effects.is_file()
        and json.loads(effects.read_text(encoding="utf-8")).get("records")
        == discover_effect_surfaces(root)
    }
    portability = root / "registry/historical_external_references.json"
    checks["historical_external_references"] = {
        "valid": portability.is_file()
        and json.loads(portability.read_text(encoding="utf-8")).get("records")
        == discover_historical_references(root)
    }
    ownership = root / "registry/contract_ownership.json"
    checks["contract_ownership"] = {
        "valid": ownership.is_file()
        and json.loads(ownership.read_text(encoding="utf-8"))
        == contract_ownership(root)
    }
    dependencies = root / "registry/python_dependency_ownership.json"
    checks["dependency_ownership"] = {
        "valid": dependencies.is_file()
        and json.loads(dependencies.read_text(encoding="utf-8"))
        == dependency_ownership(root)
    }
    declared = declared_tool_outputs(root)
    checks["declared_tool_hashes"] = {
        "valid": all(
            (root / relative).is_file() and (root / relative).read_bytes() == payload
            for relative, payload in declared.items()
        )
    }
    checks["graphs"] = validate_graph_artifacts(root)
    dependency_graph = root / "registry/generated_dependency_graph.json"
    preflight_policy = json.loads(
        (root / "policies/release-preflight.json").read_text(encoding="utf-8")
    )
    checks["generated_dependency_graph"] = {
        "valid": dependency_graph.is_file()
        and json.loads(dependency_graph.read_text(encoding="utf-8"))
        == generated_dependency_graph(preflight_policy["generated_authorities"])
    }
    failed = [name for name, result in checks.items() if not result["valid"]]
    return {
        "schema_version": "1.0",
        "valid": not failed,
        "check_count": len(checks),
        "failed": failed,
        "checks": checks,
    }
