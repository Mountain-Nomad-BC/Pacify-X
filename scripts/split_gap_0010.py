"""Split PX-GAP-0010 into its confirmed and non-reproducing components.

Writes a split disposition into the gap record without removing any original
field. The bundled claim is decomposed into two independently measured parts so
the stale half stops being carried forward as current evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

SPLIT = {
    "measured_at": "2026-10-02",
    "disposition": "split-into-one-confirmed-and-one-stale",
    "reason_for_split": (
        "PX-GAP-0010 bundled two independent defects under a single 'full suite cannot "
        "complete' feature. They have different owners, different dependencies, and "
        "different truth values. Re-measuring each separately is required before either "
        "can be worked or closed."
    ),
    "components": [
        {
            "component_id": "PX-GAP-0010-A",
            "subject": "tests/test_architecture_atlas.py raises FileNotFoundError at collection time",
            "status": "CONFIRMED",
            "live_measurement": (
                "python -m pytest tests/test_architecture_atlas.py --collect-only -q => "
                "exit code 2, FileNotFoundError: docs/architecture/reference/"
                "graph_baseline_architecture.json, 'Interrupted: 1 error during collection, "
                "no tests collected'. Reproduced twice on 2026-10-02, before and after this "
                "round's changes."
            ),
            "root_cause": "The module reads the reference baseline at import time and the file does not exist in the repository.",
            "real_owner_gap": "PX-GAP-0008",
            "dependencies": ["PX-GAP-0008"],
            "note": (
                "This component is not independently actionable. Repairing it requires the "
                "authoritative provenance of graph_baseline_architecture.json, which is "
                "PX-GAP-0008's blocker. A recursive search of C:\\Users\\Ben\\Downloads found "
                "no copy, so the input cannot currently be regenerated from authoritative "
                "sources and must not be hand-reconstructed."
            ),
            "blocks_full_suite": True,
            "next_action": "Resolve under PX-GAP-0008. Leave PX-GAP-0010-A open and dependent.",
        },
        {
            "component_id": "PX-GAP-0010-B",
            "subject": "tests/test_release_preflight_inputs.py aborts the session with pytest INTERNALERROR",
            "status": "STALE-NOT-REPRODUCING",
            "live_measurement": (
                "python -m pytest tests/test_release_preflight_inputs.py -q => 43 passed, "
                "0 failed, 0 errors, exit code 0, in approximately 6 seconds. The named test "
                "test_static_callback_order_and_construction_stay_lazy exists at "
                "tests/test_release_preflight_inputs.py:247 and passes."
            ),
            "historical_claim": (
                "Collects 43 tests, passes 39, then dies with INTERNALERROR, caused by a "
                "global monkeypatch of pathlib.Path.stat at line 225 whose AssertionError "
                "escapes into pytest's own reporting machinery."
            ),
            "why_it_no_longer_reproduces": (
                "The test no longer patches Path.stat globally. scoped_io_guard() at line 221 "
                "installs a FRAME-SCOPED guard: guarded() walks sys._getframe(1) and its "
                "back-chains and only raises when the calling frame belongs to "
                "runtime/release_preflight.py. Rejection is therefore confined to the module "
                "under test, which is exactly the property under test, while pytest's own "
                "reporting machinery is never blocked. The test additionally restores the "
                "patch eagerly in a finally block via monkeypatch.undo() before any assertion "
                "runs, so reporting never executes against the guard."
            ),
            "code_evidence": [
                "tests/test_release_preflight_inputs.py:221-244 scoped_io_guard with a docstring explicitly documenting the global-patch INTERNALERROR mechanism",
                "tests/test_release_preflight_inputs.py:253 monkeypatch.setattr(Path, 'stat', guarded_stat)",
                "tests/test_release_preflight_inputs.py:254-258 try/finally with eager monkeypatch.undo()",
            ],
            "interpretation": (
                "The gap's described defect describes a design that no longer exists in the "
                "code. The gap is therefore stale with respect to this component, not merely "
                "unreproducible in this environment. Do NOT carry this claim forward as "
                "current evidence, and do not spend repair effort here."
            ),
            "blocks_full_suite": False,
            "next_action": (
                "Close as stale-not-reproducing. The historical claim is preserved verbatim in "
                "this record's observed_behavior; it is annotated rather than deleted."
            ),
        },
    ],
    "net_effect_on_the_gap_feature": (
        "The parent feature, 'the governed full test suite must be able to run to "
        "completion', is still blocked, but solely by PX-GAP-0010-A via PX-GAP-0008. "
        "PX-GAP-0010-B imposes no remaining constraint and should no longer be cited as a "
        "blocker."
    ),
    "preservation_statement": (
        "No original field of PX-GAP-0010 was removed or rewritten. observed_behavior still "
        "contains the original bundled claim including the stale INTERNALERROR assertion. This "
        "split is additive and is itself the contradiction-preserving record."
    ),
    "next_action": (
        "Work PX-GAP-0010-A through PX-GAP-0008 provenance resolution. Treat PX-GAP-0010-B as "
        "closed-stale and stop citing it."
    ),
}


def main() -> int:
    path = WORK / "PX-GAP-0010.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["split_disposition"] = SPLIT
    record["reconciliation"] = {
        "measured_at": "2026-10-02",
        "disposition": "split-one-confirmed-one-stale",
        "measurement": {
            "claim_A_atlas_collection": "CONFIRMED - exit 2, FileNotFoundError at collection",
            "claim_B_release_preflight": "NOT_REPRODUCING - 43 passed, exit 0",
        },
        "supersedes_prior_note": (
            "The earlier reconciliation recorded claim B as merely 'not reproducing'. Live "
            "code inspection shows the described global-patch defect no longer exists in the "
            "source, so the component is stale rather than flaky."
        ),
    }
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"split written to {path.name}")
    print("  PX-GAP-0010-A: CONFIRMED (owner PX-GAP-0008)")
    print("  PX-GAP-0010-B: STALE-NOT-REPRODUCING")
    print(f"  original observed_behavior preserved: {len(record['observed_behavior'])} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())