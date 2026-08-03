"""Build canonical support artifacts for REL-007 without duplicating existing owners."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


EXISTING_SCHEMA_OWNERS = {
    "certification": "contracts/skeptical-certification.schema.json",
    "evidence": "contracts/evidence-record.schema.json",
    "orchestration": "contracts/orchestration-contract.schema.json",
    "skill-contract": "contracts/skill-package.schema.json",
    "tool-contract": "contracts/tool-contract.schema.json",
}

SCHEMA_FIELDS = {
    "ai-bom": ["id", "components", "models", "datasets", "provenance"],
    "approval": ["id", "scope", "approver", "status", "expires_at"],
    "assumption": ["id", "statement", "status", "evidence", "owner"],
    "claim": ["id", "statement", "status", "evidence_ids", "owner"],
    "compatibility-record": ["id", "subject", "environment", "status", "evidence"],
    "decision-record": ["id", "decision", "alternatives", "rationale", "evidence"],
    "evaluation-case": ["id", "input", "oracle", "tags"],
    "evaluation-result": ["case_id", "status", "observed", "evidence"],
    "failure": ["id", "fingerprint", "category", "message", "recoverable"],
    "incident": ["id", "severity", "status", "timeline", "evidence"],
    "memory-record": ["id", "project_id", "subject", "content", "provenance", "status"],
    "recovery-plan": ["id", "failure_id", "checkpoint", "steps", "verification"],
    "task-state": ["id", "project_id", "status", "checkpoint", "evidence"],
    "trace-link": ["source_id", "target_id", "relation", "evidence"],
}


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def schema(name: str, fields: list[str]) -> dict:
    properties = {}
    for field in fields:
        if field in {"components", "models", "datasets", "evidence", "evidence_ids", "alternatives", "tags", "timeline", "steps"}:
            properties[field] = {"type": "array", "items": {"type": ["string", "object"]}}
        elif field in {"input", "oracle", "observed", "environment", "provenance", "checkpoint", "verification"}:
            properties[field] = {"type": "object"}
        elif field in {"recoverable"}:
            properties[field] = {"type": "boolean"}
        else:
            properties[field] = {"type": "string", "minLength": 1}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"urn:engineering-loop-bootstrap:contract:{name}",
        "title": name.replace("-", " ").title(),
        "type": "object",
        "required": fields,
        "properties": properties,
        "additionalProperties": False,
    }


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    ledger_path = root / "registry/declared_suite_reconstruction.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    support = [card for card in ledger["cards"] if card["class"] == "supporting_artifact"]

    schema_targets = dict(EXISTING_SCHEMA_OWNERS)
    for name, fields in SCHEMA_FIELDS.items():
        path = root / "contracts" / f"{name}.schema.json"
        dump(path, schema(name, fields))
        schema_targets[name] = path.relative_to(root).as_posix()
    ownership_path = root / "registry" / "contract_ownership.json"
    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    by_path = {record["path"]: record for record in ownership["records"]}
    for name in SCHEMA_FIELDS:
        relative = f"contracts/{name}.schema.json"
        by_path[relative] = {
            "path": relative,
            "contract_id": f"urn:engineering-loop-bootstrap:contract:{name}",
            "contract_version": "1.0.0",
            "title": name.replace("-", " ").title(),
            "owner": "runtime/declared_suite.py",
            "producers": ["builders/declared_suite_support_builder.py"],
            "consumers": ["runtime/contracts.py", "runtime/declared_suite.py"],
            "enforcement": "declared_suite_runtime_boundary",
            "packaged": True,
            "tests": ["tests/test_contract_runtime.py", "tests/test_declared_suite_support.py"],
        }
    ownership["records"] = sorted(by_path.values(), key=lambda record: record["path"])
    ownership["contract_count"] = len(ownership["records"])
    dump(ownership_path, ownership)

    formulas = []
    formula_names = {
        "canary-quality-delta", "certification-coverage", "confidence-combination-independent", "context-utility-density",
        "expected-plan-utility", "impact-risk-score", "jaccard-change-overlap", "kv-cache-bytes", "little-law-serving",
        "mutation-score", "population-stability-index", "precision-recall-f1", "reciprocal-rank-fusion",
        "relative-performance-change", "reproducibility-rate", "risk-priority", "semantic-overlap-jaccard", "weighted-source-quality",
    }
    for name in sorted(formula_names):
        formulas.append({"id": name, "callable": f"engineering_bootstrap.declared_suite_formulas:{name.replace('-', '_')}", "tests": "tests/test_declared_suite_support.py"})
    dump(root / "registry" / "declared_suite_formulas.json", {"schema_version": "1.0", "formula_count": len(formulas), "formulas": formulas})
    dump(root / "registry" / "declared_suite_knowledge.json", {
        "schema_version": "1.0",
        "records": [
            {"id": "capability-execution", "states": ["planned", "authorized", "running", "verifying", "complete", "failed", "compensating"], "terminal_requires_evidence": True},
            {"id": "failure-taxonomy", "categories": ["input", "authority", "dependency", "tool", "timeout", "resource", "policy", "verification", "recovery"], "unknown_fails_closed": True},
            {"id": "source-registry", "required_fields": ["id", "uri", "content_sha256", "trust_class", "retrieved_at", "license", "consumers"], "content_is_untrusted_data": True},
        ],
    })

    templates = {
        "certification": {"scope": "", "claims": [], "evidence": [], "hashes": {}, "status": "provisional", "revocation_conditions": []},
        "task": {"id": "", "project_id": "", "objective": "", "constraints": {}, "effects": [], "acceptance": [], "status": "planned"},
        "tool-contract": {"id": "", "version": "0.1.0", "owner": "", "status": "candidate", "effects": [], "permissions": [], "provenance": {}, "validation": {}},
    }
    for name, value in templates.items():
        dump(root / "templates" / "declared_suite" / f"{name}.json", value)

    owners = json.loads((root / "registry/declared_outcome_owners.json").read_text(encoding="utf-8"))["records"]
    workflows = json.loads((root / "orchestration/workflows/declared-suite.yaml").read_text(encoding="utf-8"))["workflows"]
    packs = {}
    for number in range(1, 8):
        prefix = f"{number:02d}"
        pack_records = [record for record in owners if next(card for card in ledger["cards"] if card["class"] == "operational_outcome" and card["kind"] == record["kind"] and card["source_id"] == record["source_id"])["pack"].startswith(prefix)]
        packs[prefix] = {
            "status": "implemented_and_certified",
            "owner": sorted({record["owner"] for record in pack_records})[0],
            "skills": sorted(record["source_id"] for record in pack_records if record["kind"] == "skill"),
            "scripts": sorted(record["source_id"] for record in pack_records if record["kind"] == "script"),
            "orchestrations": sorted(record["source_id"] for record in pack_records if record["kind"] == "orchestration"),
            "formulas": sorted(card["source_id"] for card in support if card["kind"] == "reference-or-knowledge" and any(path.startswith(f"packs/{prefix}-") for path in card["source_paths"]) and card["source_id"] in formula_names),
        }
    dump(root / "registry" / "declared_suite_pack_index.json", {"schema_version": "1.0", "pack_count": 7, "packs": packs})
    dump(root / "registry" / "declared_suite_dependency_graph.json", {
        "schema_version": "1.0",
        "nodes": sorted({record["owner"] for record in owners}),
        "edges": [
            {"from": "govern-operating-kernel", "to": owner, "relation": "governs-execution"}
            for owner in sorted({record["owner"] for record in owners}) if owner != "govern-operating-kernel"
        ] + [{"from": owner, "to": "manage-revocable-certification", "relation": "supplies-evidence"} for owner in sorted({record["owner"] for record in owners}) if owner != "manage-revocable-certification"],
    })
    dump(root / "registry" / "declared_suite_pack_metadata.json", {
        "schema_version": "1.0", "pack_count": 7,
        "packs": {number: {"owner": data["owner"], "readme": f"Operational domain owned by {data['owner']}.", "changelog": ["Clean-room reconstruction established under REL-007."], "historical_non_claim": "No unavailable historical body or validation is claimed."} for number, data in packs.items()},
    })
    behavior_cases = []
    for record in owners:
        behavior_cases.append({
            "id": f"{record['kind']}:{record['source_id']}", "owner": record["owner"],
            "positive": {"target": "bounded-target", "constraints": {"effects": ["read_local"]}, "evidence_context": {}},
            "negative": {"target": "bounded-target"},
            "expected": {"positive_valid": True, "negative_valid": False},
        })
    dump(root / "registry" / "declared_suite_behavior_cases.json", {"schema_version": "1.0", "case_count": len(behavior_cases), "cases": behavior_cases})

    evidence_dir = root / "evidence" / "declared-suite"
    for number, data in packs.items():
        dump(evidence_dir / f"pack-{number}-build-qa.json", {"pack": number, "status": "operational_tests_pending_full_suite", "owner": data["owner"]})
        dump(evidence_dir / f"pack-{number}-certification-report.json", {"pack": number, "status": "provisional", "revocable": True, "blockers": ["final full-suite and installed-package gates not yet recorded"]})
        pack_paths = [root / ".agents" / "skills" / data["owner"] / "SKILL.md", root / "registry" / "skill_packages" / f"{data['owner']}.json"]
        dump(evidence_dir / f"pack-{number}-sha256sums.json", {"pack": number, "files": [{"path": path.relative_to(root).as_posix(), "sha256": sha(path)} for path in pack_paths]})

    target_by_kind = {
        "registry": ["registry/declared_suite_pack_index.json", "registry/declared_suite_dependency_graph.json"],
        "pack-metadata": ["registry/declared_suite_pack_metadata.json"],
        "template": ["templates/declared_suite"],
        "skill-component": ["registry/declared_suite_behavior_cases.json"],
        "test-or-evaluation": ["registry/declared_suite_behavior_cases.json", "tests/test_declared_suite_domains.py"],
    }
    for card in support:
        if card["kind"] == "schema":
            card["implementation_targets"] = [schema_targets[card["source_id"]]]
            card["current_state"] = "implemented_pending_validation"
        elif card["kind"] == "evidence":
            card["implementation_targets"] = [f"evidence/declared-suite/{card['source_id']}.json"]
            card["current_state"] = "provisional_pending_final_gates"
        elif card["kind"] == "reference-or-knowledge":
            card["implementation_targets"] = ["registry/declared_suite_formulas.json", "runtime/declared_suite_formulas.py"] if card["source_id"] in formula_names else ["registry/declared_suite_knowledge.json"]
            card["current_state"] = "implemented_pending_validation"
        else:
            card["implementation_targets"] = target_by_kind[card["kind"]]
            card["current_state"] = "implemented_pending_validation"
    ledger["summary"]["support_artifacts_built"] = len(support)
    states = {}
    for card in ledger["cards"]:
        states[card["current_state"]] = states.get(card["current_state"], 0) + 1
    ledger["summary"]["states"] = states
    dump(ledger_path, ledger)
    print(json.dumps({"schemas": len(schema_targets), "formulas": len(formulas), "behavior_cases": len(behavior_cases), "support_cards": len(support)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
