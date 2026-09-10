"""Validate decision-ticket graphs and select the open knowledge frontier."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path


CLOSED_STATES = {"done", "closed", "resolved"}
OPEN_STATES = {"open", "ready", "blocked", "in_progress", *CLOSED_STATES}


def _ticket_map(document: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    rows = document.get("tickets", ())
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ValueError("decision map tickets must be an array")
    result: dict[str, Mapping[str, object]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("each decision ticket must be an object")
        identifier = str(row.get("id", "")).strip()
        if not identifier or identifier in result:
            raise ValueError("decision ticket IDs must be nonempty and unique")
        state = str(row.get("status", "open"))
        if state not in OPEN_STATES:
            raise ValueError(f"{identifier}: unsupported status {state}")
        blockers = row.get("blocked_by", ())
        if not isinstance(blockers, Sequence) or isinstance(blockers, (str, bytes)):
            raise ValueError(f"{identifier}: blocked_by must be an array")
        result[identifier] = row
    for identifier, row in result.items():
        missing = sorted(set(map(str, row.get("blocked_by", ()))) - set(result))
        if missing:
            raise ValueError(f"{identifier}: unknown blockers {missing}")
    return result


def find_cycles(document: Mapping[str, object]) -> tuple[tuple[str, ...], ...]:
    tickets = _ticket_map(document)
    graph = {
        identifier: tuple(sorted(set(map(str, row.get("blocked_by", ())))))
        for identifier, row in tickets.items()
    }
    visited: set[str] = set()
    active: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(identifier: str) -> None:
        if identifier in active:
            cycle = active[active.index(identifier) :] + [identifier]
            core = cycle[:-1]
            rotations = [
                tuple(core[index:] + core[:index]) for index in range(len(core))
            ]
            canonical = min(rotations)
            cycles.add((*canonical, canonical[0]))
            return
        if identifier in visited:
            return
        active.append(identifier)
        for blocker in graph[identifier]:
            visit(blocker)
        active.pop()
        visited.add(identifier)

    for identifier in sorted(graph):
        visit(identifier)
    return tuple(sorted(cycles))


def decision_frontier(document: Mapping[str, object]) -> dict[str, object]:
    tickets = _ticket_map(document)
    cycles = find_cycles(document)
    if cycles:
        return {
            "valid": False,
            "frontier": [],
            "cycles": [list(item) for item in cycles],
            "errors": ["decision graph contains a cycle"],
        }
    closed = {
        identifier
        for identifier, row in tickets.items()
        if str(row.get("status", "open")) in CLOSED_STATES
    }
    ready = []
    for identifier, row in tickets.items():
        if identifier in closed or row.get("claimed_by"):
            continue
        blockers = tuple(map(str, row.get("blocked_by", ())))
        if all(blocker in closed for blocker in blockers):
            ready.append(dict(row))
    ready.sort(
        key=lambda row: (
            -float(row.get("impact", 0.0)),
            -float(row.get("irreversibility", 0.0)),
            -float(row.get("uncertainty", 0.0)),
            float(row.get("answer_cost", 1.0)),
            str(row["id"]),
        )
    )
    canonical = json.dumps(
        ready, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return {
        "valid": True,
        "frontier": ready,
        "cycles": [],
        "closed_count": len(closed),
        "ticket_count": len(tickets),
        "frontier_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "errors": [],
    }


def validate_reasoning_orchestration(root: Path) -> dict[str, object]:
    """Validate exact structural stages; current admission and execution remain separate."""
    from ..input_files import cooperative_deadline
    from ..numeric_inputs import bounded_text
    from ..workflow_inputs import active_skill_declarations, ordered_steps, read_declaration, unique_declarations

    expected = (('question-frontier', 'frontier-questioning', ()), ('canonical-language', 'domain-language-maintenance', ('question-frontier',)), ('decision-map', 'decision-wayfinding', ('question-frontier',)), ('delegate-authority', 'questionnaire-delegation', ('decision-map',)), ('compare-designs', 'design-it-twice', ('canonical-language', 'decision-map')), ('design-module', 'deep-module-design', ('compare-designs',)), ('audit-depth', 'architecture-deepening-audit', ('design-module',)), ('plan-slices', 'tracer-bullet-planning', ('audit-depth', 'delegate-authority')), ('manual-transition', 'guided-procedure-wizard', ('plan-slices',)), ('review-two-axes', 'dual-axis-code-review', ('plan-slices',)), ('reconcile-intent', 'intent-preserving-merge-resolution', ('review-two-axes',)), ('handoff', 'context-handoff-package', ('manual-transition', 'reconcile-intent')))
    try:
        deadline = cooperative_deadline()
        payload = read_declaration(root, "orchestration/workflows/engineering-reasoning-loop.yaml", deadline=deadline)
        workflows = unique_declarations(payload.get("workflows"), "id", maximum=256)
        if payload.get("schema_version") != "1.0" or payload.get("registry") != "registry/skill_orchestrations.json" or tuple(workflows) != ("engineering-reasoning-loop",):
            raise ValueError("reasoning workflow envelope mismatch")
        workflow = workflows["engineering-reasoning-loop"]
        steps = ordered_steps(workflow.get("steps"))
        actual = tuple((step["id"], step["skill"], tuple(step["depends_on"])) for step in steps)
        if actual != expected:
            raise ValueError("reasoning workflow steps, bindings or order mismatch")
        bounded_text(workflow.get("failure_policy"), "failure policy", maximum=4096)
        active = active_skill_declarations(root, deadline=deadline)
        if any(step["skill"] not in active for step in steps):
            raise ValueError("reasoning workflow skill is not declared active or admitted")
    except (OSError, ValueError, TypeError):
        return {"valid": False, "errors": ["invalid bounded reasoning workflow declarations"], "skill_count": None, "authority_granted": False}
    return {"valid": True, "errors": [], "skill_count": len(expected), "effects": ["read_local", "write_workspace"], "authority_granted": False, "evidence_level": "structural-declarations; current package admission and execution require separate proof"}
