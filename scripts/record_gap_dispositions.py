"""Write the measured reconciliation disposition into each gap record.

Every disposition is appended under new keys. No original field is removed,
rewritten or overwritten, so contradicting historical evidence is preserved
in place exactly as recorded at discovery.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"
RECEIPT = (
    Path(__file__).resolve().parents[1]
    / ".agentic_engineering_os_px"
    / "registers"
    / "gap-reconciliation-receipt.json"
)

DISPOSITIONS = {
    "PX-GAP-0001": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-not-yet-repaired",
        "measurement": "runtime/vscode_model_bridge.py exists as the canonical model bridge.",
        "contradiction": "The recorded control action delegates Auto selection to router.js chooseWorker. No router.js exists anywhere under extension/. The recorded control target must be corrected before repair.",
    },
    "PX-GAP-0002": {
        "measured_at": "2026-10-02",
        "disposition": "mostly-satisfied-one-criterion-open",
        "measurement": {
            "status": "valid=true managed=true phase=intake intake_open=true unresolved_count=1",
            "stage_diagnose": "PASS",
            "stage_repair": "REFUSED (requires phase repair; current=intake)",
            "stage_certify": "REFUSED (requires phase installed_operational; current=intake)",
            "stale_state": ".agentic_engineering_os_px/project-management/state.json still carries revision=44, lifecycle.phase=repair12-freeze-and-final100-release, lifecycle.status=downstream-green-release-pending, approved_effects=[read_local, write_workspace, execute_local_focused], repository.branch=main, repository.commit=0cf881533070214130ac30e797299b9758e6aa29",
        },
        "criteria_satisfied": [
            "status reports phase and unresolved denominator",
            "check --stage diagnose passes at phase intake",
            "check --stage certify is refused before installed-operational",
        ],
        "criteria_open": [
            "the stale revision-44 project-management state does not authorize any stage",
        ],
        "severity_reassessment": "The campaign boundary genuinely exists and correctly refuses downstream stages. The remaining blocker is narrower than recorded: a stale competing authorization surface, not a missing boundary.",
        "next": "Quarantine or explicitly supersede the revision-44 state so it cannot authorize effects. Do not delete the historical record.",
    },
    "PX-GAP-0003": {
        "measured_at": "2026-10-02",
        "disposition": "stale-not-reproducing",
        "measurement": {
            "delta_directory": "registry/operational_gap_ledger.deltas exists with 0 files",
            "claimed_reclaimable": 906,
            "actually_reclaimable": 0,
            "ledger_jsonl_bytes": 256015,
            "snapshot_bytes": 259600,
            "head_bytes": 32666,
        },
        "contradiction": "The gap asserts 906 unreferenced superseded delta checkpoints. The delta store is empty, so there is nothing to reclaim.",
        "existing_capability": "runtime/operational_gap_ledger.py already implements reclaim_delta_checkpoints(root, authorization=...) returning a retained receipt, with DELTA_CHECKPOINT_THRESHOLD_BYTES and MAX_DELTA_CHECKPOINT_BYTES bounds.",
        "next": "Re-measure whether unbounded growth can still occur by exercising the ledger, then either supersede with the measurement or re-register against a reproducible growth condition. Do NOT delete anything under an authorization premise that no longer holds.",
    },
    "PX-GAP-0004": {
        "measured_at": "2026-10-02",
        "disposition": "superseded-by-existing-implementation",
        "measurement": "python -m pytest tests/test_operational_gap_ledger_delta_lifecycle.py -q => 9 passed in 71.24s",
        "why_superseded": "Every required capability already exists and is proven: incremental explicitly-parented deltas, compaction driven by aggregate retained bytes and chain depth, a governed reclamation path with retained receipt, and head resolution after compaction. Do not re-implement.",
        "remaining_test": "The linear-not-quadratic retained-storage growth assertion is the only tests_required item not directly proven by that module.",
        "next": "Confirm the linear-growth assertion explicitly, then supersede with passing evidence.",
    },
    "PX-GAP-0005": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-with-partial-contradiction",
        "measurement": "engineering-workspace.toml line 25 declares integrity_hash = \"sha256\", an algorithm rather than a seal. No integrity seal field exists.",
        "blocker_confirmed": "The only governed repair path is full commissioning, which scaffolds AGENTS.md, AI_ASSISTANT.md and CLAUDE.md into the project root and widens scope beyond repair.",
        "next": "Unchanged. Requires a governed re-seal path that does not run full commissioning and does not hand-fabricate the seal.",
    },
    "PX-GAP-0006": {
        "measured_at": "2026-10-02",
        "disposition": "largely-superseded",
        "measurement": {
            "bundle_bytes": 1406374,
            "bundle_lines": 33743,
            "bundle_requires": 37,
            "source_mjs_bytes": 37232,
            "source_mjs_lines": 420,
            "surviving_commonjs_factories": 11,
            "sourcemap_for_bundle": False,
            "authored_source_modules_under_extension_src": 51,
            "package_main": "./src/extension.js",
        },
        "stale_evidence_corrected": "The originally recorded '33639 lines, 534 definitions, zero require()' is stale. Live measurement is 33743 lines and 37 require( occurrences, which confirms the prior audit's correction.",
        "contradiction": "The gap's premise of 'a single self-contained bundle with no module boundaries' is false. Modular boundaries exist as authored source under extension/src/, including extension.js (162894 bytes), coordinationManager.js (77445), pxBridge.js (55957), studioDraftHost.js (41492), studioCatalog.js (32694). The bundle additionally retains 11 recoverable CommonJS factories.",
        "real_defect": "A stale 1.4 MB generated bundle is committed and consumable as if it were source. That is a source-boundary and custody defect, not a decomposition project.",
        "next": "Reclassify as a generated-artifact boundary issue under PX-GAP-0007. Establish whether server/index.js is reachable from any governed entry point, declare it as a generated artifact with its owning generator, and do not hand-decompose it.",
    },
    "PX-GAP-0007": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-partially-implemented",
        "measurement": "runtime/source_boundary.py exists (23822 bytes) and already defines GENERATED_ARTIFACTS with per-artifact owner/consumer metadata plus validate_artifacts, classify_path, authored_paths, unbuilt_profile, census and assert_generated_never_canonical_authority.",
        "contradiction": "The gap understates existing capability. A validating declared-boundary mechanism already exists; the open question is coverage, not existence.",
        "next": "Run validate_artifacts and census against the live tree to measure actual coverage and identify concrete uncovered generated paths including docs/architecture/* and extension/server/index.js. Resolve the engine_identity dependency on the generated atlas before excluding atlas bytes.",
    },
    "PX-GAP-0008": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-provenance-unresolved",
        "measurement": "python -m pytest tests/test_architecture_atlas.py --collect-only -q => exit 2, FileNotFoundError on docs/architecture/reference/graph_baseline_architecture.json, 'no tests collected, 1 error during collection'.",
        "provenance_search": "Recursive search of C:\\Users\\Ben\\Downloads for graph_baseline_architecture* returned zero results. No punch-cards directory or PX-COMM-* identifiers found under the px_next steps reference corpus.",
        "instruction_honored": "The baseline was NOT hand-reconstructed, per this gap's own explicit prohibition.",
        "next": "Establish authoritative provenance before any repair: registry state, the generator's declared inputs, docs/architecture/reference/ORIGINAL_36_GRAPH_REQUIREMENTS.md, and any manifest or provenance record. If provenance cannot be established, leave open and record the unresolved provenance rather than fabricating the input.",
    },
    "PX-GAP-0009": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed",
        "measurement": "Both competing owners exist and are live: runtime/repository_scope.py (3134 bytes) and runtime/source_boundary.py (23822 bytes).",
        "blocker_confirmed": "Designating a canonical owner changes a widely-consumed boundary API, so the decision must be governed rather than incidental to the 0007 repair.",
        "next": "Unchanged. Designate one canonical owner, add a conformance corpus that runs both over every path and fails closed on disagreement, and have repository_scope delegate while preserving its public behaviour.",
    },
    "PX-GAP-0010": {
        "measured_at": "2026-10-02",
        "disposition": "split-one-confirmed-one-stale",
        "claim_A_atlas_collection": {
            "status": "CONFIRMED",
            "measurement": "tests/test_architecture_atlas.py --collect-only exits 2 with FileNotFoundError; 'no tests collected, 1 error during collection'.",
            "owner_gap": "PX-GAP-0008",
        },
        "claim_B_io_guard_internal_error": {
            "status": "NOT_REPRODUCING",
            "measurement": "python -m pytest tests/test_release_preflight_inputs.py -q => 43 passed in 6.10s, exit 0. test_static_callback_order_and_construction_stay_lazy exists at tests/test_release_preflight_inputs.py:247 and passes.",
            "note": "The prior audit's pytest INTERNALERROR claim from this file does not reproduce and is stale.",
        },
        "conclusion": "This gap bundles a real defect with a stale one. Only claim A reproduces, and it is already owned by PX-GAP-0008.",
        "next": "Split 0010. Retain claim A dependent on 0008; record claim B as not-reproducing with this measurement. Do not carry the stale claim forward as current evidence.",
    },
    "PX-GAP-0011": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-corpus-unrecoverable",
        "measurement": {
            "punch_cards_dir_exists": False,
            "required_path": ".agentic_engineering_os_px/punch-cards/cohesion-closure-20260904",
            "declared_by": "scripts/reconcile_cohesion_cards.py CARD_DIRECTORY",
            "reference_corpus_search": "No punch-cards directory and no PX-COMM-* card identifiers anywhere under C:\\Users\\Ben\\Downloads\\px_next steps",
        },
        "conclusion": "The cohesion-closure card corpus is absent from both the live tree and the reference corpus and cannot be regenerated from anything currently available.",
        "next": "Resolve as an explicit custody decision in WAVE-02. Do NOT create placeholder cards to silence tests.",
    },
    "PX-GAP-0013": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-and-materially-worse-than-recorded",
        "claim_provenance": "CONTRA-003 in .agentic_engineering_os_px/registers/base-002-supersession-receipt.json, disposition carried-forward-unverified, escalated_gap_id PX-GAP-0013.",
        "measurement": {
            "index": "registry/current_evidence_index.json",
            "records": 18,
            "hash_match": 0,
            "hash_mismatch": 16,
            "file_missing": 2,
            "index_valid_field": False,
            "current_required_receipt_count": 9,
            "missing_files": [
                "extension/evidence/installed-vsix-smoke.json",
                "extension/evidence/installed-vsix-smoke-linux.json",
            ],
            "blocking_reason_count": 6,
        },
        "conclusion": "Every one of the 18 indexed evidence records is non-current; not one hash matches. The index already declares itself invalid. The real blast radius is the entire evidence index, not a 28-card subset.",
        "next": "Treat the evidence index as fully stale. Resolve evidence custody first (WAVE-02), then regenerate through owning generators. Do not hand-edit hashes to force a match.",
    },
    "PX-GAP-0014": {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-newly-registered",
        "measurement": "validate_registry_envelopes() => valid=false, one error class: 7 unowned count fields across registry/plan_corpus.json (archive_count, duplicate_payload_count, expected_unique_payload_count, unique_payload_count), registry/source_freeze.json (byte_count, file_count), registry/punch_card_ledger.json (card_count). registry/registry_envelope_inventory.json holds 82 records and none of these seven.",
        "next": "Close the plan_corpus.json component now. Defer source_freeze to PX-GAP-0012 and punch_card_ledger to PX-GAP-0011.",
    },
}


def main() -> int:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["schema_version"] == "px.gap-reconciliation-receipt/1.0"
    for entry in receipt["dispositions"]:
        gap_id = entry["gap_id"]
        assert gap_id in DISPOSITIONS or gap_id == "PX-GAP-0012", (
            f"no writer entry for {gap_id}"
        )
    missing = sorted(
        set(DISPOSITIONS) ^ {e["gap_id"] for e in receipt["dispositions"]} - {"PX-GAP-0012"}
    )
    assert not missing, f"writer/receipt gap-set mismatch: {missing}"
    print(
        "cross-check: receipt dispositions =="
        " writer entries + PX-GAP-0012 (disposition recorded in its own file)"
    )

    for gap_id, disposition in DISPOSITIONS.items():
        path = WORK / f"{gap_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        assert record["gap_id"] == gap_id, f"identity mismatch in {path}"
        record["reconciliation"] = disposition
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"{gap_id}: {disposition['disposition']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())