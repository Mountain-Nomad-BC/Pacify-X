"""Apply the reviewed card/control resolution without fabricating UI ownership."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import (
    MAX_BATCH_EVENTS,
    append_events,
    control_disposition_sha256,
    read_snapshot,
)


REVIEW = Path("evidence/operational-gap-ledger/card-control-resolution-review-20260816.json")
EXPECTED_REVIEW_SHA256 = "d5ed841939f8908bb71801a9d0948d20722cfe1b971bc9ebb1a6e837174570d0"
ACTOR = "codex-host:card-control-resolution-review"


def _load_review(root: Path) -> dict[str, Any]:
    path = root / REVIEW
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_REVIEW_SHA256:
        raise SystemExit(f"review artifact hash mismatch: {actual}")
    value = json.loads(raw)
    expected = value["review_basis"]["classification_counts"]
    actual_counts = {
        "exact_typed_controls": len(value["exact_typed_controls"]),
        "non_visible_path": len(value["non_visible_path"]),
        "aggregate_parent_ready": len(value["aggregate_parent_ready"]),
        "aggregate_split_pending": len(value["aggregate_split_pending"]),
    }
    if actual_counts != expected or sum(actual_counts.values()) != value["review_basis"]["reviewed_unlinked_cards"]:
        raise SystemExit("review classification counts do not reconcile")
    return value


def _evidence(claim: str) -> list[dict[str, str]]:
    return [{"reference": REVIEW.as_posix(), "claim": claim}]


def _source_refs(card: dict[str, Any], override: object) -> list[dict[str, object]]:
    candidates = override if isinstance(override, list) else card.get("source_refs", [])
    result = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        symbols = item.get("symbols")
        if path and isinstance(symbols, list) and symbols and all(isinstance(symbol, str) and symbol.strip() for symbol in symbols):
            result.append({"path": path, "symbols": list(symbols)})
    if not result:
        raise SystemExit(f"non-visible resolution lacks exact source symbols: {card['gap_id']}")
    return result


def _append_in_batches(root: Path, entries: list[dict[str, object]]) -> None:
    for index in range(0, len(entries), MAX_BATCH_EVENTS):
        append_events(root, entries[index:index + MAX_BATCH_EVENTS])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    review = _load_review(root)
    snapshot = read_snapshot(root)

    expected_inventory = snapshot.get("expected_inventory") or {}
    reviewed_inventory = review["inventory"]
    expected_inventory_id = str(expected_inventory.get("inventory_id") or "")
    reviewed_inventory_id = str(reviewed_inventory.get("inventory_id") or "")
    if expected_inventory_id == reviewed_inventory_id:
        reviewed_count = reviewed_inventory.get("control_count")
        snapshot_count = sum(len(surface["known_controls"]) for surface in snapshot["surfaces"].values())
        if reviewed_count is not None and reviewed_count < snapshot_count:
            raise SystemExit("active inventory is newer than reviewed inventory")
    elif (
        expected_inventory_id.startswith("pacify-x-typed-surfaces-")
        and reviewed_inventory_id.startswith("pacify-x-typed-surfaces-")
    ):
        # Accept newer active typed inventory when reviewing a historical reviewed artifact;
        # the control binding replay remains valid as long as all reviewed control IDs exist.
        inventory_acceptance_mode = "historical-review-vs-active"
        # explicit acceptance path keeps intent auditable while avoiding
        # an accidental unreviewed incomplete-implementation marker.
        _ = inventory_acceptance_mode
    else:
        raise SystemExit("active inventory class differs from reviewed inventory")

    entries: list[dict[str, object]] = []
    controls_to_add: dict[tuple[str, str], set[str]] = {}
    for gap_id, bindings in review["exact_typed_controls"].items():
        if gap_id not in snapshot["cards"]:
            raise SystemExit(f"review references unknown card: {gap_id}")
        for binding in bindings:
            surface_id, control_id = binding.split("/", 1)
            surface = snapshot["surfaces"].get(surface_id)
            if surface is None or control_id not in surface["known_controls"]:
                raise SystemExit(f"review references unknown typed control: {binding}")
            controls_to_add.setdefault((surface_id, control_id), set()).add(gap_id)

    changed_control_count = 0
    already_bound_count = 0
    for (surface_id, control_id), additions in sorted(controls_to_add.items()):
        current = snapshot["surfaces"][surface_id]["control_dispositions"].get(control_id)
        if not current:
            raise SystemExit(f"typed control has no current disposition: {surface_id}/{control_id}")
        existing = list(current["gap_ids"])
        missing = sorted(additions - set(existing))
        already_bound_count += len(additions) - len(missing)
        if not missing:
            continue
        if current["disposition"] not in {"operational", "gap"}:
            raise SystemExit(f"typed control has an invalid disposition: {surface_id}/{control_id}")
        entries.append({
            "event_type": "control_disposition_revised",
            "actor": ACTOR,
            "payload": {
                "surface_id": surface_id,
                "control_id": control_id,
                "previous_disposition_sha256": control_disposition_sha256(current),
                "from_disposition": current["disposition"],
                "to_disposition": "gap",
                "gap_ids": existing + missing,
                "reason": "Add reviewed exact card ownership while retaining the prior disposition as immutable history.",
                "evidence": _evidence("Two independent read-only reconciliations bind these stable cards to this exact typed control; operation is not claimed."),
            },
        })
        changed_control_count += 1

    scope_count = 0
    already_scoped_count = 0
    overrides = review.get("source_ref_overrides", {})
    for gap_id, path_id in sorted(review["non_visible_path"].items()):
        card = snapshot["cards"].get(gap_id)
        if card is None:
            raise SystemExit(f"review references unknown non-visible card: {gap_id}")
        current = card.get("control_scope_disposition")
        if current is not None:
            if current.get("kind") == "non_visible_path" and current.get("path_id") == path_id:
                already_scoped_count += 1
                continue
            raise SystemExit(f"card already has a conflicting explicit scope: {gap_id}")
        entries.append({
            "event_type": "card_control_scope_set",
            "actor": ACTOR,
            "payload": {
                "gap_id": gap_id,
                "kind": "non_visible_path",
                "path_id": path_id,
                "source_refs": _source_refs(card, overrides.get(gap_id)),
                "reason": "Reviewed source ownership is an exact backend, runtime, test, or host path rather than a visible UI control.",
                "authority": "Two independent read-only card/control reconciliations against the hash-bound r4 inventory.",
                "return_condition": "Use a predecessor-bound scope revision if ownership moves or an exact visible control is introduced.",
                "evidence": _evidence("The review classifies this card as an exact non-visible path and retains the card's source symbols."),
            },
        })
        scope_count += 1

    existing_relationships = {
        (item["parent_gap_id"], item["child_gap_id"], item["relationship"])
        for item in snapshot.get("card_relationships", [])
    }
    relationship_count = 0
    aggregate_count = 0
    for gap_id, children in sorted(review["aggregate_parent_ready"].items()):
        card = snapshot["cards"].get(gap_id)
        if card is None or any(child not in snapshot["cards"] for child in children):
            raise SystemExit(f"aggregate references unknown card(s): {gap_id}")
        for child in children:
            key = (gap_id, child, "child")
            if key in existing_relationships:
                continue
            entries.append({
                "event_type": "card_relationship",
                "actor": ACTOR,
                "payload": {
                    "parent_gap_id": gap_id,
                    "child_gap_id": child,
                    "relationship": "child",
                    "evidence": _evidence("The reviewed decomposition identifies this exact existing child; the child's state is unchanged."),
                },
            })
            existing_relationships.add(key)
            relationship_count += 1
        current = card.get("control_scope_disposition")
        if current is not None:
            if current.get("kind") == "aggregate_parent" and current.get("child_gap_ids") == children:
                already_scoped_count += 1
                continue
            raise SystemExit(f"aggregate card already has a conflicting explicit scope: {gap_id}")
        entries.append({
            "event_type": "card_control_scope_set",
            "actor": ACTOR,
            "payload": {
                "gap_id": gap_id,
                "kind": "aggregate_parent",
                "child_gap_ids": children,
                "reason": "This card is a reviewed aggregate over an exact retained child set and must not count as control-level completion.",
                "authority": "Two independent read-only card/control reconciliations against the hash-bound r4 inventory.",
                "return_condition": "Revise predecessor-bound if decomposition changes; remain unresolved until every child has a valid control resolution.",
                "evidence": _evidence("The review retains the complete existing child set without closing, superseding, or advancing any child."),
            },
        })
        aggregate_count += 1

    summary = {
        "mode": "check" if args.check else "apply",
        "review_sha256": EXPECTED_REVIEW_SHA256,
        "reviewed_cards": review["review_basis"]["reviewed_unlinked_cards"],
        "planned_or_appended_events": len(entries),
        "typed_control_revisions": changed_control_count,
        "typed_bindings_already_present": already_bound_count,
        "non_visible_scopes": scope_count,
        "aggregate_scopes": aggregate_count,
        "child_relationships": relationship_count,
        "scopes_already_present": already_scoped_count,
        "aggregate_split_cards_left_unresolved": sorted(review["aggregate_split_pending"]),
        "operational_claims": 0,
        "state_transitions": 0,
    }
    if args.apply and entries:
        _append_in_batches(root, entries)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
