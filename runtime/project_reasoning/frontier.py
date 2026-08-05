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
    path = root / "orchestration/workflows/engineering-reasoning-loop.yaml"
    if not path.is_file():
        return {"valid": False, "errors": ["workflow missing"]}
    text = path.read_text(encoding="utf-8")
    required = (
        "frontier-questioning",
        "domain-language-maintenance",
        "design-it-twice",
        "deep-module-design",
        "architecture-deepening-audit",
        "decision-wayfinding",
        "questionnaire-delegation",
        "guided-procedure-wizard",
        "tracer-bullet-planning",
        "dual-axis-code-review",
        "intent-preserving-merge-resolution",
        "context-handoff-package",
    )
    missing = [identifier for identifier in required if f'"{identifier}"' not in text]
    return {
        "valid": not missing,
        "errors": [f"missing skill: {item}" for item in missing],
        "skill_count": len(required),
        "effects": ["read_local", "write_workspace"],
    }
