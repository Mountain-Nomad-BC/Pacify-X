"""Close out the remaining gap dispositions in a single governed pass.

Each disposition below was established by live measurement earlier in this
recovery round. This script only records those outcomes into the authoritative
gap records; it performs no repair and invents no measurement.

Append-only: no original field of any gap record is removed or rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

DISPOSITIONS: dict[str, dict[str, object]] = {
    "PX-GAP-0001": {
        "measured_at": "2026-10-02",
        "disposition": "open-control-target-does-not-exist",
        "measurement": "runtime/vscode_model_bridge.py exists as the canonical model bridge. No router.js exists anywhere under extension/.",
        "contradiction": (
            "The recorded control action names router.js chooseWorker as the Auto "
            "delegation target. The file it names does not exist in the repository, so "
            "the control action cannot be executed as written."
        ),
        "why_not_repaired": (
            "Repairing this requires knowing the intended Auto-selection mechanism. "
            "Guessing at a replacement for a named-but-absent file would invent an "
            "architecture rather than repair one."
        ),
        "next_action": (
            "Owner decision required: either identify the real Auto-selection "
            "delegation path, or restate the control action against the surface that "
            "actually implements Auto routing."
        ),
    },
    "PX-GAP-0003": {
        "measured_at": "2026-10-02",
        "disposition": "stale-not-reproducing",
        "measurement": (
            "registry/operational_gap_ledger.deltas exists and contains 0 files. The gap "
            "asserts 906 unreferenced superseded delta checkpoints. There is nothing to "
            "reclaim."
        ),
        "existing_capability": (
            "runtime/operational_gap_ledger.py already implements "
            "reclaim_delta_checkpoints(root, authorization=...) returning a retained "
            "receipt, with DELTA_CHECKPOINT_THRESHOLD_BYTES and "
            "MAX_DELTA_CHECKPOINT_BYTES bounds."
        ),
        "next_action": (
            "Supersede the 906-checkpoint claim with the empty-delta measurement. Do NOT "
            "delete anything under an authorization premise that no longer holds."
        ),
    },
    "PX-GAP-0004": {
        "measured_at": "2026-10-02",
        "disposition": "superseded-by-existing-implementation",
        "measurement": (
            "python -m pytest tests/test_operational_gap_ledger_delta_lifecycle.py -q => "
            "9 passed in 71.24s"
        ),
        "why_superseded": (
            "Every required capability already exists and is proven: incremental "
            "explicitly-parented deltas, compaction driven by aggregate retained bytes and "
            "chain depth, a governed reclamation path with retained receipt, and head "
            "resolution after compaction. Re-implementing would create the duplicate "
            "authority this campaign exists to prevent."
        ),
        "remaining_test": (
            "The linear-not-quadratic retained-storage growth assertion is the only "
            "tests_required item not directly proven by that module."
        ),
        "next_action": "Close as superseded with the passing test evidence.",
    },
    "PX-GAP-0005": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-governed-path-unsafe",
        "measurement": (
            "engineering-workspace.toml line 25 declares integrity_hash = \"sha256\", an "
            "algorithm rather than a seal. No integrity seal field exists."
        ),
        "blocker_confirmed": (
            "The only governed repair path is full commissioning, which scaffolds "
            "AGENTS.md, AI_ASSISTANT.md and CLAUDE.md into the project root and widens "
            "scope beyond a repair campaign."
        ),
        "why_not_repaired": (
            "Fabricating a seal by hand would assert an integrity property that was never "
            "computed. Running full commissioning would perform an unrelated structural "
            "change. Neither is a repair."
        ),
        "next_action": (
            "Owner decision: add a governed re-seal path that neither runs full "
            "commissioning nor hand-fabricates the seal."
        ),
    },
    "PX-GAP-0006": {
        "measured_at": "2026-10-02",
        "disposition": "superseded-by-source-boundary-repair",
        "measurement": (
            "extension/server/index.js is 33743 lines with 37 require( occurrences and "
            "retains 11 recoverable __commonJS factories. extension/src/ contains 51 "
            "authored source modules and extension/package.json declares main "
            "./src/extension.js."
        ),
        "stale_evidence_corrected": (
            "The originally recorded '33639 lines, 534 definitions, zero require()' is "
            "stale. Live measurement is 33743 lines and 37 require() occurrences."
        ),
        "why_superseded": (
            "The premise that this was a monolith with no module boundaries is false. "
            "Modular boundaries exist as authored source under extension/src/. The real "
            "defect was that a stale generated bundle was classified as authored, and that "
            "defect was repaired under PX-GAP-0007 by declaring the bundle "
            "packaging_generated and rebuilding it through its declared generator."
        ),
        "next_action": "Close as superseded. Decomposition was never required and would have destroyed recoverable structure.",
    },
    "PX-GAP-0011": {
        "measured_at": "2026-10-02",
        "disposition": "custody-resolved-corpus-still-absent",
        "measurement": (
            "The three-root custody model is declared and verified. The "
            "cohesion-closure card corpus at .agentic_engineering_os_px/punch-cards/ is still "
            "absent, and no copy exists anywhere under C:\\Users\\Ben\\Music\\Downloads or "
            "the reference corpus."
        ),
        "what_was_repaired": (
            "The architecture/governance decision this gap was blocked on is now made and "
            "recorded: three canonical evidence roots, one architectural owner each, "
            "verified by scripts/verify_evidence_custody.py including a check that the "
            "export carve-out mirrors the pyproject.toml packaged declaration."
        ),
        "what_remains": (
            "The card corpus itself is content that does not exist in this tree or the "
            "reference corpus, so it cannot be regenerated. No placeholder cards were "
            "created to silence tests."
        ),
        "next_action": "Recover the corpus from an owner-held prior source, or record an explicit scope decision.",
    },
    "PX-GAP-0013": {
        "measured_at": "2026-10-02",
        "disposition": "partially-repaired-residual-is-content",
        "measurement": (
            "Source-tree records declared current rose from 0 of 16 to 9 of 16 after "
            "regeneration through scripts/build_current_evidence_index.py --apply. Two VSIX "
            "receipts remain missing-unavailable-pending-certification by design."
        ),
        "what_was_repaired": (
            "A blocking prerequisite was found and fixed: adding evidence scripts had "
            "invalidated the test group index, which made the certification receipt policy "
            "unreadable ('test group membership is stale; explicit reconciliation "
            "required') and prevented the evidence index from evaluating currentness at "
            "all. Regenerated through scripts/build_test_group_index.py."
        ),
        "what_remains": (
            "Seven source-tree records are still not current because their governed "
            "section and profile receipts are not themselves current; producing those is a "
            "repair-campaign stage, not a diagnosis action. The two VSIX receipts require "
            "real installed-artifact certification and were not synthesized."
        ),
        "next_action": "Run the governed harness to refresh section and profile receipts, then re-project the index.",
    },
}


def main() -> int:
    for gap_id, disposition in DISPOSITIONS.items():
        path = WORK / f"{gap_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["reconciliation"] = disposition
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{gap_id}: {disposition['disposition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())