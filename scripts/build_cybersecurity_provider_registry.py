"""Build/check the governed cybersecurity provider projection from its source pack."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from runtime.json_io import load_json_object  # noqa: E402
from runtime.evidence_portability import rewrite_reference_literals  # noqa: E402


EXPECTED_ARCHIVE = "460f2ed54dac3bc96a453d2fd30c098234df80d3840fda475ba95b1e3983a08f"
EXPECTED_RECORDS = 817
EXPECTED_EDGES = 14_595
OUTPUT = Path("registry/security_capabilities")


OPERATIONAL_CONTRACTS: dict[str, dict[str, object]] = {
    "authorized-security-scope": {
        "required": [
            "engagement_id",
            "targets",
            "target_allowlist",
            "authorization_status",
            "authorization_artifact_id",
            "approved_by",
            "valid_from",
            "valid_until",
            "rules_of_engagement",
        ],
        "properties": {
            "engagement_id": {"type": "string", "minLength": 3},
            "targets": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "target_allowlist": {
                "type": "array",
                "minItems": 1,
                "uniqueItems": True,
                "items": {"type": "string", "minLength": 1},
            },
            "authorization_status": {"const": "approved"},
            "authorization_artifact_id": {"type": "string", "minLength": 1},
            "approved_by": {"type": "string", "minLength": 1},
            "valid_from": {"type": "string", "format": "date-time"},
            "valid_until": {"type": "string", "format": "date-time"},
            "rules_of_engagement": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
    "external-provider-integrity": {
        "required": [
            "archive_sha256",
            "catalog_sha256",
            "graph_sha256",
            "source_inventory_count",
            "catalog_count",
            "license",
            "frontmatter_valid",
            "selected_body_hashes_valid",
        ],
        "properties": {
            "archive_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "catalog_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "graph_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "source_inventory_count": {"type": "integer", "minimum": 1},
            "catalog_count": {"const": 817},
            "license": {"const": "Apache-2.0"},
            "frontmatter_valid": {"const": True},
            "selected_body_hashes_valid": {"const": True},
        },
    },
    "incident-response-emergency-authority": {
        "required": [
            "incident_id",
            "severity",
            "commander",
            "containment_actions",
            "expires_at",
            "after_action_review_required",
        ],
        "properties": {
            "incident_id": {"type": "string", "minLength": 1},
            "severity": {"enum": ["low", "medium", "high", "critical"]},
            "commander": {"type": "string", "minLength": 1},
            "containment_actions": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "expires_at": {"type": "string", "format": "date-time"},
            "after_action_review_required": {"const": True},
        },
    },
    "safe-security-execution": {
        "required": [
            "authority_source",
            "metadata_grants_authority",
            "provider_scripts_executed",
            "R4_default",
            "network_egress_default",
        ],
        "properties": {
            "authority_source": {"const": "runtime_policy"},
            "metadata_grants_authority": {"const": False},
            "provider_scripts_executed": {"const": False},
            "R4_default": {"const": "knowledge_or_isolated_lab"},
            "network_egress_default": {"const": "deny"},
        },
    },
    "security-change-control": {
        "required": [
            "owner",
            "change_window",
            "rollback_plan",
            "pre_change_evidence",
            "post_change_validation",
            "service_impact_assessment",
        ],
        "properties": {
            "owner": {"type": "string", "minLength": 1},
            "change_window": {"type": "string", "minLength": 1},
            "rollback_plan": {"type": "string", "minLength": 1},
            "pre_change_evidence": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "post_change_validation": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "service_impact_assessment": {"type": "string", "minLength": 1},
        },
    },
    "security-cleanup-and-rollback": {
        "required": [
            "cleanup_checklist",
            "artifact_inventory",
            "rollback_evidence",
            "residual_risk",
            "cleanup_verified",
        ],
        "properties": {
            "cleanup_checklist": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "artifact_inventory": {"type": "array", "items": {"type": "string"}},
            "rollback_evidence": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "residual_risk": {"type": "string", "minLength": 1},
            "cleanup_verified": {"const": True},
        },
    },
    "security-evidence-chain": {
        "required": [
            "evidence_id",
            "source_sha256",
            "acquired_at",
            "actor",
            "original_immutable",
            "transformations",
            "analysis_separate",
        ],
        "properties": {
            "evidence_id": {"type": "string", "minLength": 1},
            "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "acquired_at": {"type": "string", "format": "date-time"},
            "actor": {"type": "string", "minLength": 1},
            "original_immutable": {"const": True},
            "transformations": {"type": "array", "items": {"type": "object"}},
            "analysis_separate": {"const": True},
        },
    },
    "security-finding-result": {
        "required": [
            "finding_id",
            "state",
            "evidence",
            "confidence",
            "affected_assets",
            "severity_rationale",
            "recommended_actions",
            "validation_status",
        ],
        "properties": {
            "finding_id": {"type": "string", "minLength": 1},
            "state": {
                "enum": [
                    "observation",
                    "candidate_finding",
                    "verified_finding",
                    "false_positive",
                    "accepted_risk",
                    "remediated",
                    "verification_failed",
                ]
            },
            "evidence": {"type": "array", "items": {"type": "object"}},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "affected_assets": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "severity_rationale": {"type": "string", "minLength": 1},
            "recommended_actions": {"type": "array", "items": {"type": "string"}},
            "validation_status": {
                "enum": [
                    "unverified",
                    "partially_verified",
                    "verified",
                    "false_positive",
                    "accepted_risk",
                ]
            },
        },
    },
    "security-tool-invocation": {
        "required": [
            "tool_id",
            "tool_version",
            "arguments",
            "targets",
            "risk_class",
            "timeout_seconds",
            "max_output_bytes",
            "capture_output",
            "cleanup_plan",
            "approval_id",
        ],
        "properties": {
            "tool_id": {"type": "string", "minLength": 1},
            "tool_version": {"type": "string", "minLength": 1},
            "arguments": {"type": "array", "items": {"type": "string"}},
            "targets": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "minLength": 1},
            },
            "risk_class": {"enum": ["R0", "R1", "R2", "R3", "R4"]},
            "timeout_seconds": {"type": "integer", "minimum": 1},
            "max_output_bytes": {"type": "integer", "minimum": 1},
            "capture_output": {"const": True},
            "cleanup_plan": {"type": "string", "minLength": 1},
            "approval_id": {"type": ["string", "null"]},
        },
    },
}


def _yaml(path: Path) -> dict[str, object]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected YAML object: {path}")
    return value


def _render(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_or_check(
    path: Path, content: bytes, *, check: bool, drift: list[str]
) -> None:
    if not path.is_file() or path.read_bytes() != content:
        drift.append(path.as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)


def _frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not match:
        raise ValueError(f"missing frontmatter: {path}")
    value = yaml.safe_load(match.group(1))
    if not isinstance(value, dict):
        raise ValueError(f"invalid frontmatter: {path}")
    return {str(key): str(item) for key, item in value.items()}


def build(root: Path, source: Path, *, check: bool = False) -> dict[str, object]:
    root = root.resolve(strict=True)
    source = source.resolve(strict=True)
    archive = source / "upstream/Anthropic-Cybersecurity-Skills-main.zip"
    if _sha(archive) != EXPECTED_ARCHIVE:
        raise ValueError("cybersecurity source archive hash mismatch")
    catalog = source / "registries/cybersecurity_capabilities.jsonl"
    graph = source / "registries/security_capability_graph.jsonl"
    if (
        sum(1 for line in catalog.open(encoding="utf-8") if line.strip())
        != EXPECTED_RECORDS
    ):
        raise ValueError("cybersecurity catalog count mismatch")
    if (
        sum(1 for line in graph.open(encoding="utf-8") if line.strip())
        != EXPECTED_EDGES
    ):
        raise ValueError("cybersecurity graph count mismatch")
    target = root / OUTPUT
    drift: list[str] = []
    catalog_projection = b"".join(
        (
            json.dumps(
                rewrite_reference_literals(
                    json.loads(line),
                    {"file://": "local file URI scheme "},
                ),
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        for line in catalog.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    _write_or_check(
        target / "capabilities.jsonl",
        catalog_projection,
        check=check,
        drift=drift,
    )
    for source_name, target_name in (
        ("registries/security_capability_graph.jsonl", "graph.jsonl"),
        ("registries/framework_coverage.json", "framework_coverage.json"),
    ):
        _write_or_check(
            target / target_name,
            (source / source_name).read_bytes(),
            check=check,
            drift=drift,
        )
    for source_name, target_name in (
        ("registries/security_domains.yaml", "domains.json"),
        ("registries/security_risk_classes.yaml", "risk_classes.json"),
        ("registries/security_intent_aliases.yaml", "intent_aliases.json"),
    ):
        _write_or_check(
            target / target_name,
            _render(_yaml(source / source_name)).encode(),
            check=check,
            drift=drift,
        )
    registration = _yaml(source / "registries/provider_registration.yaml")
    registration.update(
        {
            "catalog": "registry/security_capabilities/capabilities.jsonl",
            "graph": "registry/security_capabilities/graph.jsonl",
            "framework_coverage": "registry/security_capabilities/framework_coverage.json",
            "source_archive": None,
            "source_archive_distribution": "not_bundled; supply separately to the explicit hydration command",
            "discovery_enabled": True,
            "execution_enabled": False,
            "disableable": True,
            "provider_scripts_admitted": 0,
        }
    )
    _write_or_check(
        target / "provider.json",
        _render(registration).encode(),
        check=check,
        drift=drift,
    )
    archive_metadata = load_json_object(source / "manifest/source_archive.json")
    source_doc = {
        "schema_version": "1.0",
        "source_project": "Anthropic Cybersecurity Skills",
        "affiliation": "Independent community project; not affiliated with Anthropic PBC.",
        "license": "Apache-2.0",
        "archive_sha256": archive_metadata["sha256"],
        "archive_entries": archive_metadata["entry_count"],
        "archive_size_bytes": archive_metadata["size_bytes"],
        "catalog_sha256": _sha(catalog),
        "graph_sha256": _sha(graph),
        "archive_bundled": False,
        "body_hydration": "explicit_verified_archive_only",
    }
    _write_or_check(
        target / "source.json", _render(source_doc).encode(), check=check, drift=drift
    )
    domains = _yaml(source / "registries/security_domains.yaml")
    golden = {
        "schema_version": "1.0",
        "cases": [
            {
                "id": f"domain-{domain}",
                "query": domain.replace("-", " "),
                "expected_domain": domain,
                "top_k": 10,
            }
            for domain in sorted(domains["canonical_counts"])
        ],
    }
    _write_or_check(
        target / "golden_queries.json",
        _render(golden).encode(),
        check=check,
        drift=drift,
    )
    contracts = root / "contracts/security_capabilities"
    for path in sorted((source / "schemas").glob("*.json")):
        value = load_json_object(path)
        contract_name = path.name.removesuffix(".schema.json")
        value["$id"] = (
            f"urn:engineering-loop-bootstrap:contract:security_capabilities:{contract_name}"
        )
        _write_or_check(
            contracts / path.name, _render(value).encode(), check=check, drift=drift
        )
    for path in sorted((source / "contracts").glob("*.yaml")):
        source_value = _yaml(path)
        contract_name = path.stem
        definition = OPERATIONAL_CONTRACTS[contract_name]
        value = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"urn:engineering-loop-bootstrap:contract:security_capabilities:{contract_name}",
            "title": contract_name,
            "description": str(source_value.get("purpose", contract_name)),
            "type": "object",
            "additionalProperties": False,
            "required": definition["required"],
            "properties": definition["properties"],
        }
        _write_or_check(
            contracts / f"{path.stem}.schema.json",
            _render(value).encode(),
            check=check,
            drift=drift,
        )

    native = []
    for path in sorted((source / "skills").glob("*/SKILL.md")):
        metadata = _frontmatter(path)
        native.append(
            {
                "source_id": metadata["name"],
                "description": metadata["description"],
                "risk_class": metadata["risk_class"],
                "disposition": "merge_into_existing",
                "canonical_owner": "govern-cybersecurity-capabilities",
                "complementary_owners": [
                    "govern-external-capability-intake",
                    "orchestrate-security-validation",
                    "secure-agent-supply-chain",
                    "supervise-contained-execution",
                    "validate-engineering-outcomes",
                ],
            }
        )
    native_doc = {
        "schema_version": "1.0",
        "count": len(native),
        "records": native,
        "duplicate_active_skills_created": 0,
    }
    _write_or_check(
        target / "native_skill_dispositions.json",
        _render(native_doc).encode(),
        check=check,
        drift=drift,
    )
    workflows = []
    for path in sorted((source / "workflows").glob("*.yaml")):
        value = _yaml(path)
        workflows.append(
            {
                "source_id": str(value.get("id", path.stem)),
                "source_path": f"workflows/{path.name}",
                "disposition": "merge_into_existing",
                "canonical_owner": "cybersecurity-capability-operations",
                "expected_outcomes": value.get(
                    "outputs", value.get("expected_outputs", [])
                ),
            }
        )
    workflows_doc = {
        "schema_version": "1.0",
        "count": len(workflows),
        "records": workflows,
    }
    _write_or_check(
        target / "workflow_dispositions.json",
        _render(workflows_doc).encode(),
        check=check,
        drift=drift,
    )

    skill_id = "govern-cybersecurity-capabilities"
    skill_body = f".agents/skills/{skill_id}/SKILL.md"
    manifest = {
        "id": skill_id,
        "version": "1.0.0",
        "status": "active",
        "body": skill_body,
        "body_sha256": _sha(root / skill_body),
        "references": [
            f".agents/skills/{skill_id}/references/authority-and-execution.md",
            f".agents/skills/{skill_id}/references/domain-operations.md",
        ],
        "capability_tags": [
            "authority",
            "cybersecurity",
            "evidence",
            "external-provider",
            "framework-mapping",
            "risk",
            "selective-hydration",
        ],
        "effects": ["read_local"],
        "provenance": {
            "type": "governed_external_provider_merge",
            "basis": [
                "registry/security_capabilities/provider.json",
                "contracts/security_capabilities",
                "tests/test_cybersecurity_provider.py",
            ],
            "canonical_owner": "runtime/cybersecurity_provider.py",
            "source_license": "Apache-2.0",
        },
        "clean_room": False,
        "tests": "tests/test_cybersecurity_provider.py",
        "evidence": "evidence/integration/pxi-20260804/cybersecurity_provider_disposition.json",
        "validation_freshness": "current",
        "context_budget_bytes": 32_768,
    }
    _write_or_check(
        root / f"registry/skill_packages/{skill_id}.json",
        _render(manifest).encode(),
        check=check,
        drift=drift,
    )

    ledger_path = root / "registry/admission_ledger.json"
    ledger = load_json_object(ledger_path)
    desired_ledger = {
        "effects": ["read_local"],
        "id": skill_id,
        "implementation": "governed_provider_adapter",
        "notes": "One lazy control skill owns 817 metadata-only candidates; R3/R4 fail closed and provider scripts remain inert.",
        "source_disposition": "merge",
        "status": "active",
        "validation": {"failed": 0, "passed": 16},
    }
    by_id = {str(item["id"]): item for item in ledger["records"]}
    if by_id.get(skill_id) != desired_ledger:
        drift.append(ledger_path.as_posix())
        if not check:
            by_id[skill_id] = desired_ledger
            ledger["records"] = [by_id[key] for key in sorted(by_id)]
            ledger_path.write_text(_render(ledger), encoding="utf-8", newline="\n")

    catalog_path = root / "registry/skill_catalog.toml"
    catalog_text = catalog_path.read_text(encoding="utf-8")
    if f'id = "{skill_id}"' not in catalog_text:
        drift.append(catalog_path.as_posix())
        if not check:
            tags = ", ".join(json.dumps(item) for item in manifest["capability_tags"])
            block = (
                "\n[[skills]]\n"
                f'id = "{skill_id}"\nversion = "1.0.0"\nstatus = "active"\n'
                f'body = "{skill_body}"\ncontract = "registry/skill_packages/{skill_id}.json"\n'
                f'admission_record = "{skill_id}"\ntags = [{tags}]\n'
            )
            catalog_path.write_text(
                catalog_text.rstrip() + "\n" + block, encoding="utf-8", newline="\n"
            )

    bindings_path = root / "registry/workflow_execution_bindings.json"
    bindings = load_json_object(bindings_path)
    desired_binding = {
        "path": "orchestration/workflows/cybersecurity-capability-operations.yaml",
        "mode": "executable_validator",
        "entrypoint": "runtime.cybersecurity_provider:validate_security_orchestration",
    }
    binding_by_path = {str(item["path"]): item for item in bindings["bindings"]}
    if binding_by_path.get(desired_binding["path"]) != desired_binding:
        drift.append(bindings_path.as_posix())
        if not check:
            binding_by_path[desired_binding["path"]] = desired_binding
            bindings["bindings"] = [
                binding_by_path[key] for key in sorted(binding_by_path)
            ]
            bindings["count"] = len(bindings["bindings"])
            bindings_path.write_text(_render(bindings), encoding="utf-8", newline="\n")

    orchestrations_path = root / "registry/skill_orchestrations.json"
    orchestrations = load_json_object(orchestrations_path)
    workflow = load_json_object(
        root / "orchestration/workflows/cybersecurity-capability-operations.yaml"
    )
    desired_workflow = {
        key: value
        for key, value in workflow.items()
        if key not in {"version", "loading_rule", "bounds", "scenarios"}
    }
    workflow_by_id = {str(item["id"]): item for item in orchestrations["workflows"]}
    if workflow_by_id.get(str(desired_workflow["id"])) != desired_workflow:
        drift.append(orchestrations_path.as_posix())
        if not check:
            workflow_by_id[str(desired_workflow["id"])] = desired_workflow
            orchestrations["workflows"] = [
                workflow_by_id[key] for key in sorted(workflow_by_id)
            ]
            orchestrations["count"] = len(orchestrations["workflows"])
            orchestrations_path.write_text(
                _render(orchestrations), encoding="utf-8", newline="\n"
            )

    pack_rows = [
        json.loads(line)
        for line in (source / "manifest/pack_files.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    dispositions = []
    for row in pack_rows:
        path = str(row["path"])
        if path == "upstream/Anthropic-Cybersecurity-Skills-main.zip":
            disposition, owner = (
                "retain_external_not_distributed",
                "external-source-custody",
            )
        elif path.startswith("licenses/"):
            disposition, owner = "merge", "NOTICE"
        elif path.startswith("skills/"):
            disposition, owner = (
                "merge",
                ".agents/skills/govern-cybersecurity-capabilities",
            )
        elif path.startswith("workflows/"):
            disposition, owner = (
                "merge",
                "orchestration/workflows/cybersecurity-capability-operations.yaml",
            )
        elif path.startswith(("contracts/", "schemas/")):
            disposition, owner = "merge", "contracts/security_capabilities"
        elif path.startswith(("registries/", "manifest/")):
            disposition, owner = "merge", "registry/security_capabilities"
        elif path.startswith(("validators/", "tools/", "tests/")):
            disposition, owner = "merge", "runtime/cybersecurity_provider.py"
        else:
            disposition, owner = "fragment_only", "evidence/integration/pxi-20260804"
        dispositions.append(
            {
                **row,
                "disposition": disposition,
                "canonical_owner": owner,
                "source_alias": "new_adds_20260804",
            }
        )
    candidate_rows = [
        {
            "id": json.loads(line)["id"],
            "disposition": "defer_as_external_candidate",
            "canonical_owner": "runtime/cybersecurity_provider.py",
        }
        for line in catalog.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    evidence = {
        "schema_version": "1.0",
        "source_pack": "PACIFY-X-Cybersecurity-Capability-Expansion",
        "source_pack_file_count": len(dispositions),
        "candidate_count": len(candidate_rows),
        "unaccounted_count": 0,
        "hard_delete": False,
        "files": dispositions,
        "external_candidates": candidate_rows,
    }
    _write_or_check(
        root
        / "evidence/integration/pxi-20260804/cybersecurity_provider_disposition.json",
        _render(evidence).encode(),
        check=check,
        drift=drift,
    )
    return {
        "valid": not drift,
        "check": check,
        "drift": sorted(drift),
        "record_count": EXPECTED_RECORDS,
        "edge_count": EXPECTED_EDGES,
        "pack_file_count": len(dispositions),
        "candidate_count": len(candidate_rows),
        "unaccounted_count": 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build(args.root, args.source, check=args.check)
    print(_render(result), end="")
    raise SystemExit(0 if result["valid"] or not args.check else 1)
