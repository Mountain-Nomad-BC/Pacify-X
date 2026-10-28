"""Populate completion_evidence on the gaps repaired in this round.

Evidence is appended to each gap record's existing completion_evidence list. No
original field is removed or rewritten, and a gap is never marked complete on the
strength of evidence alone: the disposition field records what is still open.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"
REGISTERS = (
    Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "registers"
)

EVIDENCE: dict[str, list[dict[str, object]]] = {
    "PX-GAP-0002": [
        {
            "kind": "analysis-with-negative-action",
            "artifact": ".agentic_engineering_os_px/registers/px-gap-0002-repair-receipt.json",
            "summary": (
                "Evaluated quarantine of the stale revision-44 project-management state and "
                "REJECTED it on evidence. That state is never read by any effect-authorization "
                "path, holds no authorization, is already schema-invalid (all seven companion "
                "control documents absent), and is conservative: lifecycle.status != 'complete' "
                "keeps the strict forbidden-deployment-claims scan ACTIVE. Rewriting it to "
                "'complete' would have switched that safety scan OFF. The state was left untouched."
            ),
            "supports": "0002 open criterion is conservative-by-design, not permissive",
        },
        {
            "kind": "generator-output",
            "artifact": "README.md and registry/build_claims.json",
            "owner": "scripts/build_claims.py --apply",
            "summary": (
                "The real defect repaired was stale required projection: README/build-claim "
                "denominators had drifted from canonical source (4 errors). Regenerated through "
                "the declared owner; no hand-editing."
            ),
            "claims": {
                "runtime_modules": 387,
                "contracts": 184,
                "registry_artifacts": 521,
                "tool_and_support_scripts": 210,
            },
            "supports": "valid_build_claims true; document errors 4 -> 0",
        },
        {
            "kind": "test-execution",
            "artifact": "51 passed in 12.80s",
            "summary": "tests/test_build_claims.py and tests/test_release_preflight_inputs.py",
            "supports": "positive and negative-path release preflight validation",
        },
        {
            "kind": "negative-validation",
            "artifact": "processing-order stage checks",
            "summary": (
                "check --stage diagnose passes; check --stage repair and --stage certify are "
                "both REFUSED at phase intake, proving the phase ladder fails closed."
            ),
            "supports": "unauthorized stage advancement is impossible",
        },
        {
            "kind": "non-git-working-state-identity",
            "artifact": ".agentic_engineering_os_px/registers/working-state-identity.json",
            "summary": (
                "Deterministic current-state binding; explicitly NOT a BASE-001 substitute "
                "and NOT a source-control anchor."
            ),
            "supports": "current-state identity bound using best available non-Git evidence",
        },
    ],
    "PX-GAP-0011": [
        {
            "kind": "architecture-decision",
            "artifact": ".agentic_engineering_os_px/registers/evidence-custody-decision.json",
            "summary": (
                "Two-root custody decided and declared. .agentic_engineering_os_px/test-evidence/ "
                "is the canonical source-tree governed verification root; extension/evidence/ "
                "is the canonical installed-artifact / VSIX certification root. Neither root "
                "duplicates the other's artifacts; one architectural owner per evidence class."
            ),
            "supports": "custody model resolved; single-root consolidation explicitly rejected",
        },
        {
            "kind": "implementation",
            "artifact": "scripts/clean_source_export.py",
            "summary": (
                "Added RETAINED_DISTRIBUTION_EVIDENCE_TREES following the existing "
                "RETAINED_CONTROL_TREES pattern. The top-level evidence/ root stays excluded; "
                "retention is a per-root carve-out, not a global un-exclusion."
            ),
            "supports": "declared roots retained; unrelated evidence/generated/history still excluded",
        },
        {
            "kind": "positive-and-negative-validation",
            "artifact": "scripts/verify_evidence_custody.py",
            "summary": (
                "Synthetic-tree harness with positive retention assertions and negative exclusion "
                "assertions for node_modules, build, dist, .pytest_cache, __pycache__, undeclared "
                "evidence/ bundles and non-receipt .agentic_engineering_os_px content. It caught a "
                "real ordering bug in the first implementation (EXCLUDED_DIRS matched before the "
                "carve-out was consulted), which was then fixed."
            ),
            "supports": "custody rules verified to genuinely discriminate, not pass vacuously",
        },
        {
            "kind": "contradiction-preserved",
            "artifact": ".agentic_engineering_os_px/registers/gap-reconciliation-receipt.json",
            "summary": (
                "The cohesion-closure card corpus is absent from both the live tree and the "
                "entire reference corpus. No placeholder cards were created to silence tests."
            ),
            "supports": "gap remains open; the corpus itself is not yet restored",
        },
    ],
    "PX-GAP-0013": [
        {
            "kind": "measured-before-state",
            "artifact": "registry/current_evidence_index.json",
            "summary": (
                "Before this round: 0 of 18 indexed evidence records were current. The index "
                "declared valid=false with six blocking reasons."
            ),
            "supports": "baseline measurement",
        },
        {
            "kind": "prerequisite-repair",
            "artifact": "registry/test_group_index.json",
            "owner": "scripts/build_test_group_index.py",
            "summary": (
                "New evidence scripts invalidated test membership, which made the certification "
                "receipt policy unreadable ('test group membership is stale; explicit "
                "reconciliation required') and blocked the evidence index from evaluating "
                "currentness at all. Regenerated through the declared owner."
            ),
            "supports": "source-tree currentness became evaluable again",
        },
        {
            "kind": "generator-output",
            "artifact": "registry/current_evidence_index.json",
            "owner": "scripts/build_current_evidence_index.py --apply",
            "summary": (
                "16 source-tree receipt records regenerated through the declared owner. No digest "
                "was hand-edited. Source-tree records declared current rose from 0 to 9 of 16."
            ),
            "supports": "stale records regenerated rather than fabricated",
        },
        {
            "kind": "correctly-preserved-absence",
            "artifact": "extension/evidence/installed-vsix-smoke.json and extension/evidence/installed-vsix-smoke-linux.json",
            "summary": (
                "Both remain MISSING and are reported as such. They were NOT synthesized, "
                "stubbed, copied, fabricated or manually hashed. The index continues to block on "
                "them because source-tree evidence alone cannot certify a shipped artifact."
            ),
            "supports": "installed-artifact certification is honestly incomplete",
        },
        {
            "kind": "evidence-state-model",
            "artifact": ".agentic_engineering_os_px/registers/evidence-custody-decision.json",
            "summary": (
                "Declared three distinct states: current, stale, and "
                "missing-unavailable-pending-certification. The last is defined as a legitimate "
                "unresolved release-stage condition, explicitly NOT evidence corruption."
            ),
            "supports": "source-tree verification and installed-artifact certification stay distinct",
        },
        {
            "kind": "non-git-working-state-identity",
            "artifact": ".agentic_engineering_os_px/registers/working-state-identity.json",
            "summary": "Best available deterministic current-state binding; not a BASE-001 substitute.",
            "supports": "current-state identity bound",
        },
    ],
    "PX-GAP-0007": [
        {
            "kind": "prerequisite-repair",
            "artifact": "registry/test_group_index.json",
            "owner": "scripts/build_test_group_index.py",
            "summary": (
                "Test group index reconciled after this round added evidence scripts. This is a "
                "declared-generated-truth dependency of the source-boundary surface, not a "
                "hand-edit."
            ),
            "supports": "generated projections refreshed via owners; boundary work unblocked",
        },
    ],
}


def main() -> int:
    for gap_id, items in EVIDENCE.items():
        path = WORK / f"{gap_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        existing = record.get("completion_evidence")
        assert isinstance(existing, list), f"{gap_id}: completion_evidence is not a list"
        record["completion_evidence"] = existing + items
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{gap_id}: completion_evidence now {len(record['completion_evidence'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())