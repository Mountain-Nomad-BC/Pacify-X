"""PX-OS-1067 — build the auditable registries the handoff requires.

Three artifacts, all evidence-only:

1. `px-os-1067-b7-owner-decision-register.json`
   One decision row per B7 resource (32), carrying the matrix's evidence, the candidate
   owner, an explicit `approved | rejected | pending` state, and the rule that fixes each
   state. Nothing is approved here.

2. `px-os-1067-producer-dispositions.json`
   One row per mutating producer (373) drawn from the canonical census: family, the
   artifacts that account for it, its disposition, and — when still unresolved — the
   precise missing authority.

3. `px-os-1067-authority-contract.json`
   The catalog of authority sources a producer disposition may cite. A row may only claim
   `resolved` by citing one of these; every entry names the file that makes it real.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-build-registries.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from runtime.effect_surface import discover_effect_surfaces  # noqa: E402
from runtime.mutating_producer_registry import (  # noqa: E402
    default_classification,
    discover_mutating_producers,
)

CENSUS = EVIDENCE / "px-os-1067-census-2026-11-03.json"
MATRIX = EVIDENCE / "px-os-1067-runtime-state-ownership-matrix.json"
PX_AUDIT = EVIDENCE / "px-os-1067-px-skills-owner-audit.json"
INERT = EVIDENCE / "px-os-1067-inert-fingerprint-dispositions.json"
REGISTRY_CANDIDATE = EVIDENCE / "px-os-1067-runtime-state-ownership-registry-candidate.json"
OUTPUT_ROOTS = ROOT / "registry/producer_output_roots.json"


def sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


authority_contract = {
    "schema_version": "px.producer-disposition-authority/1.0",
    "gap_id": "PX-OS-1067",
    "purpose": (
        "A producer may be reported resolved only by citing one of these authority sources. "
        "Each source is a repository file that a reviewer can open; none is an inference from "
        "a folder name, an import, or a passing write."
    ),
    "authority_sources": [
        {
            "id": "canonical_lease_intent_owner",
            "effect": "leased",
            "where": "runtime/mutating_producer_registry.py::GUARDED_MUTATING_OWNERS",
            "rule": "Producer bytes equal the shipped native owner and it uses lease+intent.",
            "verify": "default_classification returns this reason for the current hash.",
        },
        {
            "id": "canonical_control_custody_owner",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::NATIVE_CONTROL_CUSTODY_OWNERS",
            "rule": "Native control-plane bootstrap custody, byte-identical to the shipped owner.",
            "verify": "default_classification returns this reason for the current hash.",
        },
        {
            "id": "delegated_publication",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::_delegated_publication_verdict",
            "rule": (
                "The caller imports and calls the canonical publication owner and has no other "
                "filesystem mutation. Evaluated live from source on every run."
            ),
            "verify": "Live verdict — a table entry alone cannot resolve the producer.",
        },
        {
            "id": "reviewed_control_custody",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_CONTROL_CUSTODY",
            "rule": "Individually reviewed control-plane custody pinned by source hash.",
            "verify": "Hash equality with the pinned entry.",
        },
        {
            "id": "declared_output_target",
            "effect": "exempt",
            "where": "runtime/mutating_producer_custody_reviewed.py::DECLARED_OUTPUT_TARGET_RECONCILED",
            "rule": "Predicate-reconciled declared output destination, pinned by source hash.",
            "verify": "A rejected producer in DECLARED_OUTPUT_PRECEDENCE never re-promotes.",
        },
        {
            "id": "reviewed_producer_custody",
            "effect": "exempt",
            "where": "runtime/mutating_producer_custody_reviewed.py::REVIEWED_PRODUCER_CUSTODY",
            "rule": "Individually reviewed producer custody pinned by source hash.",
            "verify": "Hash equality with the pinned entry.",
        },
        {
            "id": "read_only_classifier",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_READ_ONLY_SOURCE_SHA256",
            "rule": "Reviewed normalization-only module; every flagged site is read-only.",
            "verify": "Hash equality with the pinned entry.",
        },
        # The remaining reasons come from the closed EXEMPTION_REASONS vocabulary. Each is a
        # reviewed custody decision recorded against a producer, and the custody gate refuses
        # a reason outside that tuple — so the contract lists exactly the vocabulary.
        {
            "id": "owned_ephemeral_reclamation",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::RECOVERABLE_RECLAMATION_OWNERS",
            "rule": (
                "The only mutation is a bounded probe/temp path the module creates and removes "
                "in one scope; a destructive site is permitted only for these owners."
            ),
            "verify": "RECOVERABLE_RECLAMATION_OWNERS membership plus the destructive-site check.",
        },
        {
            "id": "generated_projection_producer",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::EXEMPTION_REASONS",
            "rule": "Output is generated, never canonical authority, and is regenerated by its own producer.",
            "verify": "Reviewed entry in the producer custody tables.",
        },
        {
            "id": "non_runtime_harness",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::EXEMPTION_REASONS",
            "rule": "Test, benchmark, or verification harness that is not on a runtime path.",
            "verify": "Reviewed entry in the producer custody tables.",
        },
        {
            "id": "read_only_probe",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::EXEMPTION_REASONS",
            "rule": "The effect is a bounded read-only probe with no write.",
            "verify": "Reviewed entry in the producer custody tables.",
        },
        {
            "id": "canonical_control_audit_custody",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_CONTROL_CUSTODY",
            "rule": "Canonical control-audit ledger custody.",
            "verify": "Hash equality with the pinned entry.",
        },
        {
            "id": "protected_identity_custody",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_CONTROL_CUSTODY",
            "rule": "Runtime identity create/rotate/revoke through the protected backend transaction.",
            "verify": "Hash equality with the pinned entry.",
        },
        {
            "id": "independent_recovery_custody",
            "effect": "exempt",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_CONTROL_CUSTODY",
            "rule": "Recovery authority requires independent approval and consumes replay once.",
            "verify": "Hash equality with the pinned entry.",
        },
        {
            "id": "canonical_lease_intent_delegate",
            "effect": "leased",
            "where": "runtime/mutating_producer_registry.py::REVIEWED_DELEGATED_PUBLICATION",
            "rule": "Caller bytes pinned to the reviewed delegation table.",
            "verify": "Hash equality; the live delegated_publication verdict is preferred.",
        },
        {
            "id": "output_root_grant",
            "effect": "authorized_destination",
            "where": "runtime/output_roots.py + registry/producer_output_roots.json",
            "rule": (
                "A caller-directed destination strictly below an authorized root, granted per "
                "write class. One grant never authorizes another destination or class."
            ),
            "verify": "contained_in(destination, root) and the class-scoped grant lookup.",
        },
        {
            "id": "durable_resource_owner",
            "effect": "owner",
            "where": REGISTRY_CANDIDATE.name,
            "rule": "An approved accountable owner for the durable resource being written.",
            "verify": "Registrations exist and each cites an approval event id. Currently none.",
        },
    ],
    "never_sufficient_alone": [
        "directory or file name",
        "a successful import of a helper",
        "a passing write during a dry run",
        "another destination's grant",
        "another write class's grant",
    ],
    "current_state": {
        "output_root_roots": len(load(OUTPUT_ROOTS).get("roots") or []),
        "output_root_grants": len(load(OUTPUT_ROOTS).get("grants") or []),
        "approved_durable_resource_owners": len(
            [
                item
                for item in (load(REGISTRY_CANDIDATE).get("resources") or [])
                if item.get("accountable_owner")
            ]
        ),
    },
}

# ---------------------------------------------------------------- B7 decision register
matrix = load(MATRIX)
candidate = load(REGISTRY_CANDIDATE)
candidate_by_id = {
    item.get("resource_id"): item for item in candidate.get("resources") or []
}
decision_rows = []
for resource in matrix["resources"]:
    resource_id = resource["resource_id"]
    proposals = resource.get("candidate_owner") or resource.get("candidate_owners") or []
    decision_rows.append(
        {
            "resource_id": resource_id,
            "resource_class": resource.get("resource_class"),
            "scope": resource.get("scope") or resource.get("roots") or resource.get("root"),
            "producers": sorted(resource.get("producers") or []),
            "candidate_owner": proposals,
            "candidate_evidence": resource.get("provenance") or resource.get("evidence"),
            "unresolved_questions": resource.get("unresolved_questions") or [],
            "decision": "pending",
            "decision_rule": (
                "A candidate becomes the accountable owner only after a governed approval "
                "records an owner_approval_event_id for this resource_id. The matrix proposes; "
                "it does not approve."
            ),
            "approval_evidence": None,
            "registry_registered": resource_id in candidate_by_id,
        }
    )

b7_register = {
    "schema_version": "px.b7-owner-decision-register/1.0",
    "gap_id": "PX-OS-1067",
    "source_matrix": MATRIX.name,
    "source_matrix_sha256": hashlib.sha256(MATRIX.read_bytes()).hexdigest(),
    "candidate_registry": REGISTRY_CANDIDATE.name,
    "decisions": decision_rows,
    "totals": {
        "resources": len(decision_rows),
        "approved": sum(1 for row in decision_rows if row["decision"] == "approved"),
        "rejected": sum(1 for row in decision_rows if row["decision"] == "rejected"),
        "pending": sum(1 for row in decision_rows if row["decision"] == "pending"),
    },
    "decision_authority": (
        "Governance only. This register is executable: flipping a row to `approved` without a "
        "recorded approval event is a defect, and `validate_resource_candidate` refuses a "
        "candidate record that carries one."
    ),
}

# ------------------------------------------------------------ producer dispositions
census = load(CENSUS)
px = load(PX_AUDIT)
px_by_path = {item["path"]: item for item in px["producers"]}
b7_paths = {path for path in (item["producer"] for item in matrix["producer_dispositions"])}

# One shared scan. Classifying 373 producers with a fresh scan each is the quadratic path
# that was just removed from the canonical census; this evidence tool must not reintroduce it.
_scan = discover_effect_surfaces(ROOT)
_live_mutating = discover_mutating_producers(ROOT, records=_scan)

dispositions = []
for path in sorted(_live_mutating):
    family = path.split("/", 1)[0]
    verdict = default_classification(ROOT, path, _live_mutating[path], records=_scan)
    row: dict[str, object] = {
        "path": path,
        "family": family,
        "source_sha256": sha(path) if (ROOT / path).is_file() else None,
        "disposition": "unresolved",
        "authority": None,
        "accounting": None,
        "missing_authority": None,
    }
    if verdict is not None:
        row["disposition"] = "resolved"
        row["authority"] = verdict["reason"]
        row["missing_authority"] = None
    if path in b7_paths:
        row["accounting"] = "b7-resource-matrix"
        row["missing_authority"] = (
            "Accountable owner approval for the durable resource (see b7 owner decision register)."
        )
    elif path in px_by_path:
        row["accounting"] = "px-skills-owner-audit"
        row["missing_authority"] = (
            "Architectural role plus a destination grant or approved resource owner for this "
            "skill script's output class."
        )
    elif family == "scripts":
        row["accounting"] = "scripts-producer-audit"
        row["missing_authority"] = (
            "Per-write-class destination authority: an output-root grant for caller-directed "
            "outputs, or an approved durable resource owner for repository state."
        )
    elif row["disposition"] == "resolved":
        row["accounting"] = "mutating-producer-registry"
    else:
        row["accounting"] = "unaccounted"
        row["missing_authority"] = "No evidence artifact covers this producer; needs a source audit."
    dispositions.append(row)

producer_registry = {
    "schema_version": "px.producer-dispositions/1.0",
    "gap_id": "PX-OS-1067",
    "census_artifact": CENSUS.name,
    "census_sha256": hashlib.sha256(CENSUS.read_bytes()).hexdigest(),
    "population": "live mutating producers, discovered with one shared effect scan",
    "authority_contract": "px-os-1067-authority-contract.json",
    "rows": dispositions,
    "totals": {
        "producers": len(dispositions),
        "resolved": sum(1 for row in dispositions if row["disposition"] == "resolved"),
        "unresolved": sum(1 for row in dispositions if row["disposition"] == "unresolved"),
        "unaccounted": sum(1 for row in dispositions if row["accounting"] == "unaccounted"),
        "by_family": {
            family: sum(1 for row in dispositions if row["family"] == family)
            for family in sorted({row["family"] for row in dispositions})
        },
    },
    "note": (
        "Every unresolved row names the exact authority it lacks. No producer is resolved by "
        "this artifact; it records what is already established elsewhere."
    ),
}

generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
for path, document in (
    (EVIDENCE / "px-os-1067-authority-contract.json", authority_contract),
    (EVIDENCE / "px-os-1067-b7-owner-decision-register.json", b7_register),
    (EVIDENCE / "px-os-1067-producer-dispositions.json", producer_registry),
):
    document["generated_at_utc"] = generated
    path.write_text(json.dumps(document, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {path.name}")

print(json.dumps(b7_register["totals"]))
print(json.dumps(producer_registry["totals"]))
