"""Record completion evidence for the gaps advanced in the latest sweep.

Appends only. No original gap field is removed or rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

EVIDENCE: dict[str, list[dict[str, object]]] = {
    "PX-GAP-0008": [
        {
            "kind": "provenance-determination",
            "artifact": "PX-GAP-0008.json provenance_determination",
            "summary": (
                "build_atlas.py consumes the baseline at :495 and hashes it at :805-806; no "
                "producer exists anywhere in the repository or the reference corpus. "
                "Reconstruction was refused because tests/test_architecture_atlas.py:39-42 "
                "compares the baseline against canonical_systems.json, so rebuilding it from "
                "that source would make the parity assertion circular."
            ),
            "supports": "open-provenance-unresolved; no substitution performed",
        }
    ],
    "PX-GAP-0009": [
        {
            "kind": "measured-defect-and-repair",
            "artifact": ".agentic_engineering_os_px/registers/px-gap-0009-repair-receipt.json",
            "summary": (
                "classify_path fell through to AUTHORED for host toolchains, .git, .venv, "
                "quarantine, audit, scratch and derived custody paths, plus build/dist via a "
                "pre-existing exact-match bug. Repaired by adding boundary rules with owner and "
                "reason, adding case-insensitive ephemeral-prefix handling mirroring "
                "repository_scope, and fixing the exact=True matching defect."
            ),
            "impact": "external and transient bytes could previously enter engine_identity tree_sha256 and source_freeze",
            "supports": "source identity inputs are now boundary-correct",
        },
        {
            "kind": "positive-and-negative-validation",
            "artifact": "scripts/measure_boundary_conformance.py",
            "summary": "48-path corpus: 26 boundary disagreements before, 3 after, all 3 intentional and recorded.",
            "supports": "canonical owner designated and agreement measured, not asserted",
        },
        {
            "kind": "standing-regression-corpus",
            "artifact": "tests/test_boundary_conformance.py",
            "summary": (
                "Committed conformance corpus asserting that external, vendored, ephemeral, "
                "quarantine and derived paths are never authored, that product source remains "
                "authored, and that the two owners agree on every path outside the recorded "
                "exception set."
            ),
            "test_result": "41 passed across tests/test_boundary_conformance.py, tests/test_source_boundary.py, tests/test_registry_envelopes.py",
        },
    ],
    "PX-GAP-0010": [
        {
            "kind": "split-disposition",
            "artifact": "PX-GAP-0010.json split_disposition",
            "summary": (
                "Claim A (atlas collection FileNotFoundError) confirmed by live reproduction; "
                "claim B (pytest INTERNALERROR) is stale, because the described global "
                "Path.stat monkeypatch no longer exists in the source and has been replaced by "
                "a frame-scoped guard at tests/test_release_preflight_inputs.py:221-244 with "
                "eager monkeypatch.undo() restoration."
            ),
            "measurements": [
                "claim A: --collect-only exit 2, no tests collected",
                "claim B: 43 passed, exit 0",
            ],
            "supports": "the gap no longer carries a false current claim; the sole remaining suite blocker is PX-GAP-0008",
        }
    ],
    "PX-GAP-0007": [
        {
            "kind": "coverage-measurement",
            "artifact": ".agentic_engineering_os_px/registers/px-gap-0007-coverage-receipt.json",
            "summary": (
                "Measured real boundary coverage instead of asserting it. Found "
                "extension/server/index.js (1406374 bytes, 33743 lines) classified authored "
                "despite being an esbuild bundle of extension/server/source.mjs produced by "
                "extension/scripts/build-mcp.js. Also found the bundle is stale against its own "
                "generator: node scripts/build-mcp.js --check exits 1."
            ),
            "supporting_findings": [
                "extension/package.json declares build:mcp and check:mcp but no Python runtime module invokes the staleness detector",
                "the architecture audit independently recorded 'Bundle identity lacks a retained complete producer-input receipt' (S474)",
                "census: generated is 61 files / 592138 bytes of 77 MB, so the misclassified 1.4 MB bundle is material relative to the generated class",
            ],
            "not_repaired_reason": (
                "Rebuilding rewrites a shipped, hashed, release-identity-bearing artifact bound "
                "by registry/source_freeze.json, registry/engine_identity.json and "
                "registry/test_group_index.json. That requires the repair freeze and a governed "
                "release-identity procedure, not an opportunistic build during diagnosis."
            ),
            "supports": "measured, not repaired; 0007 remains open",
        }
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