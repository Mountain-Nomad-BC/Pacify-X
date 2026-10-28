"""Record PX-GAP-0008 as provenance-unresolved with the evidence behind that call.

Read-only with respect to the repository. The baseline must not be hand-rebuilt:
the parity test compares it against canonical data, so reconstructing it from
that same data would make the assertion circular rather than true.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

BASELINE = "docs/architecture/reference/graph_baseline_architecture.json"

DISPOSITION = {
    "measured_at": "2026-10-02",
    "disposition": "open-provenance-unresolved",
    "blocking_reason": (
        "The authoritative source of graph_baseline_architecture.json cannot be "
        "established from any available material, so the file must not be "
        "regenerated or reconstructed."
    ),
    "provenance_investigation": [
        {
            "question": "Is the baseline produced by the declared atlas generator?",
            "answer": "No. docs/architecture/tools/build_atlas.py CONSUMES the baseline at line 495 via read_text, and hashes its bytes at line 805-806 as baseline_graph_sha256. It is an input, never an output.",
            "evidence": "docs/architecture/tools/build_atlas.py:495, 498, 805-806, 1036",
        },
        {
            "question": "Does any runtime module produce it?",
            "answer": "No producer exists. The only reference is a consumer at tests/test_architecture_atlas.py:13-15, which reads it at module import time and therefore raises FileNotFoundError during collection.",
            "evidence": "tests/test_architecture_atlas.py:13-15",
        },
        {
            "question": "Is a copy retained anywhere in the reference corpus?",
            "answer": "No. A recursive search of C:\\Users\\Ben\\Downloads for graph_baseline_architecture* returned zero results.",
        },
        {
            "question": "Could it be regenerated from canonical_systems.json?",
            "answer": "Technically yes, and that is precisely why it must not be done. The test asserts BASELINE['nodes'] ids == canonical_systems ids. Rebuilding the baseline from canonical_systems would make the parity assertion circular: it would compare a value against itself and would pass by construction while proving nothing about historical parity.",
            "evidence": "tests/test_architecture_atlas.py:39-42; docs/architecture/GRAPH_36_DISPOSITION.md records 1077 semantic systems and 1626 relationships preserving original IDs, which is exactly the historical snapshot the baseline is meant to independently corroborate.",
        },
        {
            "question": "Is the underlying content still present in another form?",
            "answer": "The CURRENT canonical graph data is present: docs/architecture/data/canonical_systems.json holds 1077 systems (first ids: host, ui, bridge), with edges.jsonl, canonical_relationships.json, metrics.json and node_shards_manifest.json alongside it. What is missing is only the independent HISTORICAL baseline against which that current data is checked.",
        },
    ],
    "what_is_missing_vs_what_exists": {
        "exists": [
            "docs/architecture/data/canonical_systems.json (1077 systems)",
            "docs/architecture/data/canonical_relationships.json",
            "docs/architecture/data/edges.jsonl",
            "docs/architecture/data/metrics.json",
            "docs/architecture/data/node_shards_manifest.json",
            "docs/architecture/tools/build_atlas.py (declared generator and baseline consumer)",
            "docs/architecture/GRAPH_36_DISPOSITION.md (historical denominator record: 16101 nodes, 7478 relationships, 15024 accepted source files, 1834 historical findings)",
        ],
        "missing": [BASELINE, "docs/architecture/reference/graph_baseline_evidence-map.json (read by build_atlas.py:498)"],
    },
    "consequence": (
        "tests/test_architecture_atlas.py cannot be collected, which blocks the governed "
        "full suite. This is the sole confirmed blocker remaining against a complete suite "
        "run; the other bundled claim in PX-GAP-0010 is stale and has been closed."
    ),
    "honest_state": (
        "The atlas data plane is present and its current denominators are documented. Only "
        "the independent historical parity reference is absent. Any substitute for the "
        "baseline would weaken the very guarantee the test exists to provide."
    ),
    "resolution_requires": [
        "Recover the original graph_baseline_architecture.json from an authoritative prior source: an owner-held archive, a prior release export, or the pack that produced the historical 36-graph delivery.",
        "Recover graph_baseline_evidence-map.json alongside it, since build_atlas.py:498 reads it from the same reference directory.",
        "If neither can be recovered, the owner must decide whether the parity guarantee is retired, and if so that decision must be recorded as an explicit scope change rather than implemented by substituting regenerated data."
    ],
    "explicitly_not_done": [
        "The baseline was NOT hand-reconstructed.",
        "The baseline was NOT synthesized from canonical_systems.json.",
        "No placeholder, stub or empty JSON object was created.",
        "tests/test_architecture_atlas.py was NOT modified to skip, xfail or bypass the missing file.",
        "docs/architecture/data was NOT regenerated to make the assertion pass.",
    ],
    "next_action": (
        "Hold open pending recovery of the authoritative historical baseline from an owner-held "
        "prior source. Do not close by substitution."
    ),
}


def main() -> int:
    path = WORK / "PX-GAP-0008.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["provenance_determination"] = DISPOSITION
    record["reconciliation"] = {
        "measured_at": "2026-10-02",
        "disposition": "confirmed-provenance-unresolved",
        "measurement": (
            "python -m pytest tests/test_architecture_atlas.py --collect-only -q => exit 2, "
            "FileNotFoundError on docs/architecture/reference/graph_baseline_architecture.json, "
            "'Interrupted: 1 error during collection, no tests collected'. Reproduced twice."
        ),
        "provenance_search": "Recursive search of C:\\Users\\Ben\\Downloads for graph_baseline_architecture* returned zero results.",
        "new_finding": (
            "build_atlas.py consumes the baseline rather than producing it, so it is a "
            "historical parity input with no generator. Reconstruction from canonical data "
            "would make the parity test circular."
        ),
    }
    path.write_text(
        json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"provenance determination recorded in {path.name}")
    print(f"  disposition: {DISPOSITION['disposition']}")
    print(f"  original observed_behavior preserved: {len(record['observed_behavior'])} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())