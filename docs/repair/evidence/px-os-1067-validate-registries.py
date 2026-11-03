"""PX-OS-1067 — verify the auditable registries against the live canonical census.

The three evidence registries (owner decisions, producer dispositions, authority
contract) are only meaningful if they still describe today's repository. This check
fails closed when they drift, when a disposition claims an authority the contract does
not define, or when an owner decision claims approval without evidence.

It never changes a disposition. It reports.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from runtime.producer_census import census  # noqa: E402


def load(name: str) -> dict:
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def main() -> int:
    contract = load("px-os-1067-authority-contract.json")
    b7 = load("px-os-1067-b7-owner-decision-register.json")
    dispositions = load("px-os-1067-producer-dispositions.json")
    matrix = load("px-os-1067-runtime-state-ownership-matrix.json")

    reported: list[str] = []
    live = census(ROOT)
    contract_ids = {source["id"] for source in contract["authority_sources"]}

    rows = dispositions["rows"]
    live_mutating = set(live["mutating_producer_paths"])
    physical = {row["path"] for row in rows}

    if physical != live_mutating:
        reported.append(
            f"producer dispositions cover {len(physical)} paths but the live census has "
            f"{len(live_mutating)}; missing={sorted(live_mutating - physical)[:3]} "
            f"extra={sorted(physical - live_mutating)[:3]}"
        )
    resolved = {row["path"] for row in rows if row["disposition"] == "resolved"}
    live_resolved = live_mutating - set(live["unresolved_paths"])
    if resolved != live_resolved:
        reported.append(
            "resolved sets differ from the canonical census: "
            f"registry_only={sorted(resolved - live_resolved)[:3]} "
            f"census_only={sorted(live_resolved - resolved)[:3]}"
        )
    for row in rows:
        if row["disposition"] == "resolved" and row.get("authority") not in contract_ids:
            reported.append(f"{row['path']}: resolved by an authority outside the contract")
        if row["disposition"] == "unresolved" and not row.get("missing_authority"):
            reported.append(f"{row['path']}: unresolved without naming the missing authority")

    matrix_paths = {item["producer"] for item in matrix["producer_dispositions"]}
    if len(matrix_paths) != len(matrix["producer_dispositions"]):
        reported.append("B7 matrix lists duplicate producers")
    unaccounted = [row["path"] for row in rows if row["accounting"] == "unaccounted"]
    if unaccounted:
        reported.append(f"producers without accounting evidence: {unaccounted[:5]}")
    for path in matrix_paths:
        if path not in live_mutating:
            reported.append(f"B7 matrix names a path that is no longer a mutating producer: {path}")

    if len(b7["decisions"]) != len(matrix["resources"]):
        reported.append("B7 decision register does not cover every matrix resource")
    for decision in b7["decisions"]:
        if decision["decision"] == "approved" and not decision.get("approval_evidence"):
            reported.append(
                f"{decision['resource_id']}: approved without an approval event id"
            )
        if decision["decision"] == "approved" and not decision.get("registry_registered"):
            reported.append(
                f"{decision['resource_id']}: approved but absent from the candidate registry"
            )

    result = {
        "valid": not reported,
        "findings": reported,
        "producers": len(rows),
        "resolved": len(resolved),
        "unresolved": len(rows) - len(resolved),
        "b7_resources": len(b7["decisions"]),
        "b7_pending": sum(1 for d in b7["decisions"] if d["decision"] == "pending"),
    }
    print(json.dumps(result, indent=1))
    return 0 if not reported else 1


if __name__ == "__main__":
    raise SystemExit(main())
