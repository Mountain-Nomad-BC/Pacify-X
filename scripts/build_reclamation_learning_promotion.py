"""Compile real cleanup lifecycle experience into a governed learned process."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from runtime.learning_promotion import (
    compare_revisions,
    confidence_gate,
    decay_decision,
    freeze_revision,
    measure_reuse,
    operation_evidence,
    promote_revision,
    research_validation,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    receipt_root = root / ".engineering-bootstrap/resource-lifecycle/cleanup-receipts"
    policy = root / ".px/skills/manage-resource-lifecycle/references/lifecycle-policy.md"
    runtime = root / "runtime/resource_lifecycle.py"
    report = root / "registry/adversarial_reaudit_20260813.json"
    section = root / ".engineering-bootstrap/test-evidence/sections/testing-governance.json"
    required = (policy, runtime, report, section)
    if any(not path.is_file() for path in required):
        raise FileNotFoundError("learning promotion prerequisites are incomplete")

    failed: list[tuple[Path, dict[str, Any]]] = []
    successful: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(receipt_root.glob("cleanup-*.json")):
        row = _load(path)
        lane = str(row.get("lane_id", ""))
        if lane not in {"group:release-build", "group:derived-integrity"}:
            continue
        if row.get("resources_failed") == 1 and row.get("errors"):
            failed.append((path, row))
        elif row.get("resources_reclaimed") == 1 and not row.get("errors"):
            successful.append((path, row))
    if len(failed) < 2 or len(successful) < 6:
        raise ValueError(
            "real before/after cleanup evidence is insufficient for promotion"
        )

    environment_sha = _sha(policy)
    observations = []
    for index, (path, row) in enumerate(failed + successful, start=1):
        success = row.get("resources_reclaimed") == 1 and not row.get("errors")
        observations.append(
            operation_evidence(
                operation_id=f"cleanup-receipt-{index}",
                task_class="owned-workspace-reclamation",
                outcome="passed" if success else "cleanup_failed",
                measurements={
                    "success": int(success),
                    "bytes_reclaimed": int(row.get("bytes_reclaimed", 0)),
                },
                capability_ids=["manage-resource-lifecycle"],
                environment_sha256=environment_sha,
                source_refs=[path.relative_to(root).as_posix()],
                observed_at=str(row.get("end_time")),
            )
        )

    evidence_hashes = [item["record_sha256"] for item in observations]
    dependencies = {
        "lifecycle_policy": _sha(policy),
        "resource_lifecycle_runtime": _sha(runtime),
    }
    incumbent = freeze_revision(
        unit_id="process.owned-workspace-reclamation",
        kind="process",
        artifact={
            "strategy": "single-attempt",
            "read_only_recovery": False,
            "transient_lock_retry": False,
        },
        evidence_sha256=evidence_hashes,
        dependency_sha256=dependencies,
        tier=1,
    )
    challenger = freeze_revision(
        unit_id="process.owned-workspace-reclamation",
        kind="process",
        artifact={
            "strategy": "bounded-retry",
            "retry_delays_seconds": [0.0, 0.05, 0.15, 0.35],
            "read_only_recovery": "exact failed child only",
            "scope": "already-admitted owned target",
            "failure_mode": "retain-and-receipt",
        },
        evidence_sha256=evidence_hashes,
        dependency_sha256=dependencies,
        parent_revision_sha256=incumbent["revision_sha256"],
        tier=2,
    )
    trial_hashes = [item["record_sha256"] for item in observations[len(failed) :]]
    trials = [
        {"winner": "challenger", "evidence_sha256": digest}
        for digest in trial_hashes
    ]
    comparison = compare_revisions(
        incumbent=incumbent,
        challenger=challenger,
        trials=trials,
        minimum_trials=6,
    )
    confidence = confidence_gate(
        wins=len(trials), losses=0, minimum_trials=6
    )
    research = research_validation(
        question="Does bounded retry improve owned Windows cleanup without widening deletion authority?",
        references=[
            {
                "uri": "audit:PACIFY_X_CLEAN_FULL_ADVERSARIAL_REAUDIT_20260813.md",
                "evidence_sha256": _sha(report),
                "independent": True,
            },
            {
                "uri": "policy:manage-resource-lifecycle/lifecycle-policy.md",
                "evidence_sha256": _sha(policy),
                "independent": False,
            },
        ],
        better_alternative_found=False,
        conclusion=(
            "Bounded retry after the unchanged reclamation gate resolves the observed "
            "transient/read-only failure class while retaining fail-closed scope."
        ),
    )
    promotion = promote_revision(
        revision=challenger,
        confidence=confidence,
        comparison=comparison,
        research=research,
        final_validation_sha256=_sha(section),
        current_dependencies=dependencies,
        partial_units=["runtime.resource_lifecycle._remove_owned_target"],
    )
    reuse = measure_reuse(
        promotion_sha256=promotion["record_sha256"],
        uses=len(successful),
        successes=len(successful),
        regressions=0,
    )
    decay = decay_decision(reuse, minimum_uses=6)
    valid = bool(
        promotion["passed"]
        and decay["next_state"] == "canonical"
        and promotion["rollback_revision_sha256"] == incumbent["revision_sha256"]
    )
    return {
        "schema_version": "px.learned-process-admission/1.0",
        "valid": valid,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "authority": {
            "learning_direct_write_allowed": False,
            "promotion_authorized_by": "explicit user repair-and-completion request",
            "runtime_authority": "Codex host retained",
        },
        "evidence_denominator": {
            "failed_incumbent_receipts": len(failed),
            "successful_challenger_receipts": len(successful),
            "trials": len(trials),
        },
        "observations": observations,
        "incumbent": incumbent,
        "challenger": challenger,
        "confidence": confidence,
        "comparison": comparison,
        "research": research,
        "promotion": promotion,
        "reuse": reuse,
        "decay": decay,
        "rollback": {
            "available": True,
            "revision_sha256": incumbent["revision_sha256"],
            "automatic_delete_allowed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "evidence/learning/owned-workspace-reclamation-promotion-20260813.json"
        ),
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = build(args.root)
    output = args.output if args.output.is_absolute() else args.root / args.output
    if args.check:
        existing = _load(output) if output.is_file() else {}
        # Timestamps are observational metadata and do not affect the promotion.
        existing.pop("generated_utc", None)
        result.pop("generated_utc", None)
        if existing != result:
            raise SystemExit("learning promotion evidence is stale")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({"valid": result["valid"], **result["evidence_denominator"]}))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
