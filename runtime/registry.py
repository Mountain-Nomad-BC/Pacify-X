"""Canonical active-capability registry loading and validation."""
from __future__ import annotations

import json
from pathlib import Path
import re
import hashlib
import tomllib

from .config import load_startup_config
from .skill_navigator import CapabilitySummary
from .admission_controller import KNOWN_EFFECTS
from .graphs import validate_orchestration
from .system_graph import build_system_graph
from .contracts import validate_contract_corpus
from .source_coverage import validate_source_coverage
from .integration_registry import validate_integrations
from .graph_registry import validate_graph_artifacts
from .capability_assimilation import validate_capability_assimilation
from .semantic_index import load_semantic_index, validate_semantic_index
from .paths import declared_file_available, resolve_declared_path

CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_CONTRACT_FIELDS = {
    "id", "version", "owner", "status", "provenance", "hash", "license",
    "provides", "consumes", "effects", "permissions", "dependencies", "conflicts",
    "cost", "latency", "risk", "validation", "evidence", "approval", "rollback",
}
ALLOWED_CONTRACT_FIELDS = REQUIRED_CONTRACT_FIELDS
REQUIRED_MODEL_FIELDS = {
    "model_id", "runtime", "available", "context_tokens", "traits", "supports_tools",
    "privacy", "cost_class", "latency_class", "warm_cost", "cold_cost", "failure_modes",
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_skill_catalog(root: Path) -> dict:
    return tomllib.loads((root / "registry" / "skill_catalog.toml").read_text(encoding="utf-8"))


def validate_registry(root: Path) -> dict:
    try:
        config = load_startup_config(root / "bootstrap" / "startup.toml")
        capability_map = load_json(root / "registry" / "capability_map.json")
        ledger = load_json(root / "registry" / "admission_ledger.json")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {"valid": False, "active_count": 0, "errors": [f"configuration load failed: {error}"]}
    errors: list[str] = []
    seen: set[str] = set()
    contracts: dict[str, dict] = {}
    active = capability_map.get("active_capabilities", [])
    if not isinstance(active, list):
        return {"valid": False, "active_count": 0, "errors": ["active_capabilities must be a list"]}
    if len(active) > config.budget.max_initial_registry_records:
        errors.append("active registry exceeds initial record budget")
    ledger_status = {
        item.get("id"): item.get("status")
        for item in ledger.get("records", [])
        if isinstance(item, dict)
    }
    for item in active:
        if not isinstance(item, dict):
            errors.append("active capability entry must be an object")
            continue
        capability_id = item.get("id")
        if not isinstance(capability_id, str) or not CAPABILITY_ID.fullmatch(capability_id):
            errors.append(f"invalid capability id: {capability_id}")
            continue
        if capability_id in seen:
            errors.append(f"duplicate active capability: {capability_id}")
        seen.add(capability_id)
        if ledger_status.get(capability_id) != "active":
            errors.append(f"{capability_id}: missing active admission ledger record")
        for field in ("contract", "implementation", "evidence"):
            relative = str(item.get(field, ""))
            if not declared_file_available(root, relative):
                errors.append(f"{capability_id}: missing {field} {relative}")
        contract_path = resolve_declared_path(root, str(item.get("contract", "")))
        if contract_path is not None and contract_path.is_file():
            try:
                contract = load_json(contract_path)
            except (OSError, json.JSONDecodeError) as error:
                errors.append(f"{capability_id}: invalid contract JSON: {error}")
                continue
            missing = REQUIRED_CONTRACT_FIELDS - set(contract)
            extra = set(contract) - ALLOWED_CONTRACT_FIELDS
            if missing:
                errors.append(f"{capability_id}: missing contract fields: {', '.join(sorted(missing))}")
            if extra:
                errors.append(f"{capability_id}: unexpected contract fields: {', '.join(sorted(extra))}")
            if contract.get("id") != capability_id or contract.get("status") != "active":
                errors.append(f"{capability_id}: contract identity/status mismatch")
            if contract.get("version") != item.get("version"):
                errors.append(f"{capability_id}: version mismatch")
            if contract.get("effects") != item.get("effects"):
                errors.append(f"{capability_id}: effect declaration mismatch")
            for field in ("provides", "consumes", "effects", "permissions", "dependencies", "conflicts"):
                if not isinstance(contract.get(field), list) or not all(isinstance(value, str) for value in contract.get(field, [])):
                    errors.append(f"{capability_id}: contract {field} must be a string list")
            unknown_effects = set(contract.get("effects", ())) - KNOWN_EFFECTS
            if unknown_effects:
                errors.append(f"{capability_id}: unknown effects: {', '.join(sorted(unknown_effects))}")
            implementation_path = resolve_declared_path(root, str(item.get("implementation", "")))
            if implementation_path is not None and implementation_path.is_file():
                digest = hashlib.sha256(implementation_path.read_bytes()).hexdigest()
                if contract.get("hash") != digest:
                    errors.append(f"{capability_id}: implementation hash mismatch")
            if not isinstance(contract.get("provenance"), dict) or not contract.get("provenance"):
                errors.append(f"{capability_id}: provenance must be recorded")
            if not isinstance(contract.get("license"), str) or not contract.get("license", "").strip():
                errors.append(f"{capability_id}: license must be recorded")
            if contract.get("risk") not in {"R0", "R1", "R2", "R3", "R4"}:
                errors.append(f"{capability_id}: invalid risk class")
            for field in ("cost", "latency", "validation", "evidence", "approval", "rollback"):
                if not isinstance(contract.get(field), dict) or not contract.get(field):
                    errors.append(f"{capability_id}: {field} must be recorded")
            contracts[capability_id] = contract
    for capability_id, contract in contracts.items():
        unresolved = sorted(set(contract.get("dependencies", [])) - seen)
        if unresolved:
            errors.append(f"{capability_id}: unresolved dependencies: {', '.join(unresolved)}")
    visiting: set[str] = set()
    visited: set[str] = set()
    def visit(capability_id: str) -> None:
        if capability_id in visiting:
            errors.append(f"capability dependency cycle includes {capability_id}")
            return
        if capability_id in visited:
            return
        visiting.add(capability_id)
        for dependency in sorted(contracts.get(capability_id, {}).get("dependencies", ())):
            if dependency in contracts:
                visit(dependency)
        visiting.remove(capability_id)
        visited.add(capability_id)
    for capability_id in sorted(contracts):
        visit(capability_id)
    workflow_root = root / "registry" / "orchestrations"
    if workflow_root.is_dir():
        for workflow_path in sorted(workflow_root.glob("*.json")):
            try:
                workflow_errors = validate_orchestration(load_json(workflow_path), contracts.values())
            except (OSError, json.JSONDecodeError, ValueError) as error:
                errors.append(f"invalid orchestration {workflow_path.name}: {error}")
                continue
            errors.extend(f"{workflow_path.name}: {error}" for error in workflow_errors)
    model_path = root / "registry" / "models.json"
    if model_path.is_file():
        try:
            model_records = load_json(model_path).get("models", ())
        except (OSError, json.JSONDecodeError) as error:
            errors.append(f"invalid model registry: {error}")
            model_records = ()
        model_ids: set[str] = set()
        for model in model_records:
            if not isinstance(model, dict) or set(model) != REQUIRED_MODEL_FIELDS:
                errors.append("model registry record does not match model contract")
                continue
            model_id = model.get("model_id")
            if not isinstance(model_id, str) or not CAPABILITY_ID.fullmatch(model_id) or model_id in model_ids:
                errors.append(f"invalid or duplicate model id: {model_id}")
            model_ids.add(str(model_id))
            if not isinstance(model.get("available"), bool) or not isinstance(model.get("context_tokens"), int) or model.get("context_tokens", 0) < 1:
                errors.append(f"{model_id}: invalid availability/context metadata")
            if not isinstance(model.get("traits"), list) or not all(isinstance(value, str) for value in model.get("traits", ())):
                errors.append(f"{model_id}: invalid trait metadata")
    skill_catalog_path = root / "registry" / "skill_catalog.toml"
    if skill_catalog_path.is_file():
        try:
            skill_catalog = load_skill_catalog(root)
        except (OSError, tomllib.TOMLDecodeError) as error:
            errors.append(f"invalid skill catalog: {error}")
            skill_catalog = {"skills": []}
        skills = skill_catalog.get("skills", ())
        if skill_catalog.get("loading_rule") != "metadata_only_at_startup_body_after_selection":
            errors.append("skill catalog must require metadata-only startup")
        if skill_catalog.get("default_active_limit") != config.budget.max_active_capabilities:
            errors.append("skill catalog default limit differs from startup budget")
        skill_ids: set[str] = set()
        for skill in skills:
            if not isinstance(skill, dict):
                errors.append("skill catalog entry must be an object"); continue
            skill_id = skill.get("id")
            if not isinstance(skill_id, str) or not CAPABILITY_ID.fullmatch(skill_id) or skill_id in skill_ids:
                errors.append(f"invalid or duplicate skill id: {skill_id}")
            skill_ids.add(str(skill_id))
            skill_status = str(skill.get("status", "candidate"))
            if skill_status not in {"active", "admitted", "mapped_deferred", "candidate", "quarantined"}:
                errors.append(f"{skill_id}: invalid skill lifecycle state {skill_status}")
            for field in ("body", "contract"):
                relative = str(skill.get(field, ""))
                if not declared_file_available(root, relative):
                    errors.append(f"{skill_id}: missing skill {field}")
            admission_status = ledger_status.get(skill.get("admission_record"))
            if skill_status in {"active", "admitted"} and admission_status != "active":
                errors.append(f"{skill_id}: missing active skill admission record")
            if skill_status in {"mapped_deferred", "candidate", "quarantined"} and admission_status == "active":
                errors.append(f"{skill_id}: deferred skill has active admission record")
            contract_path = resolve_declared_path(root, str(skill.get("contract", "")))
            if contract_path is not None and "skill_packages" in contract_path.parts and contract_path.is_file():
                package = load_json(contract_path)
                body_path = resolve_declared_path(root, str(skill.get("body", "")))
                if package.get("id") != skill_id or package.get("status") != skill_status:
                    errors.append(f"{skill_id}: skill package identity/status mismatch")
                if body_path is not None and body_path.is_file() and package.get("body_sha256") != hashlib.sha256(body_path.read_bytes()).hexdigest():
                    errors.append(f"{skill_id}: skill body hash mismatch")
                for reference in package.get("references", ()):
                    if not declared_file_available(root, reference):
                        errors.append(f"{skill_id}: missing lazy reference {reference}")
                for resource in package.get("resources", ()):
                    if not declared_file_available(root, resource):
                        errors.append(f"{skill_id}: missing skill resource {resource}")
    try:
        build_system_graph(root)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        errors.append(f"invalid system asset graph: {error}")
    try:
        contract_result = validate_contract_corpus(root)
        errors.extend(f"contract corpus: {error}" for error in contract_result["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"contract corpus unavailable: {error}")
    try:
        coverage_result = validate_source_coverage(root)
        errors.extend(f"source coverage: {error}" for error in coverage_result["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        errors.append(f"source coverage unavailable: {error}")
    try:
        integration_result = validate_integrations(root)
        errors.extend(f"integration registry: {error}" for error in integration_result["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"integration registry unavailable: {error}")
    try:
        graph_result = validate_graph_artifacts(root)
        errors.extend(f"graph registry: {error}" for error in graph_result["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        errors.append(f"graph registry unavailable: {error}")
    try:
        assimilation = validate_capability_assimilation(root)
        errors.extend(f"capability assimilation: {error}" for error in assimilation["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        errors.append(f"capability assimilation unavailable: {error}")
    try:
        semantic = validate_semantic_index(root)
        errors.extend(f"semantic capability index: {error}" for error in semantic["errors"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tomllib.TOMLDecodeError) as error:
        errors.append(f"semantic capability index unavailable: {error}")
    return {"valid": not errors, "active_count": len(seen), "errors": errors}


def navigation_index(root: Path) -> list[CapabilitySummary]:
    capability_map = load_json(root / "registry" / "capability_map.json")
    summaries: list[CapabilitySummary] = []
    for item in capability_map.get("active_capabilities", []):
        contract = load_json(root / item["contract"])
        summaries.append(CapabilitySummary(
            capability_id=contract["id"],
            purpose=" ".join(contract.get("provides", [])),
            triggers=tuple(contract.get("provides", [])),
            aliases=tuple(contract.get("provides", [])),
            required_inputs=tuple(contract.get("consumes", [])),
            risk="R1" if set(contract.get("effects", [])) <= {"read_local"} else "R2",
            status=contract["status"],
            dependencies=tuple(contract.get("dependencies", [])),
            capability_tags=tuple(contract.get("provides", [])),
            freshness=1.0 if contract.get("evidence", {}).get("status") == "current" else 0.25,
            cost={"bounded": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0}.get(contract.get("cost", {}).get("class"), 2.0),
            latency={"local": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0}.get(contract.get("latency", {}).get("class"), 2.0),
        ))
    return summaries


def skill_navigation_index(root: Path) -> list[CapabilitySummary]:
    """Return metadata for every catalog skill without hydrating skill bodies.

    Skill packages are the canonical source for effects, references, validation
    freshness, and execution cost.  The catalog remains the compact startup
    index.  Deferred/candidate records stay visible for audit, but the
    navigator will not select them.
    """
    catalog = load_skill_catalog(root)
    summaries: list[CapabilitySummary] = []
    semantic_records = {
        str(record["id"]): record
        for record in load_semantic_index(root).get("records", ())
        if isinstance(record, dict) and record.get("id")
    }
    for item in catalog.get("skills", ()):
        contract_path = root / str(item.get("contract", ""))
        contract = load_json(contract_path) if contract_path.is_file() else {}
        tags = tuple(str(value) for value in item.get("tags", ()))
        effects = set(contract.get("effects", ()))
        risk = str(contract.get("risk", "R1"))
        if "risk" not in contract:
            risk = "R1" if effects <= {"read_local"} else "R2"
        freshness = 1.0
        if contract.get("validation_freshness") not in (None, "current"):
            freshness = 0.25
        evidence = contract.get("evidence")
        if isinstance(evidence, dict) and evidence.get("status") != "current":
            freshness = 0.25
        purpose_parts = [*tags]
        purpose_parts.extend(str(value) for value in contract.get("provides", ()))
        package_identity_matches = contract.get("id") == item.get("id")
        semantic = semantic_records.get(str(item["id"]), {})
        description = str(semantic.get("description", ""))
        summaries.append(CapabilitySummary(
            capability_id=str(item["id"]),
            purpose=" ".join((*purpose_parts, description)),
            triggers=tags,
            aliases=tuple(dict.fromkeys((*tags, *semantic.get("synonyms", ()), str(item["id"]).replace("-", " ")))),
            required_inputs=tuple(str(value) for value in contract.get("consumes", ())),
            risk=risk,
            status=str(item.get("status", "candidate")),
            # A core runtime contract may back several user-facing skills. Its
            # component dependencies are runtime wiring, not additional skill
            # bodies that must consume the hydration budget.
            dependencies=tuple(str(value) for value in contract.get("dependencies", ())) if package_identity_matches else (),
            capability_tags=tags,
            freshness=freshness,
            cost={"bounded": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0}.get(
                contract.get("cost", {}).get("class") if isinstance(contract.get("cost"), dict) else "low", 1.0
            ),
            latency={"local": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0}.get(
                contract.get("latency", {}).get("class") if isinstance(contract.get("latency"), dict) else "local", 0.0
            ),
            kind=str(semantic.get("kind", "skill")),
            concepts=tuple(str(value) for value in semantic.get("concepts", ())),
            synonyms=tuple(str(value) for value in semantic.get("synonyms", ())),
            tools=tuple(str(value) for value in semantic.get("tools", ())),
            relations=tuple(str(value) for value in semantic.get("relations", ())),
        ))
    return summaries
