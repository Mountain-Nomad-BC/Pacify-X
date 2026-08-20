"""Apply reviewed source-trace gap candidates as one ledger batch."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (
    MAX_BATCH_EVENTS,
    append_events,
    control_disposition_sha256,
    read_snapshot,
)


PROPOSAL = Path("evidence/operational-gap-ledger/typed-control-card-link-proposal-20260816.json")
EXPECTED_SHA256 = "a73b11f25162fc32f450acca410c7d44432fe3942ae6598886812756b78feb11"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    source = root / PROPOSAL
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != EXPECTED_SHA256:
        raise SystemExit("typed control/card proposal hash does not match its reviewed bytes")
    proposal = json.loads(raw)
    snapshot = read_snapshot(root)
    to_add: list[dict[str, object]] = []
    revised: list[dict[str, object]] = []
    already_matching = 0
    skipped_unknown = 0
    for surface in proposal["surfaces"]:
        surface_id = surface["surface_id"]
        active = snapshot["surfaces"].get(surface_id)
        if active is None:
            raise SystemExit(f"proposal references unknown surface: {surface_id}")
        known_controls = set(active.get("control_dispositions", {})) | set(active.get("control_records", {}))
        for assignment in surface["assignments"]:
            if assignment["disposition"] != "existing_gap_candidate":
                continue
            control_id = assignment["control_id"]
            gap_ids = list(assignment["existing_gap_candidate_card_ids"])
            desired_gap_ids = list(dict.fromkeys(gap_ids))
            if control_id not in known_controls:
                # The candidate references a retired control. It can no longer be
                # bound in the active inventory, so skip with an explicit count.
                skipped_unknown += 1
                continue
            existing = active["control_dispositions"].get(control_id)
            if not existing:
                to_add.append(
                    {
                        "event_type": "control_disposition",
                        "actor": "codex-primary",
                        "payload": {
                            "surface_id": surface_id,
                            "control_id": control_id,
                            "disposition": "gap",
                            "gap_ids": desired_gap_ids,
                            "evidence": [
                                {
                                    "reference": PROPOSAL.as_posix(),
                                    "claim": "Reviewed source trace associates this exact typed control with existing stable gap cards; installed-host operation is not claimed.",
                                }
                            ],
                        },
                    }
                )
                continue
            if existing["disposition"] not in {"operational", "gap"}:
                raise SystemExit(f"existing disposition conflicts with proposal: {surface_id}/{control_id}")

            current = list(existing.get("gap_ids") or [])
            existing_set = set(current)
            desired_set = set(desired_gap_ids)
            if existing["disposition"] == "gap":
                missing = sorted(desired_set - existing_set)
                if not missing:
                    already_matching += 1
                    continue
                revised.append({
                    "event_type": "control_disposition_revised",
                    "actor": "codex-primary",
                    "payload": {
                        "surface_id": surface_id,
                        "control_id": control_id,
                        "previous_disposition_sha256": control_disposition_sha256(existing),
                        "from_disposition": "gap",
                        "to_disposition": "gap",
                        "gap_ids": sorted(existing_set | desired_set),
                        "reason": "Add reviewed exact gap candidates while preserving prior gap history.",
                        "evidence": [
                            {
                                "reference": PROPOSAL.as_posix(),
                                "claim": "The reviewed source trace confirms these exact cards; missing reviewed cards are appended.",
                            }
                        ],
                    },
                })
                continue

            if current:
                raise SystemExit(f"existing operational disposition conflicts with proposal: {surface_id}/{control_id}")
            revised.append(
                {
                    "event_type": "control_disposition_revised",
                    "actor": "codex-primary",
                    "payload": {
                        "surface_id": surface_id,
                        "control_id": control_id,
                        "previous_disposition_sha256": control_disposition_sha256(existing),
                        "from_disposition": "operational",
                        "to_disposition": "gap",
                        "gap_ids": desired_gap_ids,
                        "reason": "Move reviewed exact operational control to an explicit gap disposition with deterministic reviewed candidates.",
                        "evidence": [
                            {
                                "reference": PROPOSAL.as_posix(),
                                "claim": "Operational control is already reviewed against exact gap cards and must be represented as gap disposition.",
                            }
                        ],
                    },
                }
            )

    if args.check:
        expected = proposal["counts"]["dispositions"]["existing_gap_candidate"]
        candidate_count = len(to_add) + len(revised) + already_matching + skipped_unknown
        if candidate_count != expected:
            raise SystemExit("typed gap candidate count is inconsistent")
        print(
            json.dumps(
                {
                    "candidate_count": candidate_count,
                    "would_append": len(to_add) + len(revised),
                    "new_disposition_events": len(to_add),
                    "revised_disposition_events": len(revised),
                    "skipped_unknown_controls": skipped_unknown,
                    "already_matching": already_matching,
                    "operational_claims": 0,
                },
                indent=2,
            )
        )
        return 0

    if to_add or revised:
        events = to_add + revised
        for index in range(0, len(events), MAX_BATCH_EVENTS):
            append_events(root, events[index:index + MAX_BATCH_EVENTS])
    print(
        json.dumps(
            {
                "candidate_count": len(to_add) + len(revised) + already_matching + skipped_unknown,
                "appended": len(to_add) + len(revised),
                "new_disposition_events": len(to_add),
                "revised_disposition_events": len(revised),
                "skipped_unknown_controls": skipped_unknown,
                "already_matching": already_matching,
                "operational_claims": 0,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
