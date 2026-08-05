"""Build the closed-world registry/workflow ownership and reachability inventory."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_artifact_reachability(root: Path) -> dict:
    root = root.resolve()
    binding_doc = _load(root / "registry/workflow_execution_bindings.json")
    bindings = {item["path"]: item for item in binding_doc["bindings"]}
    records = []
    recorded_paths: set[str] = set()

    def record(value: dict) -> None:
        path = str(value["path"])
        if path in recorded_paths:
            raise ValueError(f"duplicate artifact reachability record: {path}")
        recorded_paths.add(path)
        records.append(value)

    registry_owners = {
        "artifact_reachability.json": "runtime/artifact_reachability.py",
        "contract_ownership.json": "runtime/contracts.py",
        "corrective_release_ledger.json": "runtime/corrective_release.py",
        "declared_suite_authoritative_tools.json": "runtime/exact_tool_certification.py",
        "effect_surface_ownership.json": "runtime/effect_surface.py",
        "full_repair_ledger.json": "runtime/full_repair.py",
        "integrations.json": "runtime/integration_registry.py",
        "project_stream_handlers.json": "runtime/project_stream_orchestrator.py",
        "project_stream_orchestrations.json": "runtime/project_stream_orchestrator.py",
        "python_surface_ownership.json": "runtime/python_surface_certification.py",
        "registry_envelope_inventory.json": "runtime/registry_envelope.py",
        "semantic_capability_index.json": "runtime/semantic_index.py",
        "skill_catalog.toml": "runtime/registry.py",
        "skill_orchestrations.json": "runtime/skill_navigator.py",
        "test_profiles.json": "runtime/test_profiles.py",
        "workflow_execution_bindings.json": "runtime/structural_integrity.py",
    }
    for path in sorted(
        (root / "registry").rglob("*"), key=lambda item: item.as_posix().casefold()
    ):
        if (
            not path.is_file()
            or path.name == "artifact_reachability.json"
            or path.suffix.casefold() not in {".json", ".toml", ".yaml", ".yml"}
        ):
            continue
        relative = path.relative_to(root).as_posix()
        owner = registry_owners.get(path.name, "runtime/structural_integrity.py")
        record(
            {
                "path": relative,
                "sha256": _sha(path),
                "kind": "registry",
                "owner": owner,
                "reachability": "release_validated",
            }
        )
    project_stream = _load(root / "registry/project_stream_handlers.json")
    project_bindings = {
        item["orchestration_id"]: item for item in project_stream["workflows"]
    }
    for path in sorted(
        (root / "orchestration/workflows").rglob("*.yaml"),
        key=lambda item: item.as_posix().casefold(),
    ):
        relative = path.relative_to(root).as_posix()
        if "project_stream" in path.parts:
            binding = project_bindings.get(path.stem)
            if binding is None:
                entrypoint, mode = "", "unbound"
            else:
                dotted = str(binding["handler"])
                module, attribute = dotted.rsplit(".", 1)
                entrypoint, mode = f"{module}:{attribute}", str(binding["status"])
        else:
            binding = bindings.get(relative, {})
            entrypoint, mode = (
                str(binding.get("entrypoint", "")),
                str(binding.get("mode", "unbound")),
            )
        record(
            {
                "path": relative,
                "sha256": _sha(path),
                "kind": "orchestration",
                "owner": "runtime/structural_integrity.py",
                "reachability": mode,
                "entrypoint": entrypoint,
            }
        )

    provider_root = root / "providers" / "agency_agents"
    if provider_root.is_dir():
        for path in sorted(
            provider_root.rglob("*"), key=lambda item: item.as_posix().casefold()
        ):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            if "/agents/" in f"/{relative}":
                reachability = "lazy_selected_agent_body"
            elif "/manifests/" in f"/{relative}":
                reachability = "lazy_selected_agent_manifest"
            else:
                reachability = "provider_license"
            record(
                {
                    "path": relative,
                    "sha256": _sha(path),
                    "kind": "provider_asset",
                    "owner": "runtime/agent_provider.py",
                    "reachability": reachability,
                }
            )

    # YAML is executable configuration or a user-facing template. Every YAML
    # file therefore needs an explicit owner even when it is not an orchestration.
    yaml_paths = {*root.rglob("*.yaml"), *root.rglob("*.yml")}
    for path in sorted(yaml_paths, key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        if relative in recorded_paths:
            continue
        if relative.startswith(".agents/skills/") and relative.endswith(
            "/agents/openai.yaml"
        ):
            skill_id = relative.split("/")[2]
            owner = f".agents/skills/{skill_id}/SKILL.md"
            reachability = "lazy_skill_interface"
        elif (
            relative
            == "bootstrap/commissioning/reference/questionnaire_answers.template.yaml"
        ):
            owner = "bootstrap/commissioning/reference/README_START_HERE.md"
            reachability = "documented_commissioning_template"
        elif relative.startswith("templates/project_stream/"):
            owner = "runtime/project_control_plane.py"
            reachability = "runtime_validated_template"
        else:
            owner = "runtime/structural_integrity.py"
            reachability = "unclassified_yaml"
        record(
            {
                "path": relative,
                "sha256": _sha(path),
                "kind": "yaml",
                "owner": owner,
                "reachability": reachability,
            }
        )
    return {"schema_version": "1.0", "record_count": len(records), "records": records}
