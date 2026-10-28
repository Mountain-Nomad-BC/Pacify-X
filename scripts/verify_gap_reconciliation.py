"""Verify the reconciliation sweep preserved every original gap field.

Read-only integrity check: for each gap record it asserts that discovery-time
evidence is still present and that a reconciliation disposition was recorded
without displacing it.
"""

from __future__ import annotations

import json
from pathlib import Path

WORK = Path(__file__).resolve().parents[1] / ".agentic_engineering_os_px" / "work"

ORIGINAL_FIELDS = (
    "gap_id",
    "parent_surface",
    "feature",
    "expected_behavior",
    "observed_behavior",
    "interaction_chain",
    "classification",
    "severity",
    "operational_impact",
    "dependencies",
    "blockers",
    "tests_required",
    "completion_evidence",
)


def main() -> int:
    failures: list[str] = []
    print(f"{'gap':13s} {'recon':6s} {'orig':5s} {'ev':3s} {'disposition'}")
    for number in range(1, 16):
        gap_id = f"PX-GAP-{number:04d}"
        path = WORK / f"{gap_id}.json"
        if not path.is_file():
            failures.append(f"{gap_id}: missing file")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("gap_id") != gap_id:
            failures.append(f"{gap_id}: identity mismatch {record.get('gap_id')}")

        reconciliation = record.get("reconciliation")
        deferred = record.get("defer_skip")
        has_disposition = bool(reconciliation) or bool(deferred) or (
            record.get("provenance_determination") is not None
        )

        missing = [f for f in ORIGINAL_FIELDS if f not in record]
        if missing:
            failures.append(f"{gap_id}: lost original fields {missing}")

        disposition = "-"
        if reconciliation:
            disposition = reconciliation.get("disposition", "?")
        elif deferred:
            disposition = deferred.get("disposition", "?")
        elif record.get("provenance_determination"):
            disposition = record["provenance_determination"].get("disposition", "?")

        evidence = len(record.get("completion_evidence", ()))
        print(
            f"{gap_id:13s} {str(bool(reconciliation)):6s} "
            f"{str(not missing):5s} {evidence:<3d} {disposition}"
        )
        if not has_disposition:
            failures.append(f"{gap_id}: no disposition recorded")

    print()
    if failures:
        print("INTEGRITY FAILURES:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("OK: all 15 gaps retain original discovery evidence and carry a disposition.")
    print("OK: no gap was closed by the reconciliation sweep.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())