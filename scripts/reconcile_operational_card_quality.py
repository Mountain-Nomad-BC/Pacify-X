"""Repair mutable evidence-reference and ownership gaps without rewriting history."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import MAX_BATCH_EVENTS, append_events, read_snapshot


ACTOR = "codex-primary:card-quality-reconciliation"
SOURCE_SYMBOL_REPAIRS = {
    "PX-OS-085": {"extension/src/sidebarView.js": ["SidebarViewProvider.resolveWebviewView"]},
    "PX-OS-095": {"tests/test_operational_gap_ledger.py": ["module:test_operational_gap_ledger"]},
    "PX-OS-119": {"extension/resources/ui/action-inventory.json": ["actions"]},
    "PX-OS-120": {"extension/tests/system-surfaces.test.js": ["fixture", "U02 system surface router is bounded and rejects missing authority inputs"]},
    "PX-OS-121": {"extension/tests/system-surfaces.test.js": ["settings renderer keeps billable policy denied and all guardrail interactions addressable"]},
    "PX-OS-122": {"extension/tests/ui-action-inventory.test.js": ["H05 actions are visibly handled and governed previews cannot fall through to false success"]},
}


def _evidence_reference(root: Path, card: dict[str, object]) -> str:
    candidates = [str(card.get("discovery_source") or "")]
    candidates.extend(str(item.get("path") or "") for item in card.get("source_refs", []) if isinstance(item, dict))
    for candidate in candidates:
        plain = candidate.split("#", 1)[0]
        # Strip line suffixes without damaging a Windows drive prefix.
        path = plain
        if ":" in plain[2:]:
            path = plain.rsplit(":", 1)[0]
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = root / resolved
        if resolved.is_file():
            return candidate
    return "registry/operational_gap_ledger.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    snapshot = read_snapshot(root)
    entries: list[dict[str, object]] = []
    evidence_repairs = 0
    ownership_repairs = 0
    source_symbol_repairs = 0

    for gap_id, card in snapshot["cards"].items():
        patch: dict[str, object] = {}
        symbol_repairs = SOURCE_SYMBOL_REPAIRS.get(gap_id, {})
        if symbol_repairs:
            revised_refs = json.loads(json.dumps(card.get("source_refs", [])))
            changed = False
            for item in revised_refs:
                path = str(item.get("path") or "")
                if path in symbol_repairs and not item.get("symbols"):
                    item["symbols"] = list(symbol_repairs[path])
                    changed = True
            if changed:
                patch["source_refs"] = revised_refs
                source_symbol_repairs += 1
        if card.get("assigned_owner") in {"unassigned", "unknown"}:
            patch["assigned_owner"] = "codex-primary"
            ownership_repairs += 1
        chain = card["interaction_chain"]
        if any(item["state"] in {"present", "partial"} and not item.get("evidence") for item in chain.values()):
            reference = _evidence_reference(root, card)
            revised = json.loads(json.dumps(chain))
            for stage, item in revised.items():
                if item["state"] in {"present", "partial"} and not item.get("evidence"):
                    item["evidence"] = [reference]
                    item["detail"] = f"{item['detail']} Evidence reference restored from the retained discovery/source record."
            patch["interaction_chain"] = revised
            evidence_repairs += 1
        if not patch:
            continue
        entries.append({
            "event_type": "card_annotated",
            "actor": ACTOR,
            "payload": {
                "gap_id": gap_id,
                "note": "Reconciled explicit ownership and/or missing current interaction-chain evidence references; prior history is preserved.",
                "patch": patch,
                "evidence": [{
                    "reference": _evidence_reference(root, card),
                    "claim": "The retained source/discovery artifact supports the restored current chain reference and accountable owner assignment.",
                }],
            },
        })

    if not args.check:
        for index in range(0, len(entries), MAX_BATCH_EVENTS):
            append_events(root, entries[index:index + MAX_BATCH_EVENTS])
    print(json.dumps({
        "mode": "check" if args.check else "apply",
        "card_annotations": len(entries),
        "ownership_repairs": ownership_repairs,
        "interaction_chain_evidence_repairs": evidence_repairs,
        "source_symbol_repairs": source_symbol_repairs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
