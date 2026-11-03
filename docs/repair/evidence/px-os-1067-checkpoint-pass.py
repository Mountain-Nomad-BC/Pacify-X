"""Append the P4-completion / P5 / tooling checkpoints for PX-OS-1067.

Append-only. No product source, registry, gate, or repository-and-release state changes.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GAP = "PX-OS-1067"
ACTOR = "codex-host"
SESSION = "px-os-1067-p4-script-producers-r-20261103"
ADMISSION = "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036527"


def digest(relative: str) -> tuple[str, int]:
    path = ROOT / relative
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_size


def evidence(*references: str) -> list[dict[str, object]]:
    items = []
    for reference in references:
        checksum, size = digest(reference)
        items.append(
            {
                "reference": reference,
                "artifact_sha256": checksum,
                "artifact_size": size,
                "claim": "Evidence produced by the PX-OS-1067 Priority 4-5 continuation pass.",
            }
        )
    return items


from runtime.operational_gap_ledger import append_event, read_snapshot  # noqa: E402

snapshot = read_snapshot(ROOT)
prior_admission = next(e for e in snapshot["work_admissions"] if e["event_id"] == ADMISSION)
now = datetime.now(timezone.utc)

checkpoints = [
    (
        "Priority 4 completion: 135/135 scanner-emitted scripts direct-effect references traced.",
        [
            "docs/repair/evidence/px-os-1067-script-producer-audit.json",
            "docs/repair/evidence/px-os-1067-census-2026-11-03.json",
        ],
        "Continue to Priority 5 (.px/skills) and Priority 6 tooling hardening.",
    ),
    (
        "Scanner repair (authorized under this admission): two shutil.copyfile writes added to the "
        "census; documented as a proven false negative. Census 1,697 -> 1,700 effect records; "
        "377/373/216/157 and 310 gate findings unchanged; gate still invalid.",
        [
            "docs/repair/evidence/px-os-1067-census-2026-11-03.json",
            "docs/repair/evidence/px-os-1067-run-census.py",
        ],
        "Reuse the retained launcher for every later census; never write census output into the scanned tree.",
    ),
    (
        "Tooling hardening: canonical census made linear. default_classification rescanned the whole "
        "repository per delegated producer; the scan is now shared. Census 307s+ (unmeasured completion) "
        "-> 57s with identical figures. Evidence tooling under docs/repair/evidence/ excluded from the "
        "producer census so a launcher cannot change its own denominator.",
        [
            "docs/repair/evidence/px-os-1067-census-2026-11-03.json",
            "docs/repair/evidence/px-os-1067-run-census.py",
        ],
        "Run the shared-scan path in CI before any release certification attempt.",
    ),
]

previous = snapshot["work_checkpoints"][-1]
card = snapshot["cards"][GAP]
for learned, references, next_action in checkpoints:
    # A checkpoint may not restate a different next_action than the active card; the
    # ledger owns that field. The continuation step is carried by `learned` instead.
    event = append_event(
        ROOT,
        "work_checkpoint",
        {
            "active_gap_id": GAP,
            "previous_checkpoint_event_id": previous["event_id"],
            "learned": f"{learned} Continuation: {next_action}",
            "next_action": card.get("next_action"),
            "newly_discovered_gap_ids": [],
            "unresolved_branch_gap_ids": sorted(
                gid
                for gid, value in (snapshot["cards"] or {}).items()
                if gid != GAP and value.get("current_state") not in {"closed", "superseded"}
            ),
            "evidence": evidence(*references),
        },
        actor=ACTOR,
    )
    previous = event
    print(event["event_id"], flush=True)

print(json.dumps({"expires": prior_admission["expires_utc"], "now": now.isoformat()}))
