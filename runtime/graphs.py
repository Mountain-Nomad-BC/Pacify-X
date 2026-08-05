"""Deterministic registry graphs and fail-closed orchestration validation.

The graph functions consume registry metadata only.  They never import a skill
body, resolve an adapter, or execute a tool.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Mapping

from .admission_controller import KNOWN_EFFECTS


SERIAL_EFFECTS = frozenset(
    {
        "write_workspace",
        "install_tool",
        "network",
        "run_service",
        "migration",
        "destructive",
    }
)


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source: str
    target: str
    relation: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class GraphBundle:
    capability_nodes: tuple[str, ...]
    capability_edges: tuple[GraphEdge, ...]
    io_edges: tuple[GraphEdge, ...]
    dependency_effect_edges: tuple[GraphEdge, ...]


@dataclass(frozen=True, slots=True)
class RankedPath:
    capabilities: tuple[str, ...]
    score: float
    safety: float
    cost: float
    latency: float
    explanation: tuple[str, ...]


def _contracts(
    records: Iterable[Mapping[str, object]],
) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for record in records:
        capability_id = record.get("id")
        if not isinstance(capability_id, str) or not capability_id:
            raise ValueError("capability contract has no id")
        if capability_id in result:
            raise ValueError(f"duplicate capability id: {capability_id}")
        result[capability_id] = record
    return result


def build_graphs(records: Iterable[Mapping[str, object]]) -> GraphBundle:
    """Create sorted graph edges from admitted capability contracts."""
    contracts = _contracts(records)
    capability_edges: list[GraphEdge] = []
    io_edges: list[GraphEdge] = []
    dependency_effect_edges: list[GraphEdge] = []
    producers: dict[str, list[str]] = defaultdict(list)
    for capability_id, contract in contracts.items():
        for output in contract.get("provides", ()):
            if isinstance(output, str):
                producers[output].append(capability_id)
        for dependency in contract.get("dependencies", ()):
            if isinstance(dependency, str):
                capability_edges.append(
                    GraphEdge(capability_id, dependency, "depends_on")
                )
                dependency_effect_edges.append(
                    GraphEdge(capability_id, dependency, "hard_dependency")
                )
        for conflict in contract.get("conflicts", ()):
            if isinstance(conflict, str):
                capability_edges.append(
                    GraphEdge(capability_id, conflict, "conflicts_with")
                )
        for effect in contract.get("effects", ()):
            if isinstance(effect, str):
                dependency_effect_edges.append(
                    GraphEdge(capability_id, effect, "declares_effect")
                )
        approval = contract.get("approval", {})
        if isinstance(approval, Mapping) and approval:
            dependency_effect_edges.append(
                GraphEdge(capability_id, "approval", "requires")
            )
        evidence = contract.get("evidence", {})
        if isinstance(evidence, Mapping) and evidence:
            dependency_effect_edges.append(
                GraphEdge(capability_id, "evidence", "requires")
            )
    for target_id, contract in contracts.items():
        for consumed in contract.get("consumes", ()):
            if not isinstance(consumed, str):
                continue
            for source_id in producers.get(consumed, ()):
                if source_id != target_id:
                    io_edges.append(
                        GraphEdge(source_id, target_id, "produces_for", consumed)
                    )

    def sorter(edge: GraphEdge) -> tuple[str, str, str, str]:
        return edge.source, edge.target, edge.relation, edge.detail

    return GraphBundle(
        tuple(sorted(contracts)),
        tuple(sorted(capability_edges, key=sorter)),
        tuple(sorted(io_edges, key=sorter)),
        tuple(sorted(dependency_effect_edges, key=sorter)),
    )


def find_io_paths(
    records: Iterable[Mapping[str, object]],
    source_type: str,
    target_type: str,
    *,
    limit: int = 3,
) -> tuple[tuple[str, ...], ...]:
    """Return deterministic, shortest capability paths from one type to another."""
    if not source_type or not target_type or limit < 1:
        raise ValueError("source_type, target_type, and positive limit are required")
    contracts = _contracts(records)
    available: dict[str, set[str]] = {source_type: {"$input"}}
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(source_type, ())])
    paths: list[tuple[str, ...]] = []
    while queue and len(paths) < limit:
        current, path = queue.popleft()
        if current == target_type and path:
            paths.append(path)
            continue
        for capability_id, contract in sorted(contracts.items()):
            consumes = set(
                value
                for value in contract.get("consumes", ())
                if isinstance(value, str)
            )
            provides = sorted(
                value
                for value in contract.get("provides", ())
                if isinstance(value, str)
            )
            if current not in consumes or capability_id in path:
                continue
            for produced in provides:
                candidate = path + (capability_id,)
                known = available.setdefault(produced, set())
                signature = "|".join(candidate)
                if signature in known:
                    continue
                known.add(signature)
                queue.append((produced, candidate))
    return tuple(sorted(paths, key=lambda path: (len(path), path)))


def rank_io_paths(
    records: Iterable[Mapping[str, object]],
    source_type: str,
    target_type: str,
    *,
    limit: int = 3,
) -> tuple[RankedPath, ...]:
    """Rank compatible paths by bounded metadata, never by loading implementations."""
    records = tuple(records)
    contracts = _contracts(records)
    candidates = find_io_paths(
        records, source_type, target_type, limit=max(limit * 4, limit)
    )
    ranked: list[RankedPath] = []
    for path in candidates:
        path_records = [contracts[item] for item in path]
        risks = [
            {"R0": 1.0, "R1": 0.8, "R2": 0.5, "R3": 0.2, "R4": 0.0}.get(
                str(item.get("risk", "R2")), 0.5
            )
            for item in path_records
        ]
        mutating = sum(
            bool(set(item.get("effects", ())) & SERIAL_EFFECTS) for item in path_records
        )
        safety = max(0.0, (sum(risks) / len(risks)) - 0.15 * mutating)
        cost = sum(
            float(item.get("cost", {}).get("max_tool_calls", 0))
            for item in path_records
            if isinstance(item.get("cost"), Mapping)
        )
        latency = sum(
            float(item.get("latency", {}).get("max_seconds", 0))
            for item in path_records
            if isinstance(item.get("latency"), Mapping)
        )
        freshness = sum(
            1.0
            if isinstance(item.get("evidence"), Mapping)
            and item.get("evidence", {}).get("status") == "current"
            else 0.25
            for item in path_records
        ) / len(path_records)
        score = round(20 * safety + 5 * freshness - cost - latency - len(path), 3)
        ranked.append(
            RankedPath(
                path,
                score,
                round(safety, 3),
                cost,
                latency,
                (
                    f"steps={len(path)}",
                    f"freshness={freshness:.3f}",
                    f"mutating_steps={mutating}",
                ),
            )
        )
    return tuple(
        sorted(ranked, key=lambda item: (-item.score, item.capabilities))[:limit]
    )


def validate_orchestration(
    spec: Mapping[str, object], contracts: Iterable[Mapping[str, object]]
) -> tuple[str, ...]:
    """Validate a declarative DAG before it can be admitted to a workflow registry."""
    known = _contracts(contracts)
    errors: list[str] = []
    for field in (
        "id",
        "version",
        "status",
        "inputs",
        "outputs",
        "steps",
        "parallelism",
        "stop_conditions",
    ):
        if field not in spec:
            errors.append(f"missing orchestration field: {field}")
    steps = spec.get("steps", ())
    if not isinstance(steps, list):
        return tuple(errors + ["steps must be a list"])
    ids: set[str] = set()
    by_id: dict[str, Mapping[str, object]] = {}
    for step in steps:
        if not isinstance(step, Mapping):
            errors.append("step must be an object")
            continue
        step_id = step.get("id")
        capability = step.get("capability")
        if not isinstance(step_id, str) or not step_id:
            errors.append("step id must be a non-empty string")
            continue
        if step_id in ids:
            errors.append(f"duplicate step id: {step_id}")
            continue
        ids.add(step_id)
        by_id[step_id] = step
        if not isinstance(capability, str) or capability not in known:
            errors.append(f"{step_id}: unknown capability {capability}")
            continue
        declared = set(known[capability].get("effects", ()))
        requested = set(step.get("effects", declared))
        unknown = requested - KNOWN_EFFECTS
        if unknown:
            errors.append(f"{step_id}: unknown effects: {', '.join(sorted(unknown))}")
        if not requested <= declared:
            errors.append(f"{step_id}: effects exceed capability declaration")
    for step_id, step in sorted(by_id.items()):
        for dependency in step.get("depends_on", ()):
            if dependency not in ids:
                errors.append(f"{step_id}: unknown dependency step {dependency}")
        for dependency in step.get("optional_depends_on", ()):
            if dependency in ids and dependency == step_id:
                errors.append(f"{step_id}: optional dependency cannot reference itself")
    # Detect cycles with a deterministic depth-first traversal.
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visiting:
            errors.append(f"orchestration cycle includes {step_id}")
            return
        if step_id in visited:
            return
        visiting.add(step_id)
        dependencies = list(by_id[step_id].get("depends_on", ())) + [
            value
            for value in by_id[step_id].get("optional_depends_on", ())
            if value in by_id
        ]
        for dependency in sorted(dependencies):
            if dependency in by_id:
                visit(dependency)
        visiting.remove(step_id)
        visited.add(step_id)

    for step_id in sorted(by_id):
        visit(step_id)
    selected = {
        str(step.get("capability"))
        for step in by_id.values()
        if isinstance(step.get("capability"), str)
    }
    for capability_id in sorted(selected):
        for conflict in known.get(capability_id, {}).get("conflicts", ()):
            if conflict in selected:
                errors.append(
                    f"effect conflict: {capability_id} conflicts with {conflict}"
                )
    parallelism = spec.get("parallelism", {})
    if (
        not isinstance(parallelism, Mapping)
        or not isinstance(parallelism.get("max_agents"), int)
        or parallelism["max_agents"] < 1
    ):
        errors.append("parallelism.max_agents must be a positive integer")
    resource = spec.get("resource_budget", {})
    if resource and (
        not isinstance(resource, Mapping)
        or not isinstance(resource.get("max_tool_calls"), int)
        or resource["max_tool_calls"] < 0
    ):
        errors.append("resource_budget.max_tool_calls must be a non-negative integer")
    if isinstance(parallelism, Mapping) and parallelism.get("max_agents", 1) > 1:
        serial_steps = [
            step_id
            for step_id, step in by_id.items()
            if set(step.get("effects", ())) & SERIAL_EFFECTS
        ]
        if len(serial_steps) > 1:
            errors.append(
                "effect conflict: serial effects require an explicit serial dependency chain"
            )
    return tuple(sorted(set(errors)))
