"""Create permanent child cards for reviewed historical aggregates."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.operational_gap_ledger import MAX_BATCH_EVENTS, append_events, blank_interaction_chain, read_snapshot
from runtime.operational_gap_ledger import card_control_scope_sha256


PLAN = Path("evidence/operational-gap-ledger/aggregate-card-split-plan-20260816.json")
EXPECTED_PLAN_SHA256 = "db67148ff6b7d8f28a932ded02ad1503330055faa7ffe5761e875a0579ca403f"
ACTOR = "codex-host:aggregate-card-split-review"
DISCOVERED_AT = "2026-08-16T19:28:00Z"


def _gap_id(number: int) -> str:
    return f"PX-OS-{number:03d}"


def _sort_key(gap_id: str) -> int:
    return int(gap_id.rsplit("-", 1)[1])


def _load_plan(root: Path) -> dict[str, Any]:
    raw = (root / PLAN).read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_PLAN_SHA256:
        raise SystemExit(f"aggregate split plan hash mismatch: {actual}")
    plan = json.loads(raw)
    allocations = [
        gap_id
        for parent in plan["parents"].values()
        for gap_id in parent["new_children"].values()
    ]
    basis = plan["allocation_basis"]
    if (
        len(allocations) != basis["allocated_child_count"]
        or len(set(allocations)) != len(allocations)
        or min(allocations, key=_sort_key) != basis["first_allocated_gap_id"]
        or max(allocations, key=_sort_key) != basis["last_allocated_gap_id"]
    ):
        raise SystemExit("aggregate split allocation is inconsistent")
    return plan


def _evidence(claim: str) -> list[dict[str, str]]:
    return [{"reference": PLAN.as_posix(), "claim": claim}]


def _expanded_existing_ids(spec: dict[str, Any]) -> set[str]:
    result = set(map(str, spec.get("existing_ids", [])))
    for start, end in spec.get("existing_ranges", []):
        if not isinstance(start, int) or not isinstance(end, int) or start > end:
            raise SystemExit("aggregate split plan contains an invalid ID range")
        result.update(_gap_id(number) for number in range(start, end + 1))
    return result


def _selected_ids(snapshot: dict[str, Any], selector: dict[str, Any]) -> set[str]:
    kinds = set(map(str, selector.get("control_kinds", [])))
    contains = [str(item).lower() for item in selector.get("control_id_or_label_contains", [])]
    pattern = re.compile(str(selector["control_id_regex"])) if selector.get("control_id_regex") else None
    result: set[str] = set()
    for surface in snapshot["surfaces"].values():
        for control_id, disposition in surface["control_dispositions"].items():
            record = surface["control_records"][control_id]
            if kinds and record["kind"] not in kinds:
                continue
            searchable = f"{control_id} {record['label']}".lower()
            if contains and not any(token in searchable for token in contains):
                continue
            if pattern is not None and not pattern.search(control_id):
                continue
            result.update(map(str, disposition["gap_ids"]))
    return result


def _parent_child_set(snapshot: dict[str, Any], spec: dict[str, Any]) -> set[str]:
    children = _expanded_existing_ids(spec)
    if spec.get("existing_selector"):
        children.update(_selected_ids(snapshot, spec["existing_selector"]))
    children.update(map(str, spec["new_children"].values()))
    return children


def _child_payload(parent: dict[str, Any], parent_id: str, key: str, gap_id: str) -> dict[str, Any]:
    label = key.replace("-", " ")
    blockers = list(parent.get("blockers", []))
    blockers.append("Exact typed-control or non-visible-path ownership has not yet been assigned to this child.")
    return {
        "gap_id": gap_id,
        "parent_surface": parent["parent_surface"],
        "feature": f"{parent['feature']}: {label}",
        "control_action": label,
        "discovery_source": PLAN.as_posix(),
        "discovered_at": DISCOVERED_AT,
        "discovered_by": ACTOR,
        "source_refs": [{"path": PLAN.as_posix(), "symbols": [f"parents.{parent_id}.new_children.{key}"]}],
        "expected_behavior": f"The {label} branch has an independently traceable control or runtime contract, full interaction chain, evidence, and lifecycle state.",
        "observed_behavior": f"{parent_id} combined the {label} branch with other concerns and had no independently addressable child card.",
        "interaction_chain": blank_interaction_chain("Newly split branch; exact control/path interaction has not yet been traced."),
        "classification": parent["classification"],
        "severity": parent["severity"],
        "operational_impact": f"Without an exact child for {label}, work can be skipped or aggregate progress can overstate completion. Parent impact: {parent['operational_impact']}",
        "dependencies": list(parent.get("dependencies", [])),
        "blockers": blockers,
        "assigned_owner": parent["assigned_owner"],
        "tests_required": [f"exact ownership trace for {label}", f"full interaction-chain evidence for {label}"],
        "completion_evidence": [],
        "reopen_reason": None,
        "defer_skip": None,
        "next_action": f"Trace {label} to exact typed controls or a non-visible path, then record a predecessor-safe resolution without advancing the parent.",
        "discovery_evidence": _evidence(f"The reviewed split plan allocates {gap_id} to the exact {parent_id}/{key} branch."),
    }


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
    plan = _load_plan(root)
    snapshot = read_snapshot(root)
    cards = snapshot["cards"]
    expected_last = plan["allocation_basis"]["last_existing_gap_id"]
    planned_ids = {
        gap_id
        for spec in plan["parents"].values()
        for gap_id in spec["new_children"].values()
    }
    already_existing = [gap_id for gap_id in planned_ids if gap_id in cards]
    if already_existing:
        print(f"INFO planned stable IDs already exist and will be treated as pre-applied: {sorted(already_existing, key=_sort_key)}")
    current_max = max(cards, key=_sort_key)
    if _sort_key(current_max) < _sort_key(expected_last):
        raise SystemExit("current stable-ID frontier differs from the reviewed allocation basis")

    # In-place reruns are idempotent; only add missing cards, relationships,
    # and aggregate scopes where they are not already in the ledger.
    entries: list[dict[str, object]] = []
    new_child_count = 0
    relationship_count = 0
    aggregate_count = 0
    already_scoped = 0
    selector_counts: dict[str, int] = {}
    existing_relationships = {
        (item["parent_gap_id"], item["child_gap_id"], item["relationship"])
        for item in snapshot.get("card_relationships", [])
    }
    for parent_id, spec in plan["parents"].items():
        parent = cards.get(parent_id)
        if parent is None:
            raise SystemExit(f"split plan references unknown parent: {parent_id}")

        children = _parent_child_set(snapshot, spec)
        if parent_id in children or not children:
            raise SystemExit(f"aggregate child set is empty or self-referential: {parent_id}")
        if spec.get("existing_selector"):
            selector_counts[parent_id] = len(_selected_ids(snapshot, spec["existing_selector"]))
        unknown = set(children) - set(cards)
        if unknown:
            raise SystemExit(f"aggregate references unknown children for {parent_id}: {sorted(unknown, key=_sort_key)}")

        ordered_children = sorted(children, key=_sort_key)
        for key, gap_id in spec["new_children"].items():
            if gap_id in cards:
                continue
            entries.append({
                "event_type": "card_discovered",
                "actor": ACTOR,
                "payload": _child_payload(parent, parent_id, key, gap_id),
            })
            new_child_count += 1

        for child_id in ordered_children:
            relationship_key = (parent_id, child_id, "child")
            if relationship_key in existing_relationships:
                continue
            entries.append({
                "event_type": "card_relationship",
                "actor": ACTOR,
                "payload": {
                    "parent_gap_id": parent_id,
                    "child_gap_id": child_id,
                    "relationship": "child",
                    "evidence": _evidence("The reviewed aggregate plan retains this exact child without changing its lifecycle state."),
                },
            })
            existing_relationships.add(relationship_key)
            relationship_count += 1

        current_scope = parent.get("control_scope_disposition")
        if current_scope is not None:
            if current_scope.get("kind") != "aggregate_parent":
                raise SystemExit(f"aggregate parent already has a conflicting scope: {parent_id}")
            current_child_set = set(map(str, current_scope.get("child_gap_ids", [])))
            required_child_set = set(ordered_children)
            if not required_child_set.issubset(current_child_set):
                # The parent scope is missing required reviewed children; issue a
                # scope revision to match the reviewed split plan.
                entries.append({
                    "event_type": "card_control_scope_revised",
                    "actor": ACTOR,
                    "payload": {
                        "gap_id": parent_id,
                        "previous_scope_sha256": card_control_scope_sha256(current_scope),
                        "kind": "aggregate_parent",
                        "child_gap_ids": ordered_children,
                        "reason": "The historical split plan was refined and this parent scope is being aligned to include all required reviewed children.",
                        "authority": "Predecessor-bound aggregate split reconciliation for historical card repair.",
                        "return_condition": "Keep this scope only while the reviewed split plan remains in force; revise with predecessor-bound proof on changes.",
                        "evidence": _evidence("The split plan now requires this exact child set for this aggregate parent."),
                    },
                })
                aggregate_count += 1
                continue
            if current_child_set == required_child_set:
                already_scoped += 1
                continue
            # Keep prior explicit child ownership and avoid forcing a full rewrite when
            # an existing scope already contains every required child.
            already_scoped += 1
            continue

        entries.append({
            "event_type": "card_control_scope_set",
            "actor": ACTOR,
            "payload": {
                "gap_id": parent_id,
                "kind": "aggregate_parent",
                "child_gap_ids": ordered_children,
                "reason": "The historical card combined multiple exact branches and now supervises an immutable child set instead of masquerading as one control-level item.",
                "authority": "Independent historical binding audit plus the hash-bound aggregate split plan.",
                "return_condition": "Use a predecessor-bound revision if the decomposition changes; keep the parent unresolved until every child resolves.",
                "evidence": _evidence("The plan records exact permanent child IDs, retained existing children, and deterministic selector rules."),
            },
        })
        aggregate_count += 1

    if args.apply:
        _append_in_batches(root, entries)
    print(json.dumps({
        "mode": "check" if args.check else "apply",
        "plan_sha256": EXPECTED_PLAN_SHA256,
        "new_child_cards": new_child_count,
        "aggregate_parent_scopes": aggregate_count,
        "already_scoped_aggregate_parents": already_scoped,
        "child_relationships": relationship_count,
        "selector_child_counts": selector_counts,
        "planned_or_appended_events": len(entries),
        "state_transitions": 0,
        "operational_claims": 0,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
