"""Register and reconcile the two-agent card/control review as evidence input."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import append_events, read_snapshot


SOURCE = Path("evidence/operational-gap-ledger/card-control-resolution-review-20260816.json")
SOURCE_SHA256 = "d5ed841939f8908bb71801a9d0948d20722cfe1b971bc9ebb1a6e837174570d0"
REPORT_ID = "card-control-resolution-review-20260816"
ACTOR = "codex-host:agent-report-reconciliation"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    raw = (root / SOURCE).read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise SystemExit("card/control review artifact hash mismatch")
    review = json.loads(raw)
    card_ids = sorted(
        set(review["exact_typed_controls"])
        | set(review["non_visible_path"])
        | set(review["aggregate_parent_ready"])
        | set(review["aggregate_split_pending"])
    )
    if len(card_ids) != review["review_basis"]["reviewed_unlinked_cards"]:
        raise SystemExit("reviewed report card count is inconsistent")
    finding_ids = [f"card-control-resolution:{gap_id}" for gap_id in card_ids]
    snapshot = read_snapshot(root)
    existing = snapshot["reports"].get(REPORT_ID)
    entries: list[dict[str, object]] = []
    if existing is None:
        entries.append({
            "event_type": "report_registered",
            "actor": ACTOR,
            "payload": {
                "report_id": REPORT_ID,
                "source": SOURCE.as_posix(),
                "source_sha256": SOURCE_SHA256,
                "finding_ids": finding_ids,
            },
        })
        reconciled: set[str] = set()
    else:
        if existing["source_sha256"] != SOURCE_SHA256 or existing["finding_ids"] != finding_ids:
            raise SystemExit("registered card/control review conflicts with the hash-bound source")
        reconciled = set(existing["reconciliations"])
    for gap_id, finding_id in zip(card_ids, finding_ids):
        if finding_id in reconciled:
            row = existing["reconciliations"][finding_id]
            if row["disposition"] != "card" or row["gap_ids"] != [gap_id]:
                raise SystemExit(f"existing report reconciliation conflicts: {finding_id}")
            continue
        if gap_id not in snapshot["cards"]:
            raise SystemExit(f"review finding references an unknown card: {gap_id}")
        entries.append({
            "event_type": "report_finding_reconciled",
            "actor": ACTOR,
            "payload": {
                "report_id": REPORT_ID,
                "finding_id": finding_id,
                "disposition": "card",
                "gap_ids": [gap_id],
                "evidence": [{
                    "reference": SOURCE.as_posix(),
                    "claim": "The independent card/control review classification is retained on this same stable card; it creates no completion claim.",
                }],
            },
        })
    if args.apply and entries:
        append_events(root, entries)
    print(json.dumps({
        "mode": "check" if args.check else "apply",
        "report_id": REPORT_ID,
        "finding_count": len(finding_ids),
        "planned_or_appended_events": len(entries),
        "unreconciled_after_apply": 0,
        "state_transitions": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
