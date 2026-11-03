"""PX-OS-1067 — register approved custodian owners for B7 resources.

Records the approved ownership decision for every B7 resource that has a real custodian
candidate: a component that reads the resource but is NOT one of its producers.

Why the rule is `reader outside the group` and nothing looser: the earlier deadlock was
that every candidate was a writer inside its own group. Registration is therefore allowed
only when an existing, source-recorded component can reconcile the state it does not write.
The register records the decision; it does not make a writer its own authority.

Resources with no such candidate stay `pending_registration` even though the owner
decision is accepted, and the reason is recorded.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-register-custodians.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

# The evidence-tool launchers are not package roots; the repository root is.
ROOT = Path(__file__).resolve().parents[3] if "evidence" in Path(__file__).parts else Path(__file__).resolve().parents[2]
if not (ROOT / "runtime").is_dir():
    ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from runtime.runtime_state_ownership import validate_approved_resource_record  # noqa: E402

GAP = "PX-OS-1067"
OWNER_APPROVAL = "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036534"
DECIDED_BY = "Ben (repository owner)"

matrix = {
    item["resource_id"]: item
    for item in json.loads(
        (EVIDENCE / "px-os-1067-runtime-state-ownership-matrix.json").read_text(encoding="utf-8")
    )["resources"]
}


def _scope(resource: dict) -> str | None:
    """Repository-relative scope from the matrix's `resource` path.

    `project-root/.agentic_engineering_os_px/...` is internal state below the repository
    root, so the portable scope is the path with the prefix removed. Any other shape returns
    None and the validator refuses it rather than guessing.
    """
    raw = str(resource.get("resource") or "").replace("\\", "/").strip()
    for prefix in ("project-root/", "./"):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw or None


_CLASS_ORDER = (
    "authoritative_durable",
    "regenerable_durable",
    "shared_durable",
    "delegated_persistent",
    "ephemeral_process_local",
)


def _resource_class(resource: dict, resource_id: str) -> str:
    """Closed-vocabulary class from the matrix's `durability` description.

    The mapping is mechanical and conservative: anything describing ephemeral or
    process-local state stays ephemeral, anything delegated stays delegated, and a durable
    resource shared by several producers is `shared_durable`.
    """
    durability = str(resource.get("durability") or "").casefold()
    if "ephemeral" in durability or "process-local" in durability:
        return "ephemeral_process_local"
    if "delegat" in durability or "delegat" in resource_id:
        return "delegated_persistent"
    if "regenerable" in durability or "generated" in durability:
        return "regenerable_durable"
    if "shared" in durability:
        return "shared_durable"
    return "authoritative_durable"
register = json.loads(
    (EVIDENCE / "px-os-1067-b7-owner-decision-register.json").read_text(encoding="utf-8")
)

# Only a unique reader outside the group is an unambiguous custodian. Several readers would
# need a decision about which one reconciles; that is not ours to make.
resources = []
for decision in register["decisions"]:
    resource = matrix[decision["resource_id"]]
    members = sorted(set(resource.get("writers") or []))
    readers = sorted(set(resource.get("readers") or []) - set(members))
    custody = decision.get("custodian_evidence") or {}
    owner = custody.get("custodian")
    candidates = custody.get("candidates") or []
    if decision["decision"] != "approved":
        state, reason = "pending_decision", "Ownership decision not approved."
    elif custody.get("status") == "registered":
        state, reason = "registered", None
    elif custody.get("status") == "none":
        state, reason = (
            "pending_registration",
            "No component reads this resource from outside its producer group; the only "
            "source-backed candidates are its own writers.",
        )
    elif custody.get("status") == "ambiguous":
        state, reason = (
            "pending_registration",
            "Several components read this resource from outside its group; choosing the "
            "reconciling authority is an ownership decision, not an inference.",
        )
    else:
        state, reason = "pending_registration", "No custodian evidence recorded."

    record = {
        "resource_id": decision["resource_id"],
        # The matrix names the resource by repository-relative path and by a durability
        # description; it has no `scope`/`resource_class` fields. Mapping is explicit here so
        # the validator judges real values instead of silently failing on missing keys.
        "scope": _scope(resource),
        "resource_class": _resource_class(resource, decision["resource_id"]),
        "accountable_owner": owner if state == "registered" else None,
        "owner_approval_event_id": OWNER_APPROVAL if state == "registered" else None,
        "provenance": [f"docs/repair/evidence/{EVIDENCE.name}/px-os-1067-runtime-state-ownership-matrix.json"],
        "retention": resource.get("retention") or "unresolved",
        "lifecycle": resource.get("lifecycle") or "unresolved",
        "concurrency": "single accountable reconciler; per-run authorization required",
        "reclamation": "retirement owner only; no registry grants deletion",
        "recovery": "unresolved unless the matrix records it",
        "authorization": {
            "per_run_governed_authorization_required": True,
            "existing_controls": ["effect_grant", "scope_lease", "effect_intent"],
            "standing_write_privilege": False,
            "registry_confers_write_authority": False,
            "registry_confers_deletion_authority": False,
        },
    }
    if state == "registered":
        errors = validate_approved_resource_record(record, group_members=members)
        if errors:
            state, reason = "pending_registration", "Rejected by validator: " + "; ".join(errors)
            record["accountable_owner"] = None
            record["owner_approval_event_id"] = None
    resources.append(
        {
            "registration_state": state,
            "registration_reason": reason,
            "group_members": members,
            "outside_readers": readers,
            "record": record,
        }
    )

registered = [item for item in resources if item["registration_state"] == "registered"]
document = {
    "schema_version": "px.runtime-state-ownership-registry/2.0",
    "gap_id": GAP,
    "state": "approved_custodian_registrations",
    "authority": (
        "Owner decisions accepted by the repository owner on 2026-11-03. An accountable owner "
        "is registered only where a component outside the resource's own producer group can "
        "reconcile it. Registration confers no standing write or deletion authority."
    ),
    "owner_decision": {
        "decided_by": DECIDED_BY,
        "decided_at_utc": "2026-11-03",
        "approval_event_id": OWNER_APPROVAL,
    },
    "resources": resources,
    "totals": {
        "resources": len(resources),
        "registered": len(registered),
        "pending_registration": sum(
            1 for item in resources if item["registration_state"] == "pending_registration"
        ),
        "pending_decision": sum(
            1 for item in resources if item["registration_state"] == "pending_decision"
        ),
    },
    "boundary": (
        "A writer is never the accountable owner of its own group. Registered owners read the "
        "resource and hold no standing write privilege; every mutation still needs a per-run "
        "governed effect grant, and no registration authorizes deletion."
    ),
}
document["resources"] = sorted(document["resources"], key=lambda item: item["record"]["resource_id"])
(EVIDENCE / "px-os-1067-runtime-state-ownership-registry.json").write_text(
    json.dumps(document, indent=1, sort_keys=True), encoding="utf-8"
)
print(json.dumps(document["totals"]))
