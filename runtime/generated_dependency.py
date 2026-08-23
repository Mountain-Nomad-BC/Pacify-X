"""Acyclic generated-authority dependency model."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def generated_dependency_graph(
    declarations: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    nodes = sorted(
        set(declarations) | {str(v) for values in declarations.values() for v in values}
    )
    edges = sorted(
        {
            ("input", str(value), str(node))
            for node, values in declarations.items()
            for value in values
        },
        key=lambda item: (item[1].casefold(), item[2].casefold()),
    )
    adjacency = {node: [] for node in nodes}
    for _, source, target in edges:
        adjacency[source].append(target)
    index = 0
    stack: list[str] = []
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = low[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for target in adjacency[node]:
            if target not in indexes:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indexes[target])
        if low[node] == indexes[node]:
            component: list[str] = []
            while True:
                value = stack.pop()
                on_stack.remove(value)
                component.append(value)
                if value == node:
                    break
            components.append(sorted(component))

    for node in nodes:
        if node not in indexes:
            visit(node)
    cycles = [item for item in components if len(item) > 1]
    cycles.extend([[node]] for node in nodes if node in adjacency[node])
    return {
        "schema_version": "px.generated-dependency-graph/1.0",
        "valid": not cycles,
        "nodes": nodes,
        "edges": [
            {"source": source, "target": target, "kind": kind}
            for kind, source, target in edges
        ],
        "strongly_connected_components": components,
        "cycles": cycles,
        "failures": []
        if not cycles
        else [
            {
                "code": "RP-GEN-002",
                "message": "generated dependency cycle: "
                + " -> ".join(cycle + [cycle[0]]),
            }
            for cycle in cycles
        ],
    }
