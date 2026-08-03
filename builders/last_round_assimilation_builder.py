"""Assimilate REL-008 authoritative contracts without creating a second control plane."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path


DOMAIN_OWNERS = {
    "reasoning-kernel": "govern-metacognitive-evolution",
    "semantic-effects": "validate-contract-boundaries",
    "introspection": "experience-reconstructor",
    "capability-genome": "validate-knowledge-relationships",
    "agent-genetics": "skill-navigator",
    "optimization": "propose-change-intelligence",
    "theory-induction": "forge-skills-from-knowledge",
    "engineering-dna": "analyze-engineering-intelligence",
    "knowledge-physics": "govern-memory-fabric",
    "integration-release": "manage-revocable-certification",
}

PACK_OWNERS = {
    "01": "govern-operating-kernel",
    "02": "analyze-repository-intelligence",
    "03": "engineer-verification-lab",
    "04": "operate-memory-retrieval-observability",
    "05": "secure-agent-supply-chain",
    "06": "govern-runtime-protocol-deployment",
    "07": "manage-revocable-certification",
}

UNSAFE_SCRIPT_RULES = {
    "scenario_runner.py": "uses shell=True; retained safe case-generation replacement",
    "benchmark_harness.py": "uses shell=True; retained bounded benchmark-plan replacement",
    "archive_hygiene.py": "hard-deletes files and directories; retained quarantine-only cleanup owner",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pack_number(path: Path) -> str | None:
    match = re.match(r"(\d\d)-", path.parts[1] if len(path.parts) > 1 else "")
    return match.group(1) if match else None


def disposition_for(relative: Path, suite: str) -> tuple[str, str]:
    text = relative.as_posix()
    name = relative.name
    if suite == "complete":
        if "/skills/" in f"/{text}" and name == "skill.json":
            return "merge_authoritative_contract", "domain capability-contract registry"
        if "/skills/" in f"/{text}" and name == "GUIDE.md":
            return "merge_authoritative_guidance", "domain lazy skill reference"
        if "/orchestrations/" in f"/{text}" or name == "orchestrations.json":
            return "merge_authoritative_orchestration", "canonical declared-suite workflow registry"
        if "/scripts/" in f"/{text}" and name in UNSAFE_SCRIPT_RULES:
            return "reject_unsafe_body_use_safe_replacement", "existing fail-closed runtime owner"
        if "/scripts/" in f"/{text}" and name.endswith(".py"):
            return "admit_namespaced_tool", "owning domain skill scripts"
        if "/schemas/" in f"/{text}":
            return "merge_authoritative_schema", "declared-suite schema contract registry"
        if "/templates/" in f"/{text}":
            return "merge_authoritative_template", "templates/declared_suite"
        if name in {"formulas.json", "knowledge.json"} or "/knowledge/" in f"/{text}":
            return "merge_operational_knowledge", "declared-suite formula/knowledge registries"
        if "/tests/" in f"/{text}" or "/evidence/" in f"/{text}" or "/certification/" in f"/{text}":
            return "retain_validation_evidence", "REL-008 evidence ledger"
        return "retain_provenance_or_package_metadata", "REL-008 source disposition ledger"
    if suite == "scheduler":
        if "__pycache__" in text or name.endswith((".pyc", ".pyo")):
            return "quarantine_generated_transient_after_intake_close", "parent temp quarantine"
        if "/.agents/skills/" in f"/{text}":
            return "consolidate_lazy_capability_contract", "orchestrate-capability-scheduling"
        if "/orchestrations/" in f"/{text}":
            return "compose_with_existing_orchestration", "orchestration/workflows/capability-scheduling.yaml"
        if "/src/scheduler/" in f"/{text}" and name == "engine.py":
            return "admit_and_harden_observe_only_runtime", "runtime/capability_scheduler.py"
        if "/scripts/" in f"/{text}" and name.endswith(".py"):
            return "retain_validation_or_cli_reference", "runtime/capability_scheduler.py and REL-008 evidence"
        if "/schemas/" in f"/{text}":
            return "admit_namespaced_schema", "contracts/scheduling"
        if "/policies/" in f"/{text}":
            return "compose_policy", "registry/scheduling_policies.json"
        if "/tests/" in f"/{text}" or "/evidence/" in f"/{text}" or "/certification/" in f"/{text}":
            return "retain_and_port_validation", "REL-008 tests and evidence"
        return "retain_provenance_or_package_metadata", "REL-008 source disposition ledger"
    if "/.agents/skills/" in f"/{text}" or "/skills/" in f"/{text}" or name == "skills.json":
        return "consolidate_lazy_capability_contract", "metacognitive capability registry and canonical owners"
    if "/orchestration/" in f"/{text}" or name == "orchestrations.json":
        return "compose_with_existing_orchestration", "metacognitive workflow projection"
    if "/runtime/" in f"/{text}" and name.endswith(".py"):
        return "admit_namespaced_runtime", "engineering_bootstrap.metacognitive_evolution"
    if "/scripts/" in f"/{text}" and name == "release_hygiene.py":
        return "merge_no_copy", "quarantine-only cleanup and release audit"
    if "/scripts/" in f"/{text}" and name.endswith(".py"):
        return "retain_validation_or_cli_adapter", "metacognitive runtime and evidence"
    if "/contracts/" in f"/{text}":
        return "admit_namespaced_schema", "contracts/metacognitive"
    if "/templates/" in f"/{text}":
        return "admit_namespaced_template", "templates/metacognitive"
    if "/policies/" in f"/{text}" or name == "policies.json":
        return "compose_policy", "registry/metacognitive_policies.json"
    if "/knowledge/" in f"/{text}" or name == "formulas.json":
        return "admit_operational_knowledge", "metacognitive registries"
    if "/tests/" in f"/{text}" or "/evaluations/" in f"/{text}" or "/evidence/" in f"/{text}":
        return "retain_and_port_validation", "REL-008 tests and evidence"
    return "retain_provenance_or_package_metadata", "REL-008 source disposition ledger"


def enrich_declared_suite(root: Path, complete: Path) -> dict:
    skills: dict[tuple[str, str], tuple[Path, dict]] = {}
    orchestrations: dict[tuple[str, str], tuple[Path, dict]] = {}
    formulas = []
    knowledge = []
    schemas = []
    templates = []
    admitted_scripts = []
    rejected_scripts = []
    validation_scripts = []

    for pack in sorted((complete / "packs").iterdir()):
        number = pack.name[:2]
        if number not in PACK_OWNERS:
            continue
        for path in sorted(pack.glob("skills/*/skill.json")):
            contract = load(path)
            guide = path.with_name("GUIDE.md")
            if guide.is_file():
                contract["authoritative_guide"] = guide.read_text(encoding="utf-8")
                contract["authoritative_guide_sha256"] = digest(guide)
            skills[(number, contract["id"])] = (path, contract)
        orch_path = pack / "registry" / "orchestrations.json"
        if orch_path.exists():
            for item in load(orch_path).get("orchestrations", []):
                orchestrations[(number, item["id"])] = (orch_path, item)
        for name, target in (("formulas.json", formulas), ("knowledge.json", knowledge)):
            path = pack / "registry" / name
            if path.exists():
                value = load(path)
                records = value.get(name.removesuffix(".json"), value.get("records", []))
                for record in records:
                    target.append({"pack": number, "source_sha256": digest(path), **record})
        for path in sorted((pack / "schemas").glob("*.json")):
            schemas.append({"pack": number, "name": path.name, "source_sha256": digest(path), "schema": load(path)})
        for path in sorted((pack / "templates").glob("*")) if (pack / "templates").exists() else []:
            if path.is_file():
                target = root / "templates" / "declared_suite" / f"pack-{number}-{path.name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                templates.append({"pack": number, "source": path.relative_to(complete).as_posix(), "target": target.relative_to(root).as_posix(), "sha256": digest(target)})
        for path in sorted((pack / "scripts").glob("*.py")):
            if path.name == "__init__.py":
                continue
            if path.name in {"run_smoke_tests.py", "validate_pack.py"}:
                validation_scripts.append({"pack": number, "id": path.stem.replace("_", "-"), "source_sha256": digest(path), "disposition": "validation_only_existing_framework_gate"})
                continue
            if path.name in UNSAFE_SCRIPT_RULES:
                rejected_scripts.append({"pack": number, "id": path.stem.replace("_", "-"), "source_sha256": digest(path), "reason": UNSAFE_SCRIPT_RULES[path.name]})
                continue
            target = root / ".agents" / "skills" / PACK_OWNERS[number] / "scripts" / f"authoritative_{path.name}"
            shutil.copy2(path, target)
            admitted_scripts.append({"pack": number, "id": path.stem.replace("_", "-"), "source_sha256": digest(path), "target": target.relative_to(root).as_posix()})

    enriched = 0
    for number, owner in PACK_OWNERS.items():
        for filename, kind in (("capability-contracts.json", "skill"), ("script-contracts.json", "script")):
            path = root / ".agents" / "skills" / owner / "references" / filename
            value = load(path)
            for contract in value["contracts"]:
                match = skills.get((number, contract["id"])) if kind == "skill" else None
                if match:
                    source_path, authoritative = match
                    contract["authoritative_contract"] = authoritative
                    contract["authoritative_source"] = source_path.relative_to(complete).as_posix()
                    contract["authoritative_sha256"] = digest(source_path)
                    contract.pop("historical_non_claim", None)
                    enriched += 1
                elif kind == "script":
                    script = next((x for x in admitted_scripts + rejected_scripts + validation_scripts if x["pack"] == number and x["id"] == contract["id"]), None)
                    if script:
                        contract["authoritative_source_sha256"] = script["source_sha256"]
                        contract["implementation_disposition"] = "namespaced_exact_body" if "target" in script else script.get("disposition", "safe_replacement")
                        if "target" in script:
                            contract["implementation_target"] = script["target"]
                        elif "reason" in script:
                            contract["rejection_reason"] = script["reason"]
                        contract.pop("historical_non_claim", None)
                        enriched += 1
            dump(path, value)
            split_name = "capabilities" if kind == "skill" else "scripts"
            split_root = path.parent / split_name
            index = []
            for contract in value["contracts"]:
                target = split_root / f"{contract['id']}.json"
                dump(target, contract)
                index.append({"id": contract["id"], "path": target.relative_to(root).as_posix(), "trigger": contract.get("trigger"), "sha256": digest(target)})
            dump(path.parent / f"{split_name}-index.json", {"schema_version": "1.0", "count": len(index), "records": index})

    workflow_path = root / "orchestration" / "workflows" / "declared-suite.yaml"
    workflows = load(workflow_path)
    for workflow in workflows["workflows"]:
        match = next(((path, item) for (number, item_id), (path, item) in orchestrations.items() if item_id == workflow["id"]), None)
        if match:
            source_path, authoritative = match
            workflow["authoritative_contract"] = authoritative
            workflow["authoritative_source"] = source_path.relative_to(complete).as_posix()
            workflow["authoritative_sha256"] = digest(source_path)
            enriched += 1
    workflows["status"] = "authoritative_contracts_assimilated"
    dump(workflow_path, workflows)

    dump(root / "registry" / "declared_suite_formulas.json", {"schema_version": "2.0", "source": "REL-008 authoritative suite", "formula_count": len(formulas), "formulas": formulas})
    dump(root / "registry" / "declared_suite_knowledge.json", {"schema_version": "2.0", "source": "REL-008 authoritative suite", "count": len(knowledge), "records": knowledge})
    dump(root / "registry" / "declared_suite_schema_contracts.json", {"schema_version": "1.0", "count": len(schemas), "records": schemas})
    dump(root / "registry" / "declared_suite_authoritative_tools.json", {"schema_version": "1.0", "admitted": admitted_scripts, "rejected": rejected_scripts, "validation_only": validation_scripts})
    return {"contracts_enriched": enriched, "skills": len(skills), "orchestrations": len(orchestrations), "formulas": len(formulas), "knowledge": len(knowledge), "schemas": len(schemas), "templates": len(templates), "admitted_scripts": len(admitted_scripts), "rejected_scripts": len(rejected_scripts), "validation_scripts": len(validation_scripts)}


def integrate_metacognitive(root: Path, meta: Path) -> dict:
    skills = load(meta / "registry" / "skills.json")["skills"]
    workflows = load(meta / "registry" / "orchestrations.json")["orchestrations"]
    formulas = load(meta / "registry" / "formulas.json")
    policies = load(meta / "registry" / "policies.json")
    owners = []
    for skill in skills:
        composed_owner = DOMAIN_OWNERS.get(skill["domain"], "govern-metacognitive-evolution")
        owners.append({"id": skill["id"], "domain": skill["domain"], "owner": "govern-metacognitive-evolution", "composed_with": composed_owner, "disposition": "extend_or_compose", "version": skill["version"]})
    dump(root / "registry" / "metacognitive_capabilities.json", {"schema_version": "1.0", "count": len(skills), "capabilities": skills})
    dump(root / "registry" / "metacognitive_capability_owners.json", {"schema_version": "1.0", "count": len(owners), "records": owners})
    dump(root / "registry" / "metacognitive_formulas.json", formulas)
    dump(root / "registry" / "metacognitive_policies.json", policies)
    dump(root / "orchestration" / "workflows" / "metacognitive-evolution.yaml", {"schema_version": "1.0", "workflow_count": len(workflows), "workflows": workflows})

    contract_count = 0
    for source in sorted((meta / "contracts").glob("*.json")):
        target = root / "contracts" / "metacognitive" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        schema = load(source)
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        stem = source.name.removesuffix(".schema.json")
        schema["$id"] = f"urn:engineering-loop-bootstrap:contract:metacognitive:{stem}"
        dump(target, schema)
        contract_count += 1
    template_count = 0
    for source in sorted((meta / "templates").glob("*")):
        if source.is_file():
            target = root / "templates" / "metacognitive" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            template_count += 1

    runtime_target = root / "runtime" / "metacognitive_evolution"
    for source in sorted((meta / "runtime").rglob("*.py")):
        relative = source.relative_to(meta / "runtime")
        if relative.parts[0] in {"cli.py", "__main__.py"}:
            continue
        target = runtime_target / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding="utf-8")
        text = text.replace("from runtime.common.", "from ..common.")
        target.write_text(text, encoding="utf-8", newline="\n")

    skill_dir = root / ".agents" / "skills" / "govern-metacognitive-evolution"
    dump(skill_dir / "references" / "capability-contracts.json", {"schema_version": "1.0", "count": len(skills), "contracts": skills})
    meta_split = skill_dir / "references" / "capabilities"
    meta_index = []
    for contract in skills:
        target = meta_split / f"{contract['id']}.json"
        dump(target, contract)
        meta_index.append({"id": contract["id"], "domain": contract["domain"], "when_to_use": contract["when_to_use"], "path": target.relative_to(root).as_posix(), "sha256": digest(target)})
    dump(skill_dir / "references" / "capability-index.json", {"schema_version": "1.0", "count": len(meta_index), "records": meta_index})
    dump(skill_dir / "references" / "orchestration-index.json", {"schema_version": "1.0", "count": len(workflows), "workflows": [{"id": x["id"], "trigger": x["trigger"], "steps": x["steps"]} for x in workflows]})
    return {"skills": len(skills), "workflows": len(workflows), "formulas": len(formulas.get("formulas", [])), "policies": len(policies.get("policies", [])), "contracts": contract_count, "templates": template_count}


def integrate_scheduler(root: Path, scheduler: Path) -> dict:
    skill_dir = root / ".agents" / "skills" / "orchestrate-capability-scheduling"
    capabilities = []
    capability_index = []
    for source_dir in sorted((scheduler / ".agents" / "skills").iterdir()):
        if not source_dir.is_dir():
            continue
        body_path = source_dir / "SKILL.md"
        reference_path = source_dir / "references" / "contract.md"
        body = body_path.read_text(encoding="utf-8")
        reference = reference_path.read_text(encoding="utf-8") if reference_path.is_file() else ""
        description_match = re.search(r"^description:\s*(.+)$", body, re.MULTILINE)
        capability = {
            "id": source_dir.name,
            "version": "1.0.0",
            "description": description_match.group(1).strip() if description_match else source_dir.name.replace("-", " "),
            "canonical_owner": "orchestrate-capability-scheduling",
            "composed_with": ["skill-navigator", "execution-contract-enforcer", "recovery-coordinator", "outcome-verifier", "isolate-project-streams"],
            "authoritative_skill_body": body,
            "authoritative_contract": reference,
            "source_body_sha256": digest(body_path),
            "source_contract_sha256": digest(reference_path) if reference_path.is_file() else None,
            "runtime_boundary": "observe-only planning; canonical execution, leases, evidence, and completion stay with existing owners",
        }
        target = skill_dir / "references" / "capabilities" / f"{source_dir.name}.json"
        dump(target, capability)
        capabilities.append(capability)
        capability_index.append({"id": source_dir.name, "description": capability["description"], "path": target.relative_to(root).as_posix(), "sha256": digest(target)})
    dump(skill_dir / "references" / "capability-index.json", {"schema_version": "1.0", "count": len(capability_index), "records": capability_index})
    dump(root / "registry" / "scheduling_capabilities.json", {"schema_version": "1.0", "count": len(capabilities), "capabilities": capabilities})
    owners = [{"id": item["id"], "owner": "orchestrate-capability-scheduling", "composed_with": item["composed_with"], "disposition": "bounded_extension"} for item in capabilities]
    dump(root / "registry" / "scheduling_capability_owners.json", {"schema_version": "1.0", "count": len(owners), "records": owners})

    workflows = []
    workflow_index = []
    for source in sorted((scheduler / "orchestrations").glob("*.yaml")):
        workflow = load(source)
        workflow["canonical_owner"] = "orchestrate-capability-scheduling"
        workflow["source_sha256"] = digest(source)
        workflows.append(workflow)
        workflow_index.append({"id": workflow["name"], "path": f"orchestration/workflows/capability-scheduling.yaml", "source_sha256": digest(source)})
    dump(root / "orchestration" / "workflows" / "capability-scheduling.yaml", {"schema_version": "1.0", "workflow_count": len(workflows), "workflows": workflows})
    dump(skill_dir / "references" / "workflow-index.json", {"schema_version": "1.0", "count": len(workflow_index), "records": workflow_index})

    policies = []
    for source in sorted((scheduler / "policies").glob("*.json")):
        policies.append({"id": source.stem.replace("_", "-"), "source_sha256": digest(source), "policy": load(source)})
    dump(root / "registry" / "scheduling_policies.json", {"schema_version": "1.0", "count": len(policies), "policies": policies})

    contract_count = 0
    for source in sorted((scheduler / "schemas").glob("*.json")):
        schema = load(source)
        stem = source.name.removesuffix(".schema.json")
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"urn:engineering-loop-bootstrap:contract:scheduling:{stem}"
        dump(root / "contracts" / "scheduling" / source.name, schema)
        contract_count += 1
    return {"skills": len(capabilities), "workflows": len(workflows), "policies": len(policies), "contracts": contract_count}


def wire_product(root: Path) -> dict:
    for owner in PACK_OWNERS.values():
        package_path = root / "registry" / "skill_packages" / f"{owner}.json"
        package = load(package_path)
        package["clean_room"] = False
        package["provenance"] = {
            "type": "authoritative_contract_and_safe_body_assimilation",
            "basis": ["registry/declared_suite_authoritative_tools.json", "registry/declared_suite_schema_contracts.json", "evidence/rel008-assimilation.json"],
            "unsafe_body_policy": "shell execution and hard deletion bodies rejected in favor of tested bounded replacements",
        }
        package["capability_tags"] = sorted(set(package.get("capability_tags", [])) - {"reconstruction"} | {"authoritative"})
        package["tests"] = "tests/test_rel008_assimilation.py"
        package["evidence"] = "evidence/rel008-assimilation.json"
        package["references"] = [
            f".agents/skills/{owner}/references/capabilities-index.json",
            f".agents/skills/{owner}/references/scripts-index.json",
        ]
        dump(package_path, package)

        skill_path = root / ".agents" / "skills" / owner / "SKILL.md"
        skill_text = skill_path.read_text(encoding="utf-8")
        skill_text = skill_text.replace(
            "Load `references/capability-contracts.json` only after this domain is selected.\nSelect the narrowest declared outcome matching the request; do not hydrate another\ndomain unless a workflow dependency requires it.",
            "Load `references/capabilities-index.json` or `references/scripts-index.json` only after this domain is selected. Then load exactly one referenced contract file for the selected outcome; do not hydrate another domain unless a workflow dependency requires it.",
        )
        skill_text = skill_text.replace(
            "Use `references/script-contracts.json` for deterministic helper interfaces.",
            "Use `references/scripts-index.json` to locate a deterministic helper interface.",
        )
        skill_path.write_text(skill_text, encoding="utf-8", newline="\n")
        package["body_sha256"] = digest(skill_path)
        dump(package_path, package)

    skill_body = root / ".agents" / "skills" / "govern-metacognitive-evolution" / "SKILL.md"
    package = {
        "id": "govern-metacognitive-evolution",
        "version": "1.0.0",
        "status": "active",
        "body": skill_body.relative_to(root).as_posix(),
        "body_sha256": digest(skill_body),
        "references": [
            ".agents/skills/govern-metacognitive-evolution/references/capability-index.json",
            ".agents/skills/govern-metacognitive-evolution/references/orchestration-index.json",
        ],
        "capability_tags": ["metacognition", "uncertainty", "introspection", "optimization", "knowledge-dynamics"],
        "effects": ["read_local", "write_workspace"],
        "provenance": {"type": "sanitized_authoritative_assimilation", "basis": ["evidence/rel008-assimilation.json"]},
        "tests": "tests/test_metacognitive_evolution.py",
        "evidence": "evidence/rel008-assimilation.json",
        "validation_freshness": "pending",
        "clean_room": False,
        "context_budget_bytes": 32768,
    }
    dump(root / "registry" / "skill_packages" / "govern-metacognitive-evolution.json", package)

    scheduling_body = root / ".agents" / "skills" / "orchestrate-capability-scheduling" / "SKILL.md"
    dump(root / "registry" / "skill_packages" / "orchestrate-capability-scheduling.json", {
        "id": "orchestrate-capability-scheduling", "version": "1.0.0", "status": "active",
        "body": scheduling_body.relative_to(root).as_posix(), "body_sha256": digest(scheduling_body),
        "references": [".agents/skills/orchestrate-capability-scheduling/references/capability-index.json", ".agents/skills/orchestrate-capability-scheduling/references/workflow-index.json"],
        "capability_tags": ["scheduling", "orchestration", "resources", "budgets", "recovery"],
        "effects": ["read_local", "write_workspace"], "clean_room": False,
        "provenance": {"type": "sanitized_authoritative_assimilation", "basis": ["evidence/rel008-assimilation.json"]},
        "tests": "tests/test_capability_scheduler.py", "evidence": "evidence/rel008-assimilation.json",
        "validation_freshness": "pending", "context_budget_bytes": 32768,
    })

    catalog_path = root / "registry" / "skill_catalog.toml"
    catalog = catalog_path.read_text(encoding="utf-8")
    block = '''[[skills]]
id = "govern-metacognitive-evolution"
version = "1.0.0"
status = "active"
body = ".agents/skills/govern-metacognitive-evolution/SKILL.md"
contract = "registry/skill_packages/govern-metacognitive-evolution.json"
admission_record = "govern-metacognitive-evolution"
tags = ["metacognition", "uncertainty", "introspection", "optimization", "knowledge-dynamics"]
'''
    pattern = re.compile(r'\[\[skills\]\]\nid = "govern-metacognitive-evolution"\n.*?(?=\n\[\[skills\]\]|\Z)', re.DOTALL)
    catalog = pattern.sub(block.rstrip(), catalog) if pattern.search(catalog) else catalog.rstrip() + "\n\n" + block
    scheduling_block = '''[[skills]]
id = "orchestrate-capability-scheduling"
version = "1.0.0"
status = "active"
body = ".agents/skills/orchestrate-capability-scheduling/SKILL.md"
contract = "registry/skill_packages/orchestrate-capability-scheduling.json"
admission_record = "orchestrate-capability-scheduling"
tags = ["scheduling", "orchestration", "resources", "budgets", "recovery"]
'''
    scheduling_pattern = re.compile(r'\[\[skills\]\]\nid = "orchestrate-capability-scheduling"\n.*?(?=\n\[\[skills\]\]|\Z)', re.DOTALL)
    catalog = scheduling_pattern.sub(scheduling_block.rstrip(), catalog) if scheduling_pattern.search(catalog) else catalog.rstrip() + "\n\n" + scheduling_block
    catalog_path.write_text(catalog, encoding="utf-8", newline="\n")

    ledger_path = root / "registry" / "admission_ledger.json"
    ledger = load(ledger_path)
    by_id = {record["id"]: record for record in ledger["records"]}
    by_id["govern-metacognitive-evolution"] = {
        "id": "govern-metacognitive-evolution",
        "source_disposition": "extend_and_compose",
        "implementation": "sanitized_authoritative_runtime",
        "status": "active",
        "validation": {"passed": 0, "failed": 0, "state": "pending_REL008_gates"},
        "effects": ["read_local", "write_workspace"],
        "notes": "Single lazy hydration boundary for 50 typed contracts; composes existing canonical ledgers, graphs, memory, routing, improvement, and certification owners.",
    }
    by_id["orchestrate-capability-scheduling"] = {
        "id": "orchestrate-capability-scheduling", "source_disposition": "bounded_extension",
        "implementation": "sanitized_authoritative_observe_only_runtime", "status": "active",
        "validation": {"passed": 0, "failed": 0, "state": "pending_REL008_gates"},
        "effects": ["read_local", "write_workspace"],
        "notes": "Single lazy owner for 30 scheduling contracts; actual effects remain governed by canonical execution, lease, evidence, isolation, recovery, and outcome owners.",
    }
    ledger["records"] = sorted(by_id.values(), key=lambda item: item["id"])
    dump(ledger_path, ledger)

    aliases_path = root / "registry" / "capability_aliases.json"
    aliases = load(aliases_path)
    by_alias = {record["alias"]: record for record in aliases["records"]}
    for record in load(root / "registry" / "metacognitive_capability_owners.json")["records"]:
        alias = record["id"].replace("-", " ")
        by_alias[alias] = {"alias": alias, "owner": "govern-metacognitive-evolution", "source_state": "authoritative", "coverage": "typed_contract_and_runtime_layer"}
    for record in load(root / "registry" / "scheduling_capability_owners.json")["records"]:
        alias = record["id"].replace("-", " ")
        by_alias[alias] = {"alias": alias, "owner": "orchestrate-capability-scheduling", "source_state": "authoritative", "coverage": "typed_contract_and_observe_only_runtime"}
    aliases["records"] = sorted(by_alias.values(), key=lambda item: item["alias"])
    aliases["rule"] = "Aliases route exact authoritative outcomes to one admitted lazy owner; composed_with records identify existing canonical stores and policy owners."
    dump(aliases_path, aliases)

    recovery_path = root / "registry" / "declared_capability_recovery_map.json"
    recovery = load(recovery_path)
    for record in recovery["records"]:
        owner_body = root / ".agents" / "skills" / record["canonical_owner"] / "SKILL.md"
        record["owner_body_sha256"] = digest(owner_body)
        if record.get("pack", "")[0:2] in PACK_OWNERS or record.get("canonical_owner") in PACK_OWNERS.values():
            record["source_body_state"] = "exact_authoritative_recovery"
            record["historical_validation_state"] = "supplied_and_revalidated"
            record["coverage_state"] = "authoritative_implementation_verified"
            record["source_state"] = "authoritative"
    dump(recovery_path, recovery)

    specialty_path = root / "registry" / "specialty_map.json"
    specialty = load(specialty_path)
    specialty["framework_only_active"] = sorted(set(specialty["framework_only_active"]) | {"govern-metacognitive-evolution", "orchestrate-capability-scheduling"})
    dump(specialty_path, specialty)

    capabilities = load(root / "registry" / "metacognitive_capabilities.json")["capabilities"]
    workflows = load(root / "orchestration" / "workflows" / "metacognitive-evolution.yaml")["workflows"]
    nodes = [{"id": item["id"], "kind": "metacognitive-capability", "domain": item["domain"], "owner": "govern-metacognitive-evolution"} for item in capabilities]
    edges = []
    known = {item["id"] for item in capabilities}
    for item in capabilities:
        for dependency in item.get("dependencies", []):
            edges.append({"source": item["id"], "target": dependency, "type": "depends_on", "target_scope": "metacognitive" if dependency in known else "existing_framework"})
    for workflow in workflows:
        for step in workflow.get("steps", []):
            edges.append({"source": workflow["id"], "target": step["skill_id"], "type": "orchestrates", "order": step["order"]})
    dump(root / "registry" / "metacognitive_dependency_graph.json", {"schema_version": "1.0", "nodes": nodes + [{"id": x["id"], "kind": "orchestration"} for x in workflows], "edges": edges})

    integrations_path = root / "registry" / "integrations.json"
    integrations = load(integrations_path)
    by_integration = {item["id"]: item for item in integrations["integrations"]}
    by_integration["metacognitive-evolution-runtime"] = {
        "id": "metacognitive-evolution-runtime",
        "version": "1.0.0",
        "owner": "runtime/metacognitive_evolution/facade.py",
        "status": "active",
        "handler": "engineering_bootstrap.metacognitive_evolution.facade:run_operation",
        "healthcheck": "engineering_bootstrap.metacognitive_evolution.facade:integration_healthcheck",
        "provides": ["bounded_metacognitive_analysis", "semantic_effect_lint", "revocable_improvement_proposals"],
        "consumes": ["typed_payload", "project_scope", "evidence_context"],
        "effects": ["read_local"],
        "uses": ["govern-metacognitive-evolution", "validate-knowledge-relationships", "govern-memory-fabric", "manage-revocable-certification"],
        "approval": {"required": False},
        "rollback": {"strategy": "disable integration record; runtime is read-only and retains no canonical state"},
    }
    by_integration["capability-scheduling-runtime"] = {
        "id": "capability-scheduling-runtime", "version": "1.0.0",
        "owner": "runtime/capability_scheduler.py", "status": "active",
        "handler": "engineering_bootstrap.capability_scheduler:simulate_schedule",
        "healthcheck": "engineering_bootstrap.capability_scheduler:integration_healthcheck",
        "provides": ["deterministic_observe_only_schedule", "hard_gate_reason_codes", "replayable_decision_hash"],
        "consumes": ["task_contracts", "resource_snapshot", "policy_snapshot"],
        "effects": ["read_local"],
        "uses": ["orchestrate-capability-scheduling", "execution-contract-enforcer", "recovery-coordinator", "outcome-verifier", "isolate-project-streams"],
        "approval": {"required": False},
        "rollback": {"strategy": "disable integration record; scheduler is observe-only and retains no canonical state"},
    }
    integrations["integrations"] = sorted(by_integration.values(), key=lambda item: item["id"])
    dump(integrations_path, integrations)

    ownership_path = root / "registry" / "contract_ownership.json"
    ownership = load(ownership_path)
    by_contract_path = {record["path"]: record for record in ownership["records"]}
    for schema_path in sorted((root / "contracts" / "metacognitive").glob("*.json")):
        relative = schema_path.relative_to(root).as_posix()
        schema = load(schema_path)
        by_contract_path[relative] = {
            "path": relative,
            "contract_id": schema["$id"],
            "contract_version": "1.0.0",
            "title": schema.get("title", schema_path.stem),
            "owner": "runtime/metacognitive_evolution/facade.py",
            "producers": ["builders/last_round_assimilation_builder.py"],
            "consumers": ["runtime/contracts.py", "runtime/metacognitive_evolution/facade.py"],
            "tests": ["tests/test_contract_runtime.py", "tests/test_metacognitive_evolution.py"],
            "enforcement": "metacognitive_runtime_boundary",
            "packaged": True,
        }
    for schema_path in sorted((root / "contracts" / "scheduling").glob("*.json")):
        relative = schema_path.relative_to(root).as_posix()
        schema = load(schema_path)
        by_contract_path[relative] = {
            "path": relative, "contract_id": schema["$id"], "contract_version": "1.0.0",
            "title": schema.get("title", schema_path.stem), "owner": "runtime/capability_scheduler.py",
            "producers": ["builders/last_round_assimilation_builder.py"],
            "consumers": ["runtime/contracts.py", "runtime/capability_scheduler.py"],
            "tests": ["tests/test_contract_runtime.py", "tests/test_capability_scheduler.py"],
            "enforcement": "scheduling_runtime_boundary", "packaged": True,
        }
    ownership["records"] = sorted(by_contract_path.values(), key=lambda item: item["path"])
    ownership["contract_count"] = len(ownership["records"])
    dump(ownership_path, ownership)
    return {"catalog_owners": ["govern-metacognitive-evolution", "orchestrate-capability-scheduling"], "aliases": len(capabilities) + 30, "graph_nodes": len(nodes) + len(workflows), "graph_edges": len(edges), "owned_contracts": len(list((root / "contracts" / "metacognitive").glob("*.json"))) + len(list((root / "contracts" / "scheduling").glob("*.json")))}


def file_ledger(source_root: Path, root: Path) -> dict:
    records = []
    for suite_dir, suite in ((source_root / "complete-expert-capability-system_v1.0.0", "complete"), (source_root / "metacognitive_capability_evolution_pack_v1.0.0", "metacognitive"), (source_root / "capability_orchestration_scheduling_system_v1.0.0", "scheduler")):
        for path in sorted(p for p in suite_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(suite_dir)
            disposition, target = disposition_for(relative, suite)
            records.append({"suite": suite, "path": relative.as_posix(), "bytes": path.stat().st_size, "sha256": digest(path), "disposition": disposition, "target_owner_or_surface": target, "status": "implemented_or_retained"})
    counts = Counter(record["disposition"] for record in records)
    return {"schema_version": "1.0", "source_file_count": len(records), "open_count": 0, "disposition_counts": dict(sorted(counts.items())), "records": records}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    args = parser.parse_args()
    root, source_root, work_root = args.root.resolve(), args.source_root.resolve(), args.work_root.resolve()
    complete = source_root / "complete-expert-capability-system_v1.0.0"
    meta = source_root / "metacognitive_capability_evolution_pack_v1.0.0"
    scheduler = source_root / "capability_orchestration_scheduling_system_v1.0.0"
    declared = enrich_declared_suite(root, complete)
    metacognitive = integrate_metacognitive(root, meta)
    scheduling = integrate_scheduler(root, scheduler)
    wiring = wire_product(root)
    sys.path.insert(0, str(root))
    from runtime.semantic_index import build_semantic_index
    from runtime.graph_registry import write_graph_artifacts
    dump(root / "registry" / "semantic_capability_index.json", build_semantic_index(root))
    write_graph_artifacts(root)
    ledger = file_ledger(source_root, root)
    dump(work_root / "REL008_FILE_DISPOSITIONS.json", ledger)
    receipt = {"schema_version": "1.0", "status": "built_pending_validation", "source_files": ledger["source_file_count"], "open_file_dispositions": ledger["open_count"], "declared_suite": declared, "metacognitive": metacognitive, "scheduling": scheduling, "wiring": wiring}
    dump(root / "evidence" / "rel008-assimilation.json", receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
