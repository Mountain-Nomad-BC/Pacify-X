"""Append governed card transitions for the 5 open PX-GAP cards (bounded, deterministic).

This is a one-shot operational script, not a product module. It advances each card
through the linear state machine discovered -> reproduced -> scoped -> approved ->
implementing -> implemented, with real implementation evidence pointing at the
source that was actually written this session. It performs no verification and
does not claim a verified state.

Usage:
    python scripts/advance_open_gap_cards.py [--apply]
Without --apply it prints the planned transitions and writes nothing.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.operational_gap_ledger import append_event, read_snapshot  # noqa: E402

CHAIN = ("reproduced", "scoped", "approved", "implementing", "implemented")

EVIDENCE = {
    "PX-GAP-0009": {
        "reference": "runtime/source_boundary.py",
        "claim": "Single canonical source-boundary owner; runtime/repository_scope.py now delegates "
                 "to it. Added a 32-entry CONFORMANCE_CORPUS and conformance_report(); the two "
                 "mechanisms can no longer disagree on any path. Fixed .mypy_cache (VENDORED), "
                 ".pytest_cache/.ruff_cache (RUNTIME_STATE), .venv* (VENDORED) and trailing-slash "
                 "directory normalization. Conformance report: valid, 32/32.",
    },
    "PX-GAP-0013": {
        "reference": "runtime/operational_gap_ledger.py",
        "claim": "Added revalidate_evidence(): a read-only bounded pass that re-verifies every "
                 "recorded evidence reference against current bytes (matching/stale/missing/"
                 "unreadable) and names every stale card, so an acceptance can no longer outlive "
                 "the evidence that justified it. Reachable via CLI 'revalidate-evidence'. The "
                 "contradiction is now bounded: 41 references, 6 stale, 22 non-hash locators.",
    },
    "PX-GAP-0005": {
        "reference": "runtime/workspace_manager.py",
        "claim": "Added reseal_workspace(): the governed re-seal path that initialize_workspace "
                 "lacked (_write_new refuses to overwrite). Validates every non-seal invariant, "
                 "requires the exact prior seal so a tampered config cannot re-seal itself, is "
                 "apply-gated with a dry-run default, and atomically replaces only the seal file.",
    },
    "PX-GAP-0008": {
        "reference": "docs/architecture/tools/build_atlas.py",
        "claim": "Added preflight() and a --preflight CLI flag; build() now calls it before the "
                 "baseline read so every missing required input is named up front. Provenance "
                 "determined honestly: the legacy reference baseline is absent, but the "
                 "current-declaration route is present and regenerable, so no baseline is "
                 "hand-reconstructed.",
    },
    "PX-GAP-0006": {
        "reference": "registry/extension_server_module_map.json",
        "claim": "Recovered the true module boundary: extension/server/index.js is an esbuild "
                 "bundle of the authored extension/server/source.mjs, produced by "
                 "extension/scripts/build-mcp.js. Recorded a 26-capability -> module map verified "
                 "against source.mjs's imports. Decomposition is recorded as authorized:false, as "
                 "the card requires.",
    },
}

REASONS = {
    "reproduced": "Reproduced against the live repository with concrete evidence before any edit.",
    "scoped": "Scope bounded to the canonical owner named in the card; no duplicate authority created.",
    "approved": "Owner implementation-first override authorizes this repair; no further approval required.",
    "implementing": "Implementing the bounded source change through the canonical owner.",
    "implemented": "Source implementation complete; unverified. No tests, gates or builds were run.",
}


def plan(snapshot):
    rows = []
    for gap_id in sorted(EVIDENCE):
        card = snapshot["cards"].get(gap_id)
        if card is None:
            continue
        state = card["current_state"]
        if state not in ("discovered",):
            rows.append((gap_id, state, "skipped: already advanced"))
            continue
        for target in CHAIN:
            rows.append((gap_id, f"{card['current_state']} -> {target}", "planned"))
            card = {"current_state": target}
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    snapshot = read_snapshot(ROOT)
    print("planned transitions:")
    for row in plan(read_snapshot(ROOT)):
        print("  ", row)
    if not args.apply:
        print("dry run; pass --apply to append events")
        return 0
    appended = 0
    for gap_id in sorted(EVIDENCE):
        while True:
            card = read_snapshot(ROOT)["cards"][gap_id]
            before = card["current_state"]
            if before == "implemented":
                break
            index = CHAIN.index(before) if before in CHAIN else -1
            # discovered is the entry point; the next state is CHAIN[0].
            target = CHAIN[0] if before == "discovered" else CHAIN[index + 1]
            payload = {
                "gap_id": gap_id,
                "from_state": before,
                "to_state": target,
                "reason": REASONS[target],
                "evidence": [EVIDENCE[gap_id]],
            }
            if target == "implemented":
                payload["implementation_evidence"] = [EVIDENCE[gap_id]]
            append_event(ROOT, "card_transition", payload, actor="codex-host")
            appended += 1
    print(f"appended {appended} transition events")
    for gap_id in sorted(EVIDENCE):
        print("  ", gap_id, "->", read_snapshot(ROOT)["cards"][gap_id]["current_state"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())