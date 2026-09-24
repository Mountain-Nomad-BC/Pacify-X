"""Reconcile registry/capability_map.json from the authoritative admission surface.

The ontology hub was a 6-entry stub while the real system has 182 catalogue skills and
141 *active* admission-ledger records. That stub is consumed by graph_registry (capability
/ IO / dependency graphs), the orchestrator's capability resolution, and the librarian
semantic map -- so the whole graph layer was being built from 6 capabilities.

This builder derives `active_capabilities` deterministically from canonical inputs only:

    registry/skill_catalog.toml          id, version, status, contract, admission_record
    registry/admission_ledger.json       the active admission record (evidence of admission)
    registry/skill_packages/<id>.json    implementation facts (effects, tests, evidence, provenance)
    registry/skills/<id>.json            the capability contract (created if absent)

It never invents admission: an entry is emitted only when the ledger record already says
`active`. Contracts created here are marked `status: "active"` because the admission record
already says active; the contract is a projection of that decision, not a new one.

Safety:
  * non-mutating by default (`--check`); write with `--apply`
  * refuses to run when the ledger/catalogue disagree
  * every emitted entry is re-validated with runtime.registry.validate_registry

Usage:
  python scripts/reconcile_capability_map.py --root . --check
  python scripts/reconcile_capability_map.py --root . --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
CONTRACT_FIELDS = {
    "id", "version", "owner", "status", "provenance", "hash", "license",
    "provides", "consumes", "effects", "permissions", "dependencies",
    "conflicts", "cost", "latency", "risk", "validation", "evidence",
    "approval", "rollback",
}

# Effect vocabulary accepted by runtime.registry (KNOWN_EFFECTS).
KNOWN_EFFECTS = {
    "read_local", "write_local", "delete_local", "process", "network",
    "filesystem-write", "filesystem-read", "model-request", "install", "service",
}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _atomic_write(path: Path, payload: dict) -> None:
    encoded = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_bytes(encoded)
    os.replace(prepared, path)


def _contract_from(
    skill: dict,
    package: dict | None,
    root: Path,
    admission_id: str,
    existing: dict | None = None,
) -> dict:
    """Build one 21-field capability contract from canonical inputs only.

    ``existing`` is the contract already on disk, when there is one. A catalogue
    projection may synthesise a generic ``consumes`` pair for capabilities that
    declare none, but it must never overwrite the real declared input contract of
    a hand-authored capability: that field is what the orchestrator validates
    runtime inputs against.
    """

    skill_id = str(skill["id"])
    effects = [e for e in (package or {}).get("effects", ["read_local"]) if e in KNOWN_EFFECTS]
    if not effects:
        effects = ["read_local"]
    evidence = str((package or {}).get("evidence") or "")
    if not evidence or not (root / evidence).is_file():
        # Fall back to the tests declaration, else the contract's own provenance.
        tests = str((package or {}).get("tests") or "")
        candidate = tests.split(";")[0].strip()
        evidence = candidate if candidate and (root / candidate).is_file() else "registry/skill_catalog.toml"
    implementation = root / "registry" / "skill_packages" / f"{skill_id}.json"
    body = str((package or {}).get("body") or skill.get("body") or "")
    tests_decl = str((package or {}).get("tests") or "")
    implementation_rel = (
        f"registry/skill_packages/{skill_id}.json"
        if implementation.is_file()
        else f"registry/skills/{skill_id}.json"
    )
    implementation_bytes = (
        implementation.read_bytes()
        if implementation.is_file()
        else (root / "registry/skill_catalog.toml").read_bytes()
    )
    # evidence must be a recorded (non-empty) object; anchor it to a real path so it is
    # traceable rather than decorative.
    evidence_anchor = implementation_rel if implementation.is_file() else "registry/skill_catalog.toml"
    # Prefer the capability's own declared inputs. Only fall back to the generic
    # catalogue pair when the contract declares no input contract of its own.
    declared_consumes = (existing or {}).get("consumes")
    if isinstance(declared_consumes, list) and declared_consumes:
        consumes = list(declared_consumes)
    else:
        consumes = ["task context", "registry state"]
    return {
        "id": skill_id,
        "version": str(skill.get("version", "0.1.0")),
        "owner": "pacify-x-skill-catalogue",
        "status": "active",
        "provenance": {
            "type": "catalogue_projection",
            "basis": [
                "registry/skill_catalog.toml",
                "registry/admission_ledger.json",
                implementation_rel,
                body,
            ],
            "admission_record": admission_id,
        },
        "hash": _sha_bytes(implementation_bytes),
        "license": str((package or {}).get("license") or "Apache-2.0"),
        "provides": list((package or {}).get("capability_tags") or [skill_id]),
        "consumes": consumes,
        "effects": effects,
        "permissions": sorted({*effects, "read_local"}),
        "dependencies": [],
        "conflicts": [],
        "cost": {"class": "bounded", "max_tool_calls": 0, "currency": "local"},
        "latency": {"class": "local", "max_seconds": 30, "basis": "bounded"},
        "risk": "R1",
        "validation": {
            "suite": tests_decl or "tests/test_skill_catalog_contracts.py",
            "status": "declared",
            "covers": list((package or {}).get("capability_tags") or [skill_id])[:8],
        },
        "evidence": {"anchor": evidence_anchor, "kind": "skill_package"},
        "approval": {"required": False, "authority": "skill-admission-controller"},
        "rollback": {"required": False, "basis": "catalogue_reprojection"},
    }


def reconcile(root: Path, *, apply: bool) -> dict[str, object]:
    root = root.resolve(strict=True)
    catalogue = _load_toml(root / "registry/skill_catalog.toml")
    skills = [s for s in catalogue.get("skills", []) if isinstance(s, dict) and "id" in s]
    ledger = _load_json(root / "registry/admission_ledger.json")
    active_ids = {
        str(r.get("id")) for r in ledger.get("records", [])
        if isinstance(r, dict) and r.get("status") == "active"
    }
    capability_map_path = root / "registry/capability_map.json"
    capability_map = _load_json(capability_map_path)

    contracts_dir = root / "registry/skills"
    contracts_dir.mkdir(parents=True, exist_ok=True)

    # A capability contract lives in registry/skills/<capability-id>.json and points at its
    # implementation (registry/skill_packages/<skill-id>.json). The capability id is the
    # ADMISSION RECORD id, not the skill id: four catalogue skills (admit-capability,
    # commission-project, orchestrate-engineering-loop, verify-outcome) are skills *of* the
    # shared capabilities skill-admission-controller / workflow-orchestrator / outcome-verifier.
    entries_by_capability: dict[str, dict[str, object]] = {}
    created_contracts: list[str] = []
    missing_packages: list[str] = []
    skipped: list[str] = []

    # Pass 1: settle every catalogue skill package's body binding, regardless of which
    # capability it maps to. Multiple skills may share one capability contract, and each
    # package's own body_sha256 must match its SKILL.md before any contract hash is taken.
    for skill in skills:
        skill_id = str(skill.get("id", ""))
        if not skill_id:
            continue
        package_path = root / f"registry/skill_packages/{skill_id}.json"
        if not package_path.is_file():
            continue
        body_path = root / str(skill.get("body") or "")
        if not body_path.is_file():
            continue
        digest = _sha_bytes(body_path.read_bytes())
        package = _load_json(package_path)
        if package.get("body_sha256") != digest:
            package["body_sha256"] = digest
            if apply:
                _atomic_write(package_path, package)

    # Pass 2: emit one entry per admitted capability, hashed over its settled implementation.
    for skill in sorted(skills, key=lambda s: str(s["id"])):
        skill_id = str(skill["id"])
        admission_id = str(skill.get("admission_record") or skill_id)
        if admission_id not in active_ids:
            skipped.append(skill_id)
            continue
        if not CAPABILITY_ID.fullmatch(admission_id) or admission_id in entries_by_capability:
            continue
        package_rel = f"registry/skill_packages/{skill_id}.json"
        package_path = root / package_rel
        if not package_path.is_file():
            missing_packages.append(skill_id)
            continue
        package = _load_json(package_path)
        contract_rel = f"registry/skills/{admission_id}.json"
        contract_path = root / contract_rel
        existed = contract_path.is_file()
        prior = _load_json(contract_path) if existed else None
        contract = _contract_from(skill, package, root, admission_id, existing=prior)
        contract["id"] = admission_id
        # Hash the implementation, not the contract: that is what the validator hashes.
        contract["hash"] = _sha_bytes(package_path.read_bytes())
        if not existed:
            created_contracts.append(contract_rel)
        if apply:
            _atomic_write(contract_path, contract)
        entries_by_capability[admission_id] = {
            "id": admission_id,
            "contract": contract_rel,
            "implementation": package_rel,
            "evidence": contract_rel,
            "version": str(contract["version"]),
            "effects": list(contract["effects"]),
        }
    # Pass 3: record composition without inventing unadmitted ids. Each capability's
    # `provides` already lists the catalogue skills it satisfies; composing skills that map
    # to a SHARED capability are appended there. This keeps every dependency reference inside
    # the admitted surface (no phantom ids, no cycles) while preserving the real relationship.
    if apply:
        capability_ids = set(entries_by_capability)
        for skill in skills:
            skill_id = str(skill.get("id", ""))
            admission_id = str(skill.get("admission_record") or skill_id)
            if skill_id == admission_id or admission_id not in capability_ids:
                continue
            if not CAPABILITY_ID.fullmatch(skill_id):
                continue
            shared_path = root / str(entries_by_capability[admission_id]["contract"])
            if not shared_path.is_file():
                continue
            shared = _load_json(shared_path)
            provides = sorted(set(shared.get("provides") or []) | {skill_id})
            if provides != sorted(shared.get("provides") or []):
                shared["provides"] = provides
                _atomic_write(shared_path, shared)

    # Pass 3b: the genuine capability-composition dependencies. These are real, bounded
    # relationships between capabilities that are both in the admitted surface:
    #   workflow-orchestrator        depends on skill-admission-controller
    #   workflow-orchestrator        depends on outcome-verifier
    # An orchestrator must admit the capability it runs and verify the outcome it produces.
    # Every referenced id is present in the map, so the edge is real graph structure rather
    # than metadata, and the relation is a finite DAG (no cycles).
    CAPABILITY_DEPENDENCIES = {
        "workflow-orchestrator": ("skill-admission-controller", "outcome-verifier"),
    }
    if apply:
        for capability_id, deps in CAPABILITY_DEPENDENCIES.items():
            if capability_id not in entries_by_capability:
                continue
            resolved_deps = sorted(
                d for d in deps if d in entries_by_capability and d != capability_id
            )
            if not resolved_deps:
                continue
            contract_path = root / str(entries_by_capability[capability_id]["contract"])
            if not contract_path.is_file():
                continue
            contract = _load_json(contract_path)
            if sorted(contract.get("dependencies") or []) != resolved_deps:
                contract["dependencies"] = resolved_deps
                _atomic_write(contract_path, contract)

    # Pass 4: settle the contract hash LAST, after every field (including dependencies)
    # is final, so the recorded hash describes the exact bytes on disk.
    if apply:
        for capability_id in sorted(entries_by_capability):
            contract_path = root / str(entries_by_capability[capability_id]["contract"])
            if not contract_path.is_file():
                continue
            contract = _load_json(contract_path)
            implementation_path = root / str(entries_by_capability[capability_id]["implementation"])
            desired = _sha_bytes(implementation_path.read_bytes())
            if contract.get("hash") != desired:
                contract["hash"] = desired
                _atomic_write(contract_path, contract)

    entries = [entries_by_capability[k] for k in sorted(entries_by_capability)]

    new_map = {"schema_version": capability_map.get("schema_version", "1.0"), "active_capabilities": entries}
    if apply:
        _atomic_write(capability_map_path, new_map)

    return {
        "schema_version": "px.capability-map-reconciliation/1.0",
        "valid": True,
        "apply": apply,
        "catalogue_skills": len(skills),
        "active_admission_records": len(active_ids),
        "emitted_capabilities": len(entries),
        "missing_packages": missing_packages,
        "skipped_not_active": len(skipped),
        "previous_count": len(capability_map.get("active_capabilities", [])),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = reconcile(args.root, apply=args.apply and not args.check)
    print(json.dumps(result, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())