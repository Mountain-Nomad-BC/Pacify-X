"""Minimum sufficient proof planning from dependency and test ownership facts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping

from .dependency_invalidation import compute_invalidation_cone


SCHEMA_VERSION = "px.affected-proof-plan/1.0"


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_affected_proof_plan(
    root: Path,
    changed_cards: Iterable[str],
    *,
    card_directory: str = ".engineering-bootstrap/punch-cards/cohesion-closure-20260904",
    projection_invalidation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    resolved = root.resolve()
    directory = resolved / card_directory
    dag = _load(directory / "dag.json")
    nodes = {
        str(row["card_id"]): row
        for row in dag.get("nodes", ())
        if isinstance(row, Mapping)
    }
    seeds = tuple(sorted(set(map(str, changed_cards))))
    unknown = sorted(set(seeds) - set(nodes))
    if not seeds or unknown:
        raise ValueError(f"changed cards must be known and non-empty: {unknown}")
    graph = {
        "nodes": [
            {"node_id": card_id, "kind": "source", "revision": "recorded"}
            for card_id in sorted(nodes)
        ],
        "edges": [
            {"dependency": dependency, "consumer": card_id}
            for card_id, row in nodes.items()
            for dependency in row.get("dependencies", ())
        ],
    }
    cone = compute_invalidation_cone(
        graph,
        {card_id: "changed" for card_id in seeds},
        authority={"node_kinds": [{"kind": "source", "rebuild_gate": "affected_proof"}]},
    )
    affected_cards = tuple(item["node_id"] for item in cone["stale_nodes"])
    cards = {card_id: _load(directory / str(nodes[card_id]["path"])) for card_id in affected_cards}
    focused_tests: set[str] = set()
    focused_vectors: set[str] = set()
    affected_tests: set[str] = set()
    negative_cases: dict[str, tuple[str, ...]] = {}
    sections: set[str] = set()
    for card_id, card in cards.items():
        for item in card.get("focused_tests", ()):
            value = str(item)
            (focused_tests if value.endswith(".py") else focused_vectors).add(value)
        affected_tests.update(
            str(item) for item in card.get("affected_tests", ()) if str(item).endswith(".py")
        )
        negative_cases[card_id] = tuple(map(str, card.get("negative_cases", ())))
        sections.update(map(str, card.get("affected_sections", ())))
    index = _load(resolved / "registry/test_group_index.json")
    owners: dict[str, str] = {}
    for group in index.get("groups", ()):
        if not isinstance(group, Mapping):
            continue
        for member in group.get("members", ()):
            path = str(member)
            prior = owners.get(path)
            if prior and prior != group.get("group"):
                raise ValueError(f"test has multiple group owners: {path}")
            owners[path] = str(group.get("group"))
    all_tests = tuple(sorted(focused_tests | affected_tests))
    unowned = tuple(path for path in all_tests if path not in owners)
    if unowned:
        raise ValueError(f"unowned test mapping: {list(unowned)}")
    groups = tuple(sorted({owners[path] for path in all_tests}))
    stale_projections = tuple(
        sorted(
            str(row.get("output"))
            for row in (projection_invalidation or {}).get("stale", ())
            if isinstance(row, Mapping)
        )
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "changed_cards": seeds,
        "direct_consumers": tuple(cone["direct_consumers"]),
        "transitive_consumers": tuple(cone["transitive_consumers"]),
        "affected_cards": affected_cards,
        "focused_tests": tuple(sorted(focused_tests)),
        "focused_vectors": tuple(sorted(focused_vectors)),
        "negative_cases": {key: negative_cases[key] for key in sorted(negative_cases)},
        "affected_tests": tuple(sorted(affected_tests - focused_tests)),
        "test_groups": groups,
        "sections": tuple(sorted(sections)),
        "stale_projections": stale_projections,
        "stale_evidence": tuple(
            [*(f"group:{name}" for name in groups), *(f"section:{name}" for name in sorted(sections))]
        ),
        "broad_profile_allowed_during_repair": False,
        "completion_requires_downstream_green": bool(
            cone["direct_consumers"] or cone["transitive_consumers"]
        ),
    }
    return {**payload, "plan_sha256": _digest(payload)}


def validate_proof_completion(
    plan: Mapping[str, object], completion: Mapping[str, object]
) -> dict[str, object]:
    errors: list[str] = []
    if completion.get("broad_profile_run"):
        errors.append("broad_profile_selected_during_repair")
    checks = (
        ("focused_tests", "passed_focused_tests"),
        ("affected_tests", "passed_affected_tests"),
        ("test_groups", "passed_test_groups"),
        ("sections", "passed_sections"),
        ("stale_projections", "rebuilt_projections"),
    )
    for required_key, actual_key in checks:
        missing = sorted(
            set(map(str, plan.get(required_key, ())))
            - set(map(str, completion.get(actual_key, ())))
        )
        errors.extend(f"missing_{actual_key}:{item}" for item in missing)
    negative_cards = {
        card_id
        for card_id, cases in plan.get("negative_cases", {}).items()
        if cases
    }
    missing_negative = sorted(
        negative_cards - set(map(str, completion.get("passed_negative_cards", ())))
    )
    errors.extend(f"missing_negative_proof:{item}" for item in missing_negative)
    if plan.get("completion_requires_downstream_green"):
        required = set(map(str, plan.get("direct_consumers", ()))) | set(
            map(str, plan.get("transitive_consumers", ()))
        )
        green = set(map(str, completion.get("downstream_green_cards", ())))
        errors.extend(f"downstream_not_green:{item}" for item in sorted(required - green))
    return {
        "schema_version": "px.affected-proof-completion/1.0",
        "valid": not errors,
        "errors": tuple(errors),
        "plan_sha256": plan.get("plan_sha256"),
    }
