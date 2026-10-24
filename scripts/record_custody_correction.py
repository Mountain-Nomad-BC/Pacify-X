"""Record completion evidence for PX-GAP-0015 and the custody correction."""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

EVIDENCE = {
    "PX-GAP-0011": [
        {
            "kind": "custody-correction",
            "artifact": ".agentic_engineering_os_px/registers/evidence-custody-decision.json",
            "summary": (
                "The two-root custody model was corrected to three roots after discovering that "
                "the top-level evidence/ root is a declared PACKAGED PRODUCT ARTIFACT root "
                "(pyproject.toml:121) required in the working tree by "
                "runtime/source_coverage.py and runtime/capability_assimilation.py. Retaining "
                "only extension/evidence/ would have made valid packaged artifacts "
                "unexportable. The declaration now names all three roots with one owner each."
            ),
            "supports": "custody model corrected before any repair depended on it",
        }
    ],
    "PX-GAP-0015": [
        {
            "kind": "measurement",
            "artifact": "scripts/report_packaged_evidence_presence.py",
            "summary": (
                "All twelve declared packaged evidence artifacts are absent: the top-level "
                "evidence/ tree does not exist and no copy exists anywhere under "
                "C:\\Users\\Ben\\Music\\Downloads or the reference corpus."
            ),
            "supports": "registered as an unrecoverable-content gap, not a custody problem",
        },
        {
            "kind": "blocked-generator-analysis",
            "artifact": "scripts/migration/admit_capability_mining_skills.py",
            "summary": (
                "capability-mining-receipt.json is written by this script, but it is a one-time "
                "skill-admission migration that mutates registry/skill_catalog.toml, "
                "registry/engineering_lifecycle.json and fifty-plus skill packages. Running it to "
                "manufacture a receipt would be a speculative side-effecting migration, not a "
                "repair, so it was not run."
            ),
            "supports": "generator identified and deliberately not invoked",
        },
        {
            "kind": "adversarial-constraint",
            "artifact": "runtime/capability_assimilation.py:118-126",
            "summary": (
                "The mining receipt must bind the live sha256 of "
                "registry/capability_mining_admission.json and a files_accounted denominator of "
                "618 computed from a real scan. It cannot be hand-authored without asserting "
                "values that were never measured."
            ),
            "supports": "placeholder creation was structurally impossible to do honestly",
        },
    ],
}

RECIPIENT = {
    "schema_version": "px.evidence-custody-correction-receipt/1.0",
    "receipt_id": "evidence-custody-three-root-correction",
    "campaign_id": "prj_pacify_x_rev1xx_unbuilt-initial-operational-repair",
    "measured_at": "2026-10-02",
    "git_touched": False,
    "finding": (
        "The two-root Option A custody model was incomplete and, on one point, wrong. It "
        "treated the top-level evidence/ root as wholly undeclared, but pyproject.toml:121 "
        "declares eleven named receipts plus the archive-custody-20260803 bundle as packaged "
        "distribution data, and two runtime validators require specific files in that tree to "
        "exist in the working tree. The two-root model asserted that the absence of "
        "evidence/process-audit-intake-receipt.json and "
        "evidence/capability-mining-receipt.json was a pure custody-location problem. That was "
        "incorrect on two counts: those paths are already the declared packaged locations, so "
        "re-pointing them would have been wrong; and both receipts are COMPUTED artifacts with "
        "declared generators, not archival history."
    ),
    "correction": {
        "model": "three-root-explicitly-declared",
        "roots": [
            "evidence/ : packaged product-artifact receipts, retained by name via PACKAGED_PRODUCT_EVIDENCE and PACKAGED_PRODUCT_EVIDENCE_TREES, mirroring the pyproject.toml declaration",
            ".agentic_engineering_os_px/test-evidence/ : source-tree governed verification receipts, retained via RETAINED_TEST_RECEIPT_ROOTS",
            "extension/evidence/ : installed-artifact and VSIX certification evidence, retained via RETAINED_DISTRIBUTION_EVIDENCE_TREES",
        ],
        "still_excluded": [
            "evidence/bundles/** except the declared archive-custody bundle",
            "evidence/release/**",
            "any evidence-shaped path not declared packaged in pyproject.toml",
            "node_modules, build, dist, caches and every other dependency or generated tree",
        ],
    },
    "bugs_caught_by_the_verifier": [
        "First implementation guarded only the root evidence/ clause, but the packaged files were still excluded by the EXCLUDED_DIRS segment intersection and by is_external_environment_relative. Detected because the positive retention assertion failed.",
        "Packaged files declared with a glob in pyproject.toml (the archive-custody bundle) were missing from the carve-out. Detected by the new pyproject-to-export alignment check, which reported one unmirrored declared member.",
        "The alignment check initially compared wildcard declarations literally. Corrected to compare glob members by tree prefix rather than by exact literal.",
    ],
    "validation": {
        "positive": [
            "synthetic tree: both declared packaged receipts RETAINED",
            "pyproject packaged declaration mirrors the export carve-out exactly: 11 literal members aligned",
            "extension/evidence/ retained including nested receipts",
            "source-tree governed receipts retained",
        ],
        "negative": [
            "synthetic tree: evidence/bundles/archive/manifest.json EXCLUDED",
            "synthetic tree: evidence/release/historical.json EXCLUDED",
            "synthetic tree: evidence/not-a-declared-receipt.json EXCLUDED, proving retention is by declared name and not by directory",
            "synthetic tree: node_modules, build, dist, .pytest_cache and __pycache__ all EXCLUDED",
            "synthetic tree: .agentic_engineering_os_px/scratch-notes.md EXCLUDED",
        ],
    },
    "registry_resolution": {
        "before": "3 errors",
        "after": "2 errors",
        "repaired": "provider invocation bypass: registry/provider_route_scan.json index_stale",
        "repair_owner": "scripts/build_provider_route_index.py",
        "repair_result": "valid=true, 538 files, 0 violations",
        "safety": "The generator is a pure read-then-write index builder: it calls runtime.provider_gateway.build_provider_route_index(ROOT) and writes only registry/provider_route_scan.json. It has no side effects on any other surface.",
        "remaining": [
            "source coverage: verified-process-to-skill-candidate: missing owner evidence/process-audit-intake-receipt.json",
            "capability assimilation: capability mining receipt is missing",
        ],
        "remaining_classification": "Both remaining errors are PX-GAP-0015: declared packaged artifacts that are absent from both the working tree and the reference corpus. They are content-recovery problems, not custody or configuration problems, and no legitimate action available in this tree can close them.",
    },
    "not_claimed": [
        "Registry validity is NOT restored; two errors remain.",
        "Installed-artifact certification is NOT complete.",
        "PX-GAP-0008, PX-GAP-0011, PX-GAP-0012, PX-GAP-0015 remain open.",
        "No evidence artifact was synthesized, stubbed, copied or manually hashed.",
        "The one-time skill-admission migration was deliberately NOT run.",
        "No Git or source-control requirement was satisfied or evaluated.",
        "The repair-campaign intake remains open."
    ],
}


def main() -> int:
    for gap_id, items in EVIDENCE.items():
        path = WORK / f"{gap_id}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        record["completion_evidence"] = record.get("completion_evidence", []) + items
        path.write_text(
            json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"{gap_id}: completion_evidence now {len(record['completion_evidence'])}")

    target = (
        Path(__file__).resolve().parents[1]
        / ".agentic_engineering_os_px"
        / "registers"
        / "evidence-custody-correction-receipt.json"
    )
    target.write_text(
        json.dumps(RECIPIENT, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())