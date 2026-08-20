"""Generate the single non-certifying completion projection from owned ledgers."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sys


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


CARD = re.compile(r"^\|\s*([A-Z][A-Z0-9-]*\d+)\s*\|\s*\[([xX~ ])\]\s*\|")
STATE = {"x": "accepted", "X": "accepted", "~": "partial", " ": "open"}
VERIFIED = frozenset({"accepted", "closed", "passed", "verified"})
LIVE_PENDING = frozenset(
    {
        "fixed_pending_live_verification",
        "fixed_pending_live_reload_verification",
    }
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(root: Path) -> dict[str, object]:
    root = root.resolve(strict=True)
    cards_path = root / "docs/PX_UNIVERSAL_VISIBILITY_PUNCH_CARDS.md"
    repairs_path = root / "registry/adversarial_repair_status.json"
    reaudit_path = root / "registry/adversarial_reaudit_20260814.json"
    functional_path = root / "registry/functional_validation_r2_20260814.json"
    operational_path = root / "registry/operational_validation_r3_20260814.json"
    independent_path = (
        root / "registry/independent_operational_audit_r1_20260815.json"
    )
    surface_path = root / "registry/operational_surface_audit_20260816.json"
    instruction_path = root / "registry/instruction_reconciliation_audit_20260816.json"
    cards = []
    for line in cards_path.read_text(encoding="utf-8").splitlines():
        match = CARD.match(line)
        if match:
            cards.append({"id": match.group(1), "status": STATE[match.group(2)]})
    repairs = json.loads(repairs_path.read_text(encoding="utf-8"))["records"]
    reaudit = json.loads(reaudit_path.read_text(encoding="utf-8"))["findings"]
    functional = json.loads(functional_path.read_text(encoding="utf-8"))["findings"]
    operational = json.loads(operational_path.read_text(encoding="utf-8"))["findings"]
    independent = json.loads(independent_path.read_text(encoding="utf-8"))[
        "findings"
    ]
    surface = json.loads(surface_path.read_text(encoding="utf-8"))["findings"]
    instruction = json.loads(instruction_path.read_text(encoding="utf-8"))
    requirements = instruction.get("requirements", [])
    identity_sets = (cards, repairs, reaudit, functional, operational, independent, surface)
    if any(len({row["id"] for row in rows}) != len(rows) for rows in identity_sets):
        raise ValueError("completion authority contains duplicate card identities")
    card_counts = Counter(row["status"] for row in cards)
    repair_counts = Counter(row["status"] for row in repairs)
    historical_cards_complete = (
        card_counts["open"] == card_counts["partial"] == 0
        and all(row["status"] == "accepted" for row in repairs)
    )
    open_reaudit = [row["id"] for row in reaudit if row.get("status") == "open"]
    pending_reaudit = [row["id"] for row in reaudit if row.get("status") not in {"accepted", "closed", "passed"}]
    reaudit_counts = Counter(row.get("status", "unknown") for row in reaudit)
    open_functional = [row["id"] for row in functional if row.get("status") == "open"]
    pending_functional = [row["id"] for row in functional if row.get("status") not in {"accepted", "closed", "passed"}]
    functional_counts = Counter(row.get("status", "unknown") for row in functional)
    open_operational = [row["id"] for row in operational if row.get("status") == "open"]
    pending_operational = [row["id"] for row in operational if row.get("status") not in {"accepted", "closed", "passed"}]
    operational_counts = Counter(row.get("status", "unknown") for row in operational)
    open_independent = [
        row["id"] for row in independent if row.get("status") == "open"
    ]
    pending_independent = [
        row["id"]
        for row in independent
        if row.get("status") not in {"accepted", "closed", "passed"}
    ]
    independent_counts = Counter(
        row.get("status", "unknown") for row in independent
    )
    open_surface = [row["id"] for row in surface if row.get("status") == "open"]
    live_pending_surface = [
        row["id"] for row in surface if row.get("status") in LIVE_PENDING
    ]
    verified_surface = [
        row["id"] for row in surface if row.get("status") in VERIFIED
    ]
    unknown_surface = [
        row["id"]
        for row in surface
        if row.get("status") not in VERIFIED | LIVE_PENDING | {"open"}
    ]
    pending_surface = [
        row["id"]
        for row in surface
        if row.get("status") not in {"accepted", "closed", "passed"}
    ]
    surface_counts = Counter(row.get("status", "unknown") for row in surface)
    requirement_counts = Counter(
        str(row.get("state", "unknown")) for row in requirements
    )
    instruction_requirements_complete = bool(
        instruction.get("completion_claim", {}).get("complete")
    )
    operational_repairs_complete = not open_surface and not unknown_surface
    live_verification_complete = not live_pending_surface and not unknown_surface
    operational_frontier_complete = (
        operational_repairs_complete and live_verification_complete
    )
    cards_complete = (
        instruction_requirements_complete
        and operational_frontier_complete
    )
    from runtime.test_profiles import group_status, section_status

    sections = section_status(root)
    groups = group_status(root)
    section_rows = list(sections.get("sections", ()))
    group_rows = list(groups.get("groups", ()))
    gate_blockers = [
        f"section:{row['section']}" for row in sections.get("sections", ()) if not row.get("current")
    ] + [f"group:{row['group']}" for row in groups.get("groups", ()) if not row.get("current")]
    failed_receipts = [
        f"section:{row['section']}" for row in section_rows if not row.get("passed")
    ] + [f"group:{row['group']}" for row in group_rows if not row.get("passed")]
    stale_receipts = [
        f"section:{row['section']}" for row in section_rows if not row.get("fresh")
    ] + [f"group:{row['group']}" for row in group_rows if not row.get("fresh")]
    dependency_stale_receipts = [
        f"section:{row['section']}"
        for row in section_rows
        if not row.get("dependencies_current")
    ]
    blocking_reasons = []
    if not historical_cards_complete:
        blocking_reasons.append(
            "one or more historical punch cards or repair records are not accepted"
        )
    if not instruction_requirements_complete:
        blocking_reasons.append(
            "the current instruction-reconciliation authority is not complete"
        )
    if pending_surface:
        blocking_reasons.append(
            f"current product-surface audit has {len(pending_surface)} operational findings pending repair and verification"
        )
    if gate_blockers:
        blocking_reasons.append(f"{len(gate_blockers)} required section/group receipts are stale or failed")
    evidence_path = root / "registry/current_evidence_index.json"
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        evidence = {}
    operationally_complete = cards_complete
    evidence_receipts_current = (
        evidence.get("valid") is True
        and evidence.get("current_required_receipt_count")
        == evidence.get("required_receipt_count")
        and not evidence.get("blocking_reasons")
    )
    evidence_identity_current = False
    evidence_identity_evaluated = False
    if operationally_complete and not gate_blockers and evidence_receipts_current:
        from runtime.engine_identity import validate_engine_identity

        engine = validate_engine_identity(root)
        indexed_engine = evidence.get("engine_identity", {})
        evidence_identity_current = (
            engine.get("valid") is True
            and indexed_engine.get("manifest_sha256")
            == engine.get("manifest_sha256")
            and indexed_engine.get("tree_sha256") == engine.get("tree_sha256")
            and indexed_engine.get("file_total") == engine.get("file_total")
        )
        evidence_identity_evaluated = True
    certification_fresh = (
        not gate_blockers
        and evidence_receipts_current
        and evidence_identity_current
    )
    certification_eligible = operationally_complete and certification_fresh
    if certification_eligible:
        from runtime.release_certification import verify_release_certificate

        release_certificate = verify_release_certificate(root)
    else:
        release_certificate = {
            "valid": False,
            "errors": ["current product is not certification-eligible"],
        }
    certified = certification_eligible and release_certificate.get("valid") is True
    if not certified:
        blocking_reasons.append("final exact-artifact certification has not been admitted")
    complete = not blocking_reasons
    return {
        "schema_version": "px.completion-status/1.3",
        "authority": "generated projection; current operational and instruction ledgers supersede historical audit acceptance as completion authority",
        "complete": complete,
        "operationally_complete": operationally_complete,
        "certified": certified,
        "sources": [
            {"path": cards_path.relative_to(root).as_posix(), "sha256": _sha(cards_path)},
            {"path": repairs_path.relative_to(root).as_posix(), "sha256": _sha(repairs_path)},
            {"path": reaudit_path.relative_to(root).as_posix(), "sha256": _sha(reaudit_path)},
            {"path": functional_path.relative_to(root).as_posix(), "sha256": _sha(functional_path)},
            {"path": operational_path.relative_to(root).as_posix(), "sha256": _sha(operational_path)},
            {"path": independent_path.relative_to(root).as_posix(), "sha256": _sha(independent_path)},
            {"path": surface_path.relative_to(root).as_posix(), "sha256": _sha(surface_path)},
            {"path": instruction_path.relative_to(root).as_posix(), "sha256": _sha(instruction_path)},
            *([{"path": evidence_path.relative_to(root).as_posix(), "sha256": _sha(evidence_path)}] if evidence_path.is_file() else []),
        ],
        "cards_complete": cards_complete,
        "historical_cards_complete": historical_cards_complete,
        "universal_cards": {"authority": "historical provenance; not sufficient for current completion", "count": len(cards), "counts": dict(sorted(card_counts.items())), "open_ids": [row["id"] for row in cards if row["status"] != "accepted"]},
        "adversarial_repairs": {"authority": "historical provenance; not sufficient for current completion", "count": len(repairs), "counts": dict(sorted(repair_counts.items())), "open_ids": [row["id"] for row in repairs if row["status"] != "accepted"]},
        "current_instruction_reconciliation": {
            "count": len(requirements),
            "state_counts": dict(sorted(requirement_counts.items())),
            "complete": instruction_requirements_complete,
            "completion_claim": instruction.get("completion_claim", {}),
        },
        "current_adversarial_reaudit": {
            "count": len(reaudit),
            "status_counts": dict(sorted(reaudit_counts.items())),
            "open_ids": open_reaudit,
            "pending_ids": pending_reaudit,
        },
        "current_functional_validation": {
            "count": len(functional),
            "status_counts": dict(sorted(functional_counts.items())),
            "open_ids": open_functional,
            "pending_ids": pending_functional,
        },
        "current_operational_validation": {
            "count": len(operational),
            "status_counts": dict(sorted(operational_counts.items())),
            "open_ids": open_operational,
            "pending_ids": pending_operational,
        },
        "current_independent_operational_audit_r1": {
            "count": len(independent),
            "status_counts": dict(sorted(independent_counts.items())),
            "open_ids": open_independent,
            "pending_ids": pending_independent,
        },
        "current_operational_surface_audit": {
            "count": len(surface),
            "status_counts": dict(sorted(surface_counts.items())),
            "open_ids": open_surface,
            "pending_ids": pending_surface,
            "complete": operational_frontier_complete,
        },
        "operational_readiness": {
            "repairs_complete": operational_repairs_complete,
            "open_ids": open_surface,
            "unknown_status_ids": unknown_surface,
        },
        "live_verification": {
            "complete": live_verification_complete,
            "pending_ids": live_pending_surface,
            "verified_ids": verified_surface,
            "unknown_status_ids": unknown_surface,
        },
        "historical_verification_debt": {
            "authority": "provenance only; superseded by the current instruction and operational-surface ledgers",
            "pending_ids": sorted(
                pending_reaudit
                + pending_functional
                + pending_operational
                + pending_independent
            ),
        },
        "current_gates": {"valid": not gate_blockers, "blocking_ids": gate_blockers},
        "certification_freshness": {
            "fresh": certification_fresh,
            "receipt_current": not gate_blockers,
            "evidence_identity_current": evidence_identity_current,
            "evidence_identity_evaluated": evidence_identity_evaluated,
            "evidence_receipts_current": evidence_receipts_current,
            "failed_receipt_ids": failed_receipts,
            "stale_receipt_ids": stale_receipts,
            "dependency_stale_receipt_ids": dependency_stale_receipts,
        },
        "release_certificate": release_certificate,
        "blocking_reasons": blocking_reasons,
    }


def write(root: Path) -> dict[str, object]:
    """Atomically publish the current non-certifying completion projection."""
    root = root.resolve(strict=True)
    value = build(root)
    target = root / "registry/completion_status.json"
    temporary = target.with_name(f".{target.name}.prepared")
    temporary.write_text(
        json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    os.replace(temporary, target)
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    value = write(root) if args.apply else build(root)
    print(json.dumps(value, indent=2))
    return 0 if value["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
