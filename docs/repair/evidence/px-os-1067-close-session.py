"""Close the PX-OS-1067 Priority 4-6 continuation session with its final checkpoint.

Append-only. Does not approve any producer, owner, fingerprint, or release state.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from runtime.operational_gap_ledger import append_event, read_snapshot

ROOT = Path(__file__).resolve().parents[3]
GAP = "PX-OS-1067"
ACTOR = "codex-host"
ADMISSION = "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036527"


def evidence(relative: str, claim: str) -> dict[str, object]:
    path = ROOT / relative
    return {
        "reference": relative,
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "artifact_size": path.stat().st_size,
        "claim": claim,
    }


snapshot = read_snapshot(ROOT)
admission = next(e for e in snapshot["work_admissions"] if e["event_id"] == ADMISSION)

closure = append_event(
    ROOT,
    "work_session_closed",
    {
        "gap_id": GAP,
        "session_id": admission["session_id"],
        "admission_event_id": admission["event_id"],
        "outcome": "completed",
        "reason": (
            "Priority 4 completed for tracing (135/135 direct references, 78 dispositions "
            "unresolved). Priority 6 tooling hardening completed: census made linear (307s+ -> "
            "57s) and one proven scanner false negative repaired with tests. Priority 5 "
            ".px/skills evidence complete (11/11, none registered). B7 still 68 producers / 32 "
            "resources / 0 approved owners. No producer, owner, fingerprint, or release state "
            "was approved; the canonical gate remains invalid with 310 findings."
        ),
        "evidence": [
            evidence(
                "docs/repair/REV1XX_PX_OS_1067_MASTER_EXECUTION_LOG.md",
                "Master execution log records the P4-6 continuation results.",
            ),
            evidence(
                "docs/repair/evidence/px-os-1067-census-2026-11-03.json",
                "Canonical census: 1700 / 377 / 373 / 216 / 157 / 310, gate invalid.",
            ),
            evidence(
                "docs/repair/evidence/px-os-1067-px-skills-owner-audit.json",
                "Eleven .px/skills producers accounted for; none registered.",
            ),
        ],
    },
    actor=ACTOR,
)

prior = snapshot["work_checkpoints"][-1]
card = snapshot["cards"][GAP]
checkpoint = append_event(
    ROOT,
    "work_checkpoint",
    {
        "active_gap_id": GAP,
        "previous_checkpoint_event_id": prior["event_id"],
        "learned": (
            "The 103 inert fingerprints remain BLOCKED_AUTHORITY (no original source for 80 "
            "paths, no reviewer approval). All 78 scripts and all 11 .px/skills producers remain "
            "unresolved by design. Two inherited test modules fail on the inherited worktree and "
            "were not modified."
        ),
        "next_action": card.get("next_action"),
        "newly_discovered_gap_ids": [],
        "unresolved_branch_gap_ids": sorted(
            gid
            for gid, value in (snapshot["cards"] or {}).items()
            if gid != GAP and value.get("current_state") not in {"closed", "superseded"}
        ),
        "evidence": [
            evidence(
                "docs/repair/evidence/px-os-1067-inert-fingerprint-dispositions.json",
                "All 103 inert fingerprints individually accounted for; none re-reviewed.",
            )
        ],
    },
    actor=ACTOR,
)
print(closure["event_id"])
print(checkpoint["event_id"])
