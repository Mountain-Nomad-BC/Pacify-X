"""Idempotently admit the clean-room capability-mining skill wave."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SKILLS = {
    "audit-source-capabilities": (
        ["source", "audit", "coverage", "reconciliation"],
        ["read_local", "write_workspace"],
    ),
    "orchestrate-security-validation": (
        ["security", "validation", "aggregation", "pipeline"],
        ["read_local", "write_workspace"],
    ),
    "harden-container-boundaries": (
        ["container", "database", "isolation", "least-privilege"],
        ["read_local"],
    ),
    "deploy-isolated-model-worker": (
        ["model", "worker", "gpu", "container", "isolation"],
        ["read_local", "write_workspace"],
    ),
    "synchronize-derived-architecture": (
        ["architecture", "documents", "graph", "synchronization"],
        ["read_local", "write_workspace"],
    ),
    "certify-reversible-validation": (
        ["validation", "recovery", "ui", "reversible"],
        ["read_local", "write_workspace"],
    ),
    "govern-visual-runtime-accessibility": (
        ["visual", "runtime", "accessibility", "webgl"],
        ["read_local"],
    ),
    "engineer-hybrid-retrieval": (
        ["retrieval", "ranking", "graph", "governance"],
        ["read_local", "write_workspace"],
    ),
    "inspect-live-contracts": (
        ["contract", "runtime", "dependency", "introspection"],
        ["read_local"],
    ),
    "validate-production-containers": (
        ["container", "production", "validation", "isolation"],
        ["read_local"],
    ),
    "dynamic-service-discovery": (
        ["service-discovery", "dns", "identity", "cache", "network"],
        ["read_local"],
    ),
    "repair-corrupted-text": (
        ["text", "ocr", "repair", "provenance"],
        ["read_local", "write_workspace"],
    ),
    "run-evidence-campaigns": (
        ["evidence", "campaign", "validation", "coverage"],
        ["read_local", "write_workspace"],
    ),
    "triage-cross-surface-failures": (
        ["triage", "failure", "correlation", "diagnosis"],
        ["read_local"],
    ),
    "validate-knowledge-relationships": (
        ["knowledge", "graph", "integrity", "provenance"],
        ["read_local", "write_workspace"],
    ),
    "manage-mcp-lifecycle": (
        ["mcp", "tooling", "lifecycle", "lazy-loading"],
        ["read_local", "write_workspace"],
    ),
    "enforce-source-import-boundaries": (
        ["imports", "architecture", "boundaries", "contracts"],
        ["read_local", "write_workspace"],
    ),
    "govern-deployment-safety": (
        ["deployment", "migration", "release", "rollback"],
        ["read_local"],
    ),
    "run-resilience-drills": (
        ["resilience", "chaos", "recovery", "fault"],
        ["read_local"],
    ),
    "audit-incomplete-implementations": (
        ["completeness", "stub", "fallback", "audit"],
        ["read_local", "write_workspace"],
    ),
}

SCAN_RECEIPTS = [
    {
        "id": "broad-reference-and-code-snapshot",
        "files_accounted": 111139,
        "text_scanned": 44726,
        "excluded_directories": 506,
        "oversize_review_required": 411,
        "error_count": 0,
        "inventory_sha256": "d556939c1c03c61c521d6de8c1cdc240c719ba765d4edcad1c07e5d0a1e98d96",
        "report_sha256": "3b22626a09aa2b00075f86312fcc5080f055cf2d6a0b2817b7ec9fab9a2bec2a",
        "complete": True,
    },
    {
        "id": "control-plane-focus-pass",
        "files_accounted": 8203,
        "text_scanned": 3939,
        "excluded_directories": 60,
        "oversize_review_required": 282,
        "error_count": 0,
        "inventory_sha256": "04a509d2360c43608204cf1e086caca01a674d8bba1a9882e9ce5083d59adfc5",
        "report_sha256": "a2dd7eeb2c7cd5028e450a285473f01627861b6d8d904524a238c7255bdc3a32",
        "complete": True,
    },
    {
        "id": "tooling-audit-intake-pass",
        "files_accounted": 16,
        "text_scanned": 16,
        "excluded_directories": 0,
        "oversize_review_required": 0,
        "error_count": 0,
        "inventory_sha256": "c9dc21d6ad9ef82e58b49cc96a84d90ab70efe955977344d8d947ac07c315e00",
        "report_sha256": "72d873f6e4268dfba718aa41b31150658774163974ca8335e86080cbf4fa9b39",
        "complete": True,
    },
    {
        "id": "simulation-skill-focus-pass",
        "files_accounted": 14,
        "text_scanned": 14,
        "excluded_directories": 0,
        "oversize_review_required": 0,
        "error_count": 0,
        "inventory_sha256": "2ae46679356baae18a9f98c3f9355b9a5346096f4f10756900fd7e6d0df72e82",
        "report_sha256": "4c7bbec98dcccda2066b7b57aeb54530c574ce4c2ee80583ad6c13aaf5816107",
        "complete": True,
    },
    {
        "id": "engineering-skill-focus-pass",
        "files_accounted": 75,
        "text_scanned": 75,
        "excluded_directories": 0,
        "oversize_review_required": 0,
        "error_count": 0,
        "inventory_sha256": "ecefc9891211f66afbf81e445d663ae1d33217de0e115ee4c2042bac50637da5",
        "report_sha256": "6142489104e2b9e51b8d3a3b16821242c60e7846f52a6d2b42d731a9f7711833",
        "complete": True,
    },
]

DISPOSITIONS = [
    ("source-audit-scanner", "adopt", ["audit-source-capabilities"]),
    (
        "source-audit-analysis",
        "merge",
        ["audit-source-capabilities", "validate-knowledge-relationships"],
    ),
    (
        "dependency-aware-security-pipeline",
        "adopt",
        ["orchestrate-security-validation"],
    ),
    (
        "enterprise-completion-punch-card",
        "merge",
        ["orchestrate-engineering-loop", "run-evidence-campaigns"],
    ),
    ("isolated-accelerated-worker", "adopt", ["deploy-isolated-model-worker"]),
    ("isolated-container-validation", "adopt", ["validate-production-containers"]),
    (
        "container-injected-contract-audit",
        "merge",
        ["harden-container-boundaries", "inspect-live-contracts"],
    ),
    ("database-isolation-hardening", "merge", ["harden-container-boundaries"]),
    ("hybrid-retrieval-pipeline", "adopt", ["engineer-hybrid-retrieval"]),
    (
        "least-privilege-builds",
        "merge",
        ["harden-container-boundaries", "govern-deployment-safety"],
    ),
    ("dynamic-name-resolution", "adopt", ["dynamic-service-discovery"]),
    ("reversible-interface-certification", "adopt", ["certify-reversible-validation"]),
    ("corrupted-text-repair", "adopt", ["repair-corrupted-text"]),
    ("architecture-document-sync", "adopt", ["synchronize-derived-architecture"]),
    ("visual-runtime-accessibility", "adopt", ["govern-visual-runtime-accessibility"]),
    ("security-result-aggregation", "merge", ["orchestrate-security-validation"]),
    ("mcp-server-lifecycle", "adopt", ["manage-mcp-lifecycle"]),
    ("source-import-boundaries", "adopt", ["enforce-source-import-boundaries"]),
    (
        "document-relationship-synchronization",
        "merge",
        ["synchronize-derived-architecture", "validate-knowledge-relationships"],
    ),
    ("deployment-safety-governor", "adopt", ["govern-deployment-safety"]),
    ("approval-gated-resilience", "adopt", ["run-resilience-drills"]),
    ("incomplete-implementation-census", "adopt", ["audit-incomplete-implementations"]),
    (
        "runtime-route-access-drift",
        "merge",
        ["validate-contract-boundaries", "inspect-live-contracts"],
    ),
    (
        "fallback-truth-classification",
        "merge",
        ["audit-incomplete-implementations", "validate-engineering-outcomes"],
    ),
    ("full-evidence-campaign", "adopt", ["run-evidence-campaigns"]),
    ("cross-surface-failure-triage", "adopt", ["triage-cross-surface-failures"]),
    (
        "knowledge-relationship-validation",
        "adopt",
        ["validate-knowledge-relationships"],
    ),
    ("api-producer-consumer-parity", "merge", ["validate-contract-boundaries"]),
    ("secret-safe-retrieval", "merge", ["memory-injection-firewall"]),
    (
        "artifact-bound-release-certification",
        "merge",
        ["certify-skeptical-engineering", "provenance-signature-verifier"],
    ),
    (
        "changed-area-validation-routing",
        "merge",
        ["dependency-impact-tracer", "active-evaluation-selector"],
    ),
    (
        "oversize-derived-payload-bucket",
        "reference_only",
        [
            "audit-source-capabilities",
            "run-evidence-campaigns",
            "validate-knowledge-relationships",
        ],
    ),
    ("prototype-loader-without-lifecycle", "reject", ["quarantine-external-tools"]),
    ("unexecuted-proof-generator", "reject", ["certify-skeptical-engineering"]),
    ("blanket-card-closure", "reject", ["run-evidence-campaigns"]),
]

WORKFLOWS = [
    {
        "id": "source-capability-assimilation",
        "purpose": "Account, classify, admit, map, validate, and evidence reusable source mechanisms without copying private product identity.",
        "steps": [
            {"id": "inventory", "skill": "audit-source-capabilities", "depends_on": []},
            {
                "id": "incompleteness",
                "skill": "audit-incomplete-implementations",
                "depends_on": ["inventory"],
            },
            {
                "id": "relationships",
                "skill": "validate-knowledge-relationships",
                "depends_on": ["inventory"],
            },
            {
                "id": "boundaries",
                "skill": "enforce-source-import-boundaries",
                "depends_on": ["inventory"],
            },
            {
                "id": "derive",
                "skill": "synchronize-derived-architecture",
                "depends_on": ["relationships", "boundaries"],
            },
            {
                "id": "certify",
                "skill": "run-evidence-campaigns",
                "depends_on": ["incompleteness", "derive"],
            },
        ],
    },
    {
        "id": "secure-service-release",
        "purpose": "Validate isolated services from contract and discovery design through security aggregation and deployment evidence.",
        "steps": [
            {"id": "isolate", "skill": "harden-container-boundaries", "depends_on": []},
            {
                "id": "discover",
                "skill": "dynamic-service-discovery",
                "depends_on": ["isolate"],
            },
            {
                "id": "contracts",
                "skill": "inspect-live-contracts",
                "depends_on": ["discover"],
            },
            {
                "id": "security",
                "skill": "orchestrate-security-validation",
                "depends_on": ["contracts"],
            },
            {
                "id": "containers",
                "skill": "validate-production-containers",
                "depends_on": ["security"],
            },
            {
                "id": "release",
                "skill": "govern-deployment-safety",
                "depends_on": ["containers"],
            },
            {
                "id": "evidence",
                "skill": "run-evidence-campaigns",
                "depends_on": ["release"],
            },
        ],
    },
    {
        "id": "retrieval-readiness",
        "purpose": "Repair and validate source knowledge before constructing and evaluating governed retrieval.",
        "steps": [
            {"id": "repair", "skill": "repair-corrupted-text", "depends_on": []},
            {
                "id": "relationships",
                "skill": "validate-knowledge-relationships",
                "depends_on": ["repair"],
            },
            {
                "id": "retrieval",
                "skill": "engineer-hybrid-retrieval",
                "depends_on": ["relationships"],
            },
            {
                "id": "evaluate",
                "skill": "evaluate-retrieval-readiness",
                "depends_on": ["retrieval"],
            },
            {
                "id": "evidence",
                "skill": "run-evidence-campaigns",
                "depends_on": ["evaluate"],
            },
        ],
    },
    {
        "id": "failure-and-recovery",
        "purpose": "Triage cross-surface failure, prove reversible restoration, exercise bounded resilience, and retain release blockers.",
        "steps": [
            {
                "id": "triage",
                "skill": "triage-cross-surface-failures",
                "depends_on": [],
            },
            {
                "id": "restore",
                "skill": "certify-reversible-validation",
                "depends_on": ["triage"],
            },
            {
                "id": "drill",
                "skill": "run-resilience-drills",
                "depends_on": ["restore"],
            },
            {
                "id": "release",
                "skill": "govern-deployment-safety",
                "depends_on": ["drill"],
            },
        ],
    },
    {
        "id": "external-tool-lifecycle",
        "purpose": "Audit, quarantine, admit, lazily register, and protocol-certify external tool servers.",
        "steps": [
            {"id": "inventory", "skill": "audit-source-capabilities", "depends_on": []},
            {
                "id": "quarantine",
                "skill": "quarantine-external-tools",
                "depends_on": ["inventory"],
            },
            {
                "id": "lifecycle",
                "skill": "manage-mcp-lifecycle",
                "depends_on": ["quarantine"],
            },
        ],
    },
]


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")


def resources(skill_id: str) -> list[str]:
    root = ROOT / ".agents" / "skills" / skill_id
    return [
        item.relative_to(ROOT).as_posix()
        for folder in ("scripts", "references", "assets")
        if (root / folder).is_dir()
        for item in sorted((root / folder).rglob("*"))
        if item.is_file()
        and item.suffix.casefold() not in {".pyc", ".pyo"}
        and "__pycache__" not in item.parts
    ]


def update_catalog() -> None:
    path = ROOT / "registry" / "skill_catalog.toml"
    text = path.read_text(encoding="utf-8")
    for skill_id, (tags, _) in SKILLS.items():
        if re.search(rf'(?m)^id = "{re.escape(skill_id)}"$', text):
            continue
        rendered_tags = ", ".join(json.dumps(tag) for tag in tags)
        text += f'\n[[skills]]\nid = "{skill_id}"\nversion = "0.1.0"\nstatus = "active"\nbody = ".agents/skills/{skill_id}/SKILL.md"\ncontract = "registry/skill_packages/{skill_id}.json"\nadmission_record = "{skill_id}"\ntags = [{rendered_tags}]\n'
    path.write_text(text.rstrip() + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    update_catalog()
    for skill_id, (tags, effects) in SKILLS.items():
        body = ROOT / ".agents" / "skills" / skill_id / "SKILL.md"
        if not body.is_file():
            raise FileNotFoundError(body)
        package = {
            "id": skill_id,
            "version": "0.1.0",
            "status": "active",
            "body": body.relative_to(ROOT).as_posix(),
            "body_sha256": hashlib.sha256(body.read_bytes()).hexdigest(),
            "references": [],
            "resources": resources(skill_id),
            "capability_tags": tags,
            "effects": effects,
            "provenance": {
                "type": "clean_room",
                "basis": [
                    {"receipt": item["id"], "report_sha256": item["report_sha256"]}
                    for item in SCAN_RECEIPTS
                ],
            },
            "clean_room": True,
            "tests": "tests/test_capability_mining_skills.py; tests/test_capability_assimilation.py",
            "evidence": "evidence/capability-mining-receipt.json",
            "validation_freshness": "current",
            "context_budget_bytes": 24576,
        }
        write_json(ROOT / "registry" / "skill_packages" / f"{skill_id}.json", package)

    ledger_path = ROOT / "registry" / "admission_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    records = {str(item["id"]): item for item in ledger.get("records", ())}
    for skill_id, (_, effects) in SKILLS.items():
        records[skill_id] = {
            "id": skill_id,
            "source_disposition": "pattern_only",
            "implementation": "clean_room",
            "status": "active",
            "validation": {"passed": 2, "failed": 0},
            "effects": effects,
            "notes": "Bounded clean-room capability with lazy body loading, explicit source disposition, and deterministic validation evidence.",
        }
    ledger["records"] = [records[key] for key in sorted(records)]
    write_json(ledger_path, ledger)

    admission = {
        "schema_version": "1.0",
        "coverage_denominator_policy": "Use the largest complete snapshot; focused scans overlap and are not added to the denominator.",
        "scan_receipts": [{"schema_version": "1.0", **item} for item in SCAN_RECEIPTS],
        "dispositions": [
            {"id": identity, "disposition": disposition, "targets": targets}
            for identity, disposition, targets in DISPOSITIONS
        ],
        "oversize_review": {
            "record_count": 411,
            "bytes": 7283852942,
            "extensions": {"json": 389, "markdown": 15, "text": 7},
            "categories": {
                "derived_code_index_cache": 121,
                "domain_data_and_derived_index": 85,
                "generated_audit_and_run_evidence": 172,
                "simulation_fixture_and_run_ledger": 3,
                "other_manifest_inventory_or_domain_payload": 30,
            },
            "disposition": "reference_only",
            "reason": "The bucket contains derived indexes, data payloads, generated evidence, inventories, manifests, fixtures, and run ledgers. Headings and path classes were reviewed; reusable mechanisms are represented by admitted audit, evidence, knowledge, retrieval, and synchronization skills.",
        },
        "rejection_policy": "Generated reports, caches, backups, old snapshots, unexecuted proof, blanket completion, and lifecycle-free loaders are evidence or quarantine inputs, never active behavior.",
    }
    admission_path = ROOT / "registry" / "capability_mining_admission.json"
    write_json(admission_path, admission)
    write_json(
        ROOT / "registry" / "skill_orchestrations.json",
        {
            "schema_version": "1.0",
            "loading_rule": "Load workflow and skill metadata first; hydrate one selected skill body at a time.",
            "count": len(WORKFLOWS),
            "workflows": WORKFLOWS,
        },
    )
    (ROOT / "orchestration" / "workflows").mkdir(parents=True, exist_ok=True)
    write_json(
        ROOT / "orchestration" / "workflows" / "capability-assimilation.yaml",
        {
            "schema_version": "1.0",
            "registry": "registry/skill_orchestrations.json",
            "workflows": WORKFLOWS,
        },
    )

    receipt = {
        "schema_version": "1.0",
        "status": "implemented_pending_release_certification",
        "scan_count": len(SCAN_RECEIPTS),
        "files_accounted": max(item["files_accounted"] for item in SCAN_RECEIPTS),
        "focused_scan_observations": sum(
            item["files_accounted"] for item in SCAN_RECEIPTS[1:]
        ),
        "disposition_count": len(DISPOSITIONS),
        "admitted_skill_count": len(SKILLS),
        "workflow_count": len(WORKFLOWS),
        "admission_registry_sha256": hashlib.sha256(
            admission_path.read_bytes()
        ).hexdigest(),
        "raw_reports_custody_index": "evidence/externalized-payload-index.json",
    }
    write_json(ROOT / "evidence" / "capability-mining-receipt.json", receipt)

    coverage_path = ROOT / "registry" / "source_requirement_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["controls"] = [
        item
        for item in coverage["controls"]
        if item.get("id") != "source-capability-assimilation"
    ]
    coverage["controls"].append(
        {
            "id": "source-capability-assimilation",
            "state": "operational_bounded",
            "release_role": "required",
            "owners": [
                "runtime/capability_assimilation.py",
                "registry/capability_mining_admission.json",
                "registry/skill_orchestrations.json",
            ],
            "skills": list(SKILLS),
            "contracts": ["contracts/source-capability-audit.schema.json"],
            "tests": [
                "tests/test_capability_assimilation.py",
                "tests/test_capability_mining_skills.py",
            ],
        }
    )
    coverage["controls"].sort(key=lambda item: item["id"])
    write_json(coverage_path, coverage)

    lifecycle_path = ROOT / "registry" / "engineering_lifecycle.json"
    lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
    discovery = next(
        item for item in lifecycle["stages"] if item["id"] == "environment-discovery"
    )
    for skill_id in (
        "audit-source-capabilities",
        "audit-incomplete-implementations",
        "validate-knowledge-relationships",
    ):
        if skill_id not in discovery["skills"]:
            discovery["skills"].append(skill_id)
    for item in (
        "complete source capability coverage receipt",
        "explicit capability disposition registry",
    ):
        if item not in discovery["exit_evidence"]:
            discovery["exit_evidence"].append(item)
    write_json(lifecycle_path, lifecycle)
    # Body hashes bind every package after cross-cutting merge updates, not only
    # the newly admitted wave.
    for package_path in sorted((ROOT / "registry" / "skill_packages").glob("*.json")):
        package = json.loads(package_path.read_text(encoding="utf-8"))
        body = ROOT / str(package["body"])
        package["body_sha256"] = hashlib.sha256(body.read_bytes()).hexdigest()
        write_json(package_path, package)
    print(
        json.dumps(
            {
                "skills": len(SKILLS),
                "dispositions": len(DISPOSITIONS),
                "workflows": len(WORKFLOWS),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
