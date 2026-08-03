"""Fail-closed facade for the bounded metacognitive evolution layer."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from .agent_profiles.router import compose_team, route
from .capability_genome.genome import build, dependency_health, mutation_plan
from .engineering_dna.profiler import compare_profiles, profile
from .introspection.trace import compare_alternatives, reconstruct
from .knowledge_physics.engine import simulate
from .metacognition.contradiction import detect
from .metacognition.epistemic import build_state
from .optimization.engine import evaluate
from .semantic_contracts.linter import lint
from .theory_induction.inducer import induce, validate_proposal
from ..paths import framework_root


OPERATIONS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "epistemic-state": build_state,
    "detect-contradictions": lambda value: {"contradictions": detect(value.get("claims", []))},
    "build-capability-genome": lambda value: build(value.get("capabilities", []), value.get("relations", [])),
    "dependency-health": dependency_health,
    "plan-capability-mutation": lambda value: mutation_plan(value.get("genome", {}), value.get("desired_outputs", [])),
    "reconstruct-trace": reconstruct,
    "compare-alternatives": compare_alternatives,
    "route-agent": lambda value: route(value["request"], value["agents"]),
    "compose-team": lambda value: compose_team(value["request"], value["agents"], int(value.get("max_agents", 3))),
    "profile-engineering-practices": lambda value: profile(value.get("events", []), int(value.get("min_observations", 3))),
    "compare-engineering-profiles": lambda value: compare_profiles(value.get("source", {}), value.get("target", {})),
    "evaluate-optimization": evaluate,
    "induce-theory": lambda value: induce(value.get("records", []), float(value.get("threshold", 0.45))),
    "validate-theory": lambda value: validate_proposal(value.get("proposal", {}), value.get("held_out_cases", [])),
    "simulate-knowledge-dynamics": simulate,
    "lint-semantic-contract": lint,
}


def _load(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def list_capabilities(root: Path, domain: str | None = None) -> dict[str, Any]:
    records = _load(root, "registry/metacognitive_capability_owners.json")["records"]
    if domain:
        records = [record for record in records if record["domain"] == domain]
    return {"valid": True, "metadata_only": True, "count": len(records), "records": records}


def describe_capability(root: Path, capability_id: str) -> dict[str, Any]:
    records = _load(root, "registry/metacognitive_capabilities.json")["capabilities"]
    owners = _load(root, "registry/metacognitive_capability_owners.json")["records"]
    contract = next((record for record in records if record["id"] == capability_id), None)
    owner = next((record["owner"] for record in owners if record["id"] == capability_id), None)
    if contract is None or owner is None:
        return {"valid": False, "errors": [f"unknown metacognitive capability: {capability_id}"]}
    return {"valid": True, "owner": owner, "contract": contract}


def run_operation(operation: str, payload: dict[str, Any]) -> dict[str, Any]:
    function = OPERATIONS.get(operation)
    if function is None:
        return {"valid": False, "errors": [f"unknown operation: {operation}"], "available": sorted(OPERATIONS)}
    if not isinstance(payload, dict):
        return {"valid": False, "errors": ["payload must be an object"]}
    try:
        result = function(payload)
    except (KeyError, TypeError, ValueError) as error:
        return {"valid": False, "operation": operation, "errors": [str(error)], "input_sha256": _hash(payload)}
    valid = bool(result.get("valid", True)) if isinstance(result, dict) else True
    return {"valid": valid, "operation": operation, "read_only": True, "result": result, "input_sha256": _hash(payload), "result_sha256": _hash(result)}


def validate_layer(root: Path) -> dict[str, Any]:
    capabilities = _load(root, "registry/metacognitive_capabilities.json")
    owners = _load(root, "registry/metacognitive_capability_owners.json")
    formulas = _load(root, "registry/metacognitive_formulas.json")
    policies = _load(root, "registry/metacognitive_policies.json")
    workflows = _load(root, "orchestration/workflows/metacognitive-evolution.yaml")
    schemas = list((root / "contracts" / "metacognitive").glob("*.json"))
    errors: list[str] = []
    expected = {"capabilities": 50, "owners": 50, "formulas": 79, "policies": 9, "workflows": 15, "schemas": 14}
    actual = {
        "capabilities": len(capabilities.get("capabilities", [])),
        "owners": len(owners.get("records", [])),
        "formulas": len(formulas.get("formulas", [])),
        "policies": len(policies.get("policies", [])),
        "workflows": len(workflows.get("workflows", [])),
        "schemas": len(schemas),
    }
    for name, count in expected.items():
        if actual[name] != count:
            errors.append(f"{name} denominator mismatch: {actual[name]} != {count}")
    ids = {item["id"] for item in capabilities.get("capabilities", [])}
    owner_ids = {item["id"] for item in owners.get("records", [])}
    if ids != owner_ids:
        errors.append("capability owner projection is not bijective")
    for workflow in workflows.get("workflows", []):
        for step in workflow.get("steps", []):
            if step.get("skill_id") not in ids:
                errors.append(f"workflow {workflow.get('id')} references unknown capability {step.get('skill_id')}")
    return {"valid": not errors, "counts": actual, "operations": sorted(OPERATIONS), "errors": errors}


def integration_healthcheck() -> dict[str, Any]:
    """Validate the installed or source framework without accepting caller state."""
    return validate_layer(framework_root())
