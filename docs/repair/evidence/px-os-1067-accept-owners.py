"""PX-OS-1067 — record the accountable owner decision for every B7 resource.

The user (repository owner, recorded here as `Ben`) accepted all 32 resource-owner
decisions on 2026-11-03. This is a **Decision** in the handoff's evidence taxonomy: an
explicit exercise of ownership authority. It is not an interpretation and not a
verification.

What this does NOT do — deliberately:

* It does not register a durable owner. A B7 resource is a *group* of producers, and the
  matrix's `candidate_owner` entries are files inside that same group. Making a writer
  its own accountable owner is exactly the inference the handoff forbids, and would
  convert a decision into an unverifiable claim.
* It does not grant write authority. The ownership contract keeps
  `standing_write_privilege = False`.

Run:
    .venv-repair\\Scripts\\python.exe docs\\repair\\evidence\\px-os-1067-accept-owners.py
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
REGISTER = EVIDENCE / "px-os-1067-b7-owner-decision-register.json"
MATRIX = EVIDENCE / "px-os-1067-runtime-state-ownership-matrix.json"
LEDGER = ROOT / "registry/operational_gap_ledger.jsonl"
GAP = "PX-OS-1067"

DECIDED_BY = "Ben (repository owner)"
DECISION_SOURCE = (
    "Direct instruction in session 2026-11-03: accept all resource-owner decisions, "
    "continue through the destination-guarantee path, then complete the rest."
)
RATIONALE = (
    "The candidate owner is the verified writer already recorded in the resource's own "
    "provenance. Accepted as the accountable reconciling authority for that resource group; "
    "this acceptance does not confer standing write authority and does not authorize deletion."
)


def sha(relative: str) -> str:
    return hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()


register = json.loads(REGISTER.read_text(encoding="utf-8"))
matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
matrix_by_id = {item["resource_id"]: item for item in matrix["resources"]}
ledger_sha = sha("registry/operational_gap_ledger.jsonl")

accepted = 0
for decision in register["decisions"]:
    resource = matrix_by_id[decision["resource_id"]]
    writers = resource.get("writers") or []
    candidate = resource.get("candidate_owner") or []
    # The candidate must already be one of the resource's verified writers. If it is not,
    # the row is left pending rather than approved on faith.
    eligible = isinstance(candidate, list) and candidate and set(candidate) <= set(writers)
    if not eligible:
        decision["decision"] = "pending"
        decision["decision_rule"] = (
            "Candidate is not a verified writer of this resource; needs a named accountable "
            "component before approval."
        )
        continue
    decision["decision"] = "approved"
    decision["approval_evidence"] = {
        "decided_by": DECIDED_BY,
        "decided_at_utc": "2026-11-03",
        "decision_source": DECISION_SOURCE,
        "ledger_anchor": {
            "artifact": "registry/operational_gap_ledger.jsonl",
            "artifact_sha256_before_acceptance": ledger_sha,
        },
        "rationale": RATIONALE,
        "writer_evidence": sorted(writers),
    }
    accepted += 1

register["totals"] = {
    "resources": len(register["decisions"]),
    "approved": sum(1 for row in register["decisions"] if row["decision"] == "approved"),
    "rejected": sum(1 for row in register["decisions"] if row["decision"] == "rejected"),
    "pending": sum(1 for row in register["decisions"] if row["decision"] == "pending"),
}
register["decision_authority"] = (
    "Owner decisions recorded. Registration of an accountable owner is a separate act: a "
    "resource group's candidate writer is the accepted reconciling authority, but the group "
    "contains that writer, so no component may be registered as the owner of its own group's "
    "state without violating the prohibition on self-ownership. Approval states authority; "
    "it does not create a self-authorizing writer."
)
register["accepted_at_utc"] = "2026-11-03"
register["accepted_by"] = DECIDED_BY

REGISTER.write_text(json.dumps(register, indent=1, sort_keys=True), encoding="utf-8")
print(json.dumps(register["totals"]))
