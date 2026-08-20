"""Authoritative structural audit composed from live framework validators."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tomllib
from typing import Any

from .contracts import validate_contract_corpus
from .graph_registry import validate_graph_artifacts
from .integration_registry import validate_integrations
from .registry import validate_registry
from .external_evidence import validate_external_evidence
from .generated_artifacts import validate_generated_artifacts
from .registry_envelope import validate_registry_envelopes
from .dependency_audit import validate_dependency_closure
from .release_artifacts import classify_tree
from .structural_integrity import audit_structural_integrity
from .effect_surface import validate_effect_surfaces
from .evidence_portability import validate_evidence_portability
from .licensing import validate_licensing
from .bounded_walk import WalkLimits, bounded_walk
from .repository_scope import is_external_environment_relative, is_project_source


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_framework(
    root: Path, *, require_external_manifests: bool = False
) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []

    def check(
        identifier: str, passed: bool, detail: str, evidence: list[str] | None = None
    ) -> None:
        checks.append(
            {
                "id": identifier,
                "passed": bool(passed),
                "detail": detail,
                "evidence": evidence or [],
            }
        )

    registry = validate_registry(root)
    check(
        "registry",
        registry["valid"],
        f"active capabilities={registry['active_count']}; errors={len(registry['errors'])}",
        ["registry/capability_map.json", "registry/admission_ledger.json"],
    )
    contracts = validate_contract_corpus(root)
    check(
        "contracts",
        contracts["valid"],
        f"owned={contracts['owned_count']}/{contracts['contract_count']}",
        ["registry/contract_ownership.json"],
    )
    integrations = validate_integrations(root, smoke=True)
    check(
        "integrations",
        integrations["valid"],
        f"active={integrations['active_count']}; smoke={integrations['smoke_tested']}",
        ["registry/integrations.json"],
    )
    graphs = validate_graph_artifacts(root)
    check(
        "graphs",
        graphs["valid"],
        f"fresh deterministic artifacts={graphs['artifact_count']}",
        ["registry/graphs/graph_manifest.json"],
    )
    generated_outputs = validate_generated_artifacts(root)
    check(
        "generated-projections",
        generated_outputs["valid"],
        f"projection families={len(generated_outputs.get('checks', {}))}",
        ["templates/generated/domain_tool.py"],
    )
    envelopes = validate_registry_envelopes(root)
    check(
        "registry-envelopes",
        envelopes["valid"],
        f"owned count fields={envelopes.get('record_count', 0)}",
        ["registry/registry_envelope_inventory.json"],
    )
    dependencies = validate_dependency_closure(root)
    check(
        "dependency-closure",
        dependencies["valid"],
        f"mapped modules={dependencies.get('module_count', 0)}",
        ["registry/python_dependency_ownership.json", "requirements-release.lock"],
    )
    artifacts = classify_tree(root)
    check(
        "release-artifact-classification",
        artifacts["valid"],
        f"files={artifacts['file_count']}; classes={artifacts['counts']}; errors={artifacts['errors']}",
        ["policies/release-artifact-policy.json"],
    )
    structural = audit_structural_integrity(root)
    check(
        "structural-integrity",
        structural["valid"],
        f"categories={structural['category_count']}; reachability={structural['reachability_records']}",
        [
            "registry/artifact_reachability.json",
            "registry/structural_integrity_policy.json",
        ],
    )
    effects = validate_effect_surfaces(root)
    check(
        "effect-surface-ownership",
        effects["valid"],
        f"owned effects={effects['record_count']}; classes={effects['counts']}",
        ["registry/effect_surface_ownership.json"],
    )
    portability = validate_evidence_portability(root)
    check(
        "evidence-portability",
        portability["valid"],
        f"historical external locators dispositioned={portability['reference_count']}",
        ["registry/historical_external_references.json"],
    )
    licensing = validate_licensing(root)
    check(
        "licensing",
        licensing["valid"],
        f"license={licensing['license']}; checked={licensing['checked_file_count']}; errors={len(licensing['errors'])}",
        [
            "LICENSE",
            "NOTICE",
            "pyproject.toml",
            "evidence/licensing-consistency-report.json",
        ],
    )

    catalog = tomllib.loads(
        (root / "registry/skill_catalog.toml").read_text(encoding="utf-8")
    )
    catalog_ids = {str(item["id"]) for item in catalog.get("skills", ())}
    skill_root = root / ".px" / "skills"
    directory_ids = {path.name for path in skill_root.iterdir() if path.is_dir()}
    missing_skill_files = sorted(
        identifier
        for identifier in directory_ids
        if not (skill_root / identifier / "SKILL.md").is_file()
        or not (skill_root / identifier / "agents/openai.yaml").is_file()
    )
    check(
        "skill-topology",
        catalog_ids == directory_ids and not missing_skill_files,
        f"catalog={len(catalog_ids)}; directories={len(directory_ids)}; incomplete={missing_skill_files}",
        ["registry/skill_catalog.toml", ".px/skills"],
    )
    active = {
        str(item["id"])
        for item in catalog.get("skills", ())
        if item.get("status") in {"active", "admitted"}
    }
    deferred = catalog_ids - active
    check(
        "skill-lifecycle",
        bool(active) and not (active & deferred),
        f"selectable={len(active)}; inert={len(deferred)}",
        ["registry/skill_catalog.toml", "registry/admission_ledger.json"],
    )

    policy_index = _json(root / "policies/policy_index.json")
    missing_policies = [
        str(item.get("body"))
        for item in policy_index.get("policies", ())
        if not (root / str(item.get("body"))).is_file()
    ]
    check(
        "policies",
        not missing_policies,
        f"indexed={len(policy_index.get('policies', ()))}; missing={missing_policies}",
        ["policies/policy_index.json"],
    )
    workflows = _json(root / "registry/project_stream_orchestrations.json")
    workflow_files = {
        path.stem
        for path in (root / "orchestration/workflows/project_stream").glob("*.yaml")
    }
    workflow_ids = {
        str(item["orchestration_id"]) for item in workflows.get("orchestrations", ())
    }
    check(
        "workflow-topology",
        workflow_files == workflow_ids and workflows.get("count") == len(workflow_ids),
        f"registry={len(workflow_ids)}; definitions={len(workflow_files)}",
        [
            "registry/project_stream_orchestrations.json",
            "orchestration/workflows/project_stream",
        ],
    )

    model_files = (
        "index.json",
        "routing-policy.json",
        "provider-adapters.json",
        "benchmark-policy.json",
    )
    missing_models = [
        name for name in model_files if not (root / "models" / name).is_file()
    ]
    check(
        "model-routing",
        not missing_models,
        f"configuration files={len(model_files) - len(missing_models)}/{len(model_files)}; weights bundled=false",
        ["models/index.json"],
    )
    prompts = (
        root / "bootstrap/prompts/NEW_PROJECT_PROMPT.md",
        root / "bootstrap/prompts/EXISTING_PROJECT_PROMPT.md",
    )
    check(
        "commissioning-prompts",
        all(path.is_file() for path in prompts),
        "new and existing project entry prompts",
        [path.relative_to(root).as_posix() for path in prompts],
    )
    source_tree = (root / "pyproject.toml").is_file()
    management_present = (root / "PROJECT_MANAGEMENT.md").is_file() and (
        root / ".engineering-bootstrap/project-management/state.json"
    ).is_file()
    check(
        "project-management",
        management_present if source_tree else True,
        "single build control point plus machine state"
        if source_tree
        else "installed data root: build-time management state is intentionally excluded",
        [
            "PROJECT_MANAGEMENT.md",
            ".engineering-bootstrap/project-management/state.json",
        ]
        if source_tree
        else [],
    )

    forbidden_roots = [
        name
        for name in ("planning", "quarantine", "integrations")
        if (root / name).exists()
    ]
    forbidden_roots.extend(
        name
        for name in (
            "knowledge/bootstrap_source_notes",
            "knowledge/research_operations",
            "knowledge/project_stream_reference",
        )
        if (root / name).exists()
    )
    check(
        "deploy-layout",
        not forbidden_roots,
        f"forbidden duplicate/raw roots={forbidden_roots}",
        ["evidence/externalized-payload-index.json"],
    )

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        config = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        data_files = config.get("tool", {}).get("setuptools", {}).get("data-files", {})
        packaged_skills = {
            key.split(".px/skills/", 1)[1].split("/", 1)[0]
            for key in data_files
            if ".px/skills/" in key
        }
        check(
            "package-skill-topology",
            packaged_skills == catalog_ids,
            f"packaged={len(packaged_skills)}; catalog={len(catalog_ids)}",
            ["pyproject.toml"],
        )
    else:
        check(
            "package-skill-topology",
            True,
            "installed data root: source packaging manifest not present",
            [],
        )

    external = validate_external_evidence(root, strict=require_external_manifests)
    check(
        "external-evidence",
        external["valid"],
        f"verified manifests={external['verified']}; strict={require_external_manifests}; errors={external['errors']}",
        ["evidence/externalized-payload-index.json"],
    )

    generated_directory_names = {
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
    }
    quarantine_prefix = (".engineering-bootstrap", "quarantine")
    audit_walk = bounded_walk(
        root,
        limits=WalkLimits(max_files=100_000, max_depth=128, max_bytes=2 * 1024**3),
        symlink_policy="skip",
        exclude=lambda relative: is_external_environment_relative(relative)
        or Path(relative).parts[:2] == quarantine_prefix,
    )
    generated = sorted(
        entry.relative
        for entry in audit_walk.entries
        for path in (entry.path,)
        if (
            any(
                part in generated_directory_names
                for part in path.relative_to(root).parts
            )
            or path.name.endswith(".egg-info")
            or path.suffix.casefold() in {".pyc", ".pyo"}
        )
    )
    generated = [
        relative
        for relative in generated
        if not relative.startswith("extension/dist")
    ]
    generated_evidence: list[str] = []
    # A raw prefix can be monopolized by one large generated tree (for example,
    # a release-output directory) and hide a different violation entirely.
    # Retain one deterministic witness for every governed artifact class before
    # filling the bounded evidence payload with the ordinary sorted remainder.
    for marker in sorted(generated_directory_names):
        witness = next(
            (
                relative
                for relative in generated
                if marker in Path(relative).parts
            ),
            None,
        )
        if witness is not None and witness not in generated_evidence:
            generated_evidence.append(witness)
    for predicate in (
        lambda path: path.name.endswith(".egg-info"),
        lambda path: path.suffix.casefold() in {".pyc", ".pyo"},
    ):
        witness = next(
            (relative for relative in generated if predicate(Path(relative))), None
        )
        if witness is not None and witness not in generated_evidence:
            generated_evidence.append(witness)
    generated_evidence.extend(
        relative
        for relative in generated
        if relative not in generated_evidence
    )
    check(
        "generated-artifact-hygiene",
        not generated,
        f"active generated artifacts={len(generated)}",
        generated_evidence[:20],
    )

    ownership_path = root / "registry/python_surface_ownership.json"
    ownership_errors: list[str] = []
    mapped_count = 0
    if ownership_path.is_file():
        ownership = _json(ownership_path)
        mapped = {
            str(record.get("path")): record for record in ownership.get("records", ())
        }
        python_paths = {
            entry.relative: entry.path
            for entry in audit_walk.files
            for path in (entry.path,)
            if path.suffix.casefold() == ".py"
            and is_project_source(path, root)
            and "__pycache__" not in path.parts
            and path.relative_to(root).parts[:2] != quarantine_prefix
        }
        mapped_count = len(mapped)
        for relative, path in python_paths.items():
            record = mapped.get(relative)
            if record is None:
                ownership_errors.append(f"unmapped: {relative}")
            elif hashlib.sha256(path.read_bytes()).hexdigest() != record.get("sha256"):
                ownership_errors.append(f"hash mismatch: {relative}")
        ownership_errors.extend(
            f"missing: {relative}"
            for relative in sorted(set(mapped) - set(python_paths))
        )
    else:
        ownership_errors.append("missing registry/python_surface_ownership.json")
    check(
        "python-surface-ownership",
        not ownership_errors,
        f"mapped={mapped_count}; errors={len(ownership_errors)}",
        ["registry/python_surface_ownership.json", *ownership_errors[:20]],
    )

    failed = [item for item in checks if not item["passed"]]
    return {
        "schema_version": "1.0",
        "valid": not failed,
        "check_count": len(checks),
        "passed": len(checks) - len(failed),
        "failed": len(failed),
        "checks": checks,
    }
