"""Update .agentic_engineering_os_px/registers/rev1xx-change-register.json.

Appends a recovery-round record describing what was actually measured and
repaired in this round. The historical registered_gaps / next_actions entries
are preserved verbatim; the new round record states where current measurement
contradicts them, so stale claims are corrected rather than silently replaced.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

REGISTER = (
    Path(__file__).resolve().parents[1]
    / ".agentic_engineering_os_px"
    / "registers"
    / "rev1xx-change-register.json"
)

ROUND = {
    "round_id": "rev1xx-recovery-2026-10-02",
    "recorded_at": "2026-10-02",
    "recorded_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "intake_state": "remains open; not closed to satisfy the phase ladder",
    "source_control": {
        "git_touched": False,
        "disposition": "deferred_by_owner_until_pre_release_source_control_freeze",
        "note": "No Git operation was performed. PX-GAP-0012 / BASE-001 remain open-deferred.",
    },
    "repaired": [
        {
            "surface": "semantic-contracts",
            "gap_ids": ["PX-GAP-0002"],
            "change": "Four semantic contracts repaired: canonical URN $id, maxLength expressed in the supported dialect, four ownership records added, contract_count 180 -> 184.",
            "owner": "contracts/*, registry/contract_ownership.json",
            "evidence": "registry errors 29 -> 3; all 26 semantic-contract errors cleared",
        },
        {
            "surface": "build-claims",
            "gap_ids": ["PX-GAP-0002"],
            "change": "README and stored build-claim denominators regenerated through the declared owner after denominator drift was detected.",
            "owner": "scripts/build_claims.py --apply",
            "claims": {
                "runtime_modules": 387,
                "contracts": 184,
                "registry_artifacts": 521,
                "tool_and_support_scripts": 210,
            },
            "evidence": "valid_build_claims true; document errors 4 -> 0; 51 tests pass",
        },
        {
            "surface": "evidence-custody",
            "gap_ids": ["PX-GAP-0011", "PX-GAP-0013"],
            "change": "Two-root evidence custody declared. .agentic_engineering_os_px/test-evidence/ remains the canonical source-tree verification root; extension/evidence/ is now a declared retained distribution root for installed-artifact certification.",
            "owner": "scripts/clean_source_export.py, .agentic_engineering_os_px/registers/evidence-custody-decision.json",
            "evidence": "scripts/verify_evidence_custody.py confirms both roots retained and unrelated generated/dependency/history/undeclared-evidence trees still excluded",
        },
        {
            "surface": "test-group-index",
            "gap_ids": ["PX-GAP-0007"],
            "change": "Test group index regenerated after new evidence scripts invalidated test membership, which had made the certification receipt policy unreadable.",
            "owner": "scripts/build_test_group_index.py",
            "evidence": "section_status and group_status resolve again instead of raising",
        },
        {
            "surface": "current-evidence-index",
            "gap_ids": ["PX-GAP-0013"],
            "change": "Evidence index regenerated through its declared owner.",
            "owner": "scripts/build_current_evidence_index.py --apply",
            "evidence": "source-tree records declared current rose from 0 to 9 of 16; index remains valid=false for legitimate release-stage reasons only",
        },
    {
            "surface": "registry-envelope-ownership",
            "gap_ids": ["PX-GAP-0014"],
            "change": "Six of seven unowned count fields now declared and verified. Two envelope rules added (nested_nonempty, sum_bytes). One field exempted via the repo's existing UNOWNED_COUNT_FIELDS mechanism.",
            "owner": "registry/registry_envelope_inventory.json, runtime/registry_envelope.py",
            "evidence": "validate_registry_envelopes now valid=true with 88 records; 21 tests pass; all 5 corruption attempts rejected",
        },
        {
            "surface": "gap-0010-split",
            "gap_ids": ["PX-GAP-0010"],
            "change": "Bundled gap decomposed. Claim A (atlas collection) confirmed. Claim B (pytest INTERNALERROR) classified stale because the described global Path.stat monkeypatch no longer exists and has been replaced by a frame-scoped guard.",
            "evidence": "claim A exit 2 with FileNotFoundError; claim B 43 passed exit 0; tests/test_release_preflight_inputs.py:221-244 documents the replaced design",
        },
        {
            "surface": "source-boundary-authority",
            "gap_ids": ["PX-GAP-0009"],
            "change": "Canonical boundary owner designated as runtime/source_boundary.py. Repaired classify_path falling through to AUTHORED for host toolchains, .git, .venv, quarantine, audit, scratch and derived custody paths, plus a pre-existing exact-match defect on build and dist.",
            "owner": "runtime/source_boundary.py",
            "evidence": "boundary conformance over a 48-path corpus improved from 26 disagreements to 3 intentional and recorded; tests/test_boundary_conformance.py committed as a standing regression corpus",
        },
    {
            "surface": "generated-artifact-boundary",
            "gap_ids": ["PX-GAP-0006", "PX-GAP-0007"],
            "change": "extension/server/index.js reclassified from authored to packaging_generated with its real generator, inputs and regeneration command; bundle rebuilt through that declared owner and confirmed current by npm run check:mcp; all bound manifests regenerated through their owners.",
            "owner": "runtime/source_boundary.py, extension/scripts/build-mcp.js",
            "evidence": "validate_artifacts attributes the artifact with zero problems; check:mcp exits 0 where it previously exited 1; source_freeze file_count 521 now matches expected_build_claims; 32 boundary and freeze tests pass",
        },
        {
            "surface": "provider-route-index",
            "gap_ids": ["PX-GAP-0010"],
            "change": "Stale required projection regenerated through its declared owner.",
            "owner": "scripts/build_provider_route_index.py",
            "evidence": "valid=true, 538 files, 0 violations; removed one of the three residual registry errors",
        },
    ],
    "adversarial_validation_summary": {
        "envelope_corruption_attempts": "5 of 5 rejected across 3 documents",
        "boundary_conformance_corpus": "48 paths; disagreements reduced 26 -> 3, all 3 recorded as intentional",
        "self_corrections_during_authoring": [
            "The custody verification harness caught a real ordering bug in my own first export implementation: EXCLUDED_DIRS matched before the distribution carve-out was consulted, so extension/evidence was still excluded.",
            "The envelope corruption harness initially reported 82 false errors because the staged tree omitted the 80+ registry documents the inventory references. Fixed the harness rather than trusting the output.",
            "The boundary conformance corpus initially asserted three cases the live modules did not support, including a path name I invented. Each was re-measured and corrected against the modules rather than weakening the assertion.",
        ]
    },
    "evidence_states": {
        "current": "receipt exists and is declared current by the index",
        "stale": "receipt exists but is not declared current; must be regenerated through its owner, never hand-edited",
        "missing_unavailable_pending_certification": (
            "installed-VSIX smoke receipts for win32 and linux; these cannot be produced "
            "until a real installed artifact is certified. Their absence is a legitimate "
            "unresolved release-stage condition, not evidence corruption."
        ),
    },
    "contradicts_historical_register": [
        {
            "gap_id": "PX-GAP-0008",
            "historical_claim": "repairable",
            "current_measurement": "build_atlas.py consumes the baseline at :495 and hashes it at :805-806; no producer exists. Reconstruction refused because the parity test compares the baseline against canonical_systems.json and rebuilding it from that source would be circular.",
            "disposition": "open-provenance-unresolved; the sole remaining blocker against a full-suite run"
        },
        {
            "gap_id": "PX-GAP-0009",
            "historical_claim": "two competing owners with no declared authority",
            "current_measurement": "runtime/source_boundary.py is self-declared canonical with fixed precedence, owner/consumer metadata and fail-closed validation; conformance against repository_scope measured at 26 disagreements before repair and 3 after",
            "disposition": "canonical owner established and conformance enforced"
        },
        {
            "gap_id": "PX-GAP-0003",
            "historical_claim": "502.7 MB of orphaned cumulative checkpoints reclaimed; state narrowly_verified",
            "current_measurement": "registry/operational_gap_ledger.deltas contains 0 files; nothing is reclaimable now",
            "disposition": "historical claim retained; current disposition is stale-not-reproducing",
        },
        {
            "gap_id": "PX-GAP-0006",
            "historical_claim": "extension server is a 33639-line zero-require bundle with no module boundaries",
            "current_measurement": (
                "extension/server/index.js is 33743 lines with 37 require() occurrences and retains "
                "11 recoverable CommonJS factories; extension/src/ contains 51 authored source "
                "modules and extension/package.json declares main ./src/extension.js"
            ),
            "disposition": "largely superseded; the real defect is a stale generated bundle treated as source",
        },
        {
            "gap_id": "PX-GAP-0013",
            "historical_claim": "recorded stale acceptance evidence",
            "current_measurement": "0 of 18 indexed records were current before this round; 9 of 16 source-tree records are current after regeneration; 2 VSIX receipts remain legitimately missing",
            "disposition": "confirmed and repaired within the declared custody model",
        },
    ],
    "newly_registered": [
        {
            "gap_id": "PX-GAP-0014",
            "surface": "registry-envelope-ownership",
            "severity": "high",
            "state": "repaired-one-governed-exception",
            "summary": "six of seven count fields declared and verified; expected_unique_payload_count exempted via UNOWNED_COUNT_FIELDS as an externally declared expectation rather than a derived collection count",
        },
        {
            "gap_id": "PX-GAP-0015",
            "surface": "packaged-product-artifact-custody",
            "severity": "blocker",
            "state": "confirmed-content-unrecoverable",
            "summary": "all twelve declared packaged evidence artifacts absent from the tree and the reference corpus; sole remaining cause of two registry errors and one release-artifact test failure",
        }
    ],
    "not_claimed": [
        "Installed-artifact certification is NOT complete.",
        "registry validity is NOT restored; two errors remain, both PX-GAP-0015 content recovery.",
        "PX-GAP-0012 / BASE-001 remain open-deferred.",
        "No gap is closed by this register update alone.",
    ],
}


def main() -> int:
    register = json.loads(REGISTER.read_text(encoding="utf-8"))
    rounds = register.setdefault("recovery_rounds", [])
    rounds = [item for item in rounds if item.get("round_id") != ROUND["round_id"]]
    rounds.append(ROUND)
    register["recovery_rounds"] = rounds
    register["generated_at"] = ROUND["recorded_at_utc"]
    REGISTER.write_text(
        json.dumps(register, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"registered round {ROUND['round_id']}")
    print(f"total recovery_rounds: {len(rounds)}")
    print(f"historical registered_gaps preserved: {len(register['registered_gaps'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())