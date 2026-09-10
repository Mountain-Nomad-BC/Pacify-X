"""Acyclic generated-authority dependency model with bounded typed inputs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .json_io import bounded_json_text


MAX_NODES = 10_000
MAX_EDGES = 20_000
MAX_ID_BYTES = 4096
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_RESULT_BYTES = 32 * 1024 * 1024
GRAPH_SCHEMA = "px.generated-dependency-graph/1.0"


def dependency_identity(value: object) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > MAX_ID_BYTES
        or len(value.encode("utf-8")) > MAX_ID_BYTES
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("dependency identity must be bounded nonempty text")
    return value


def strongly_connected_components(
    nodes: list[str], edges: list[tuple[str, str]]
) -> list[list[str]]:
    """Iterative Tarjan traversal; caller supplies a bounded validated graph."""
    adjacency = {node: [] for node in nodes}
    for source, target in edges:
        adjacency[source].append(target)
    indexes: dict[str, int] = {}
    low: dict[str, int] = {}
    active: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def enter(node: str):
        indexes[node] = low[node] = len(indexes)
        active.append(node)
        on_stack.add(node)
        return node, iter(adjacency[node])

    for start in nodes:
        if start in indexes:
            continue
        frames = [enter(start)]
        while frames:
            node, targets = frames[-1]
            target = next(targets, None)
            if target is not None:
                if target not in indexes:
                    frames.append(enter(target))
                elif target in on_stack:
                    low[node] = min(low[node], indexes[target])
                continue
            frames.pop()
            if frames:
                parent = frames[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == indexes[node]:
                component = []
                while True:
                    value = active.pop()
                    on_stack.remove(value)
                    component.append(value)
                    if value == node:
                        break
                components.append(sorted(component))
    return components


def generated_dependency_graph(
    declarations: Mapping[str, Iterable[str]],
) -> dict[str, Any]:
    if not isinstance(declarations, Mapping) or len(declarations) > MAX_NODES:
        raise ValueError("dependency declarations require a bounded mapping")
    nodes: set[str] = set()
    edges: set[tuple[str, str]] = set()
    input_bytes = 0
    observed_edges = 0

    def acquire(value: object) -> str:
        nonlocal input_bytes
        node = dependency_identity(value)
        input_bytes += len(node.encode("utf-8"))
        if input_bytes > MAX_INPUT_BYTES:
            raise ValueError("dependency identity byte budget exceeded")
        nodes.add(node)
        if len(nodes) > MAX_NODES:
            raise ValueError("dependency node budget exceeded")
        return node

    # Consume each declared iterable once, counting before deduplication.
    for key, values in declarations.items():
        node = acquire(key)
        if isinstance(values, (str, bytes, bytearray, Mapping)):
            raise ValueError("dependency inputs must be an iterable of identities")
        try:
            iterator = iter(values)
        except TypeError as error:
            raise ValueError("dependency inputs must be iterable") from error
        for value in iterator:
            observed_edges += 1
            if observed_edges > MAX_EDGES:
                raise ValueError("dependency edge budget exceeded")
            edges.add((acquire(value), node))
    ordered_nodes = sorted(nodes)
    ordered_edges = sorted(
        edges,
        key=lambda item: (item[0].casefold(), item[1].casefold(), item[0], item[1]),
    )
    components = strongly_connected_components(ordered_nodes, ordered_edges)
    cycles = sorted(
        component
        for component in components
        if len(component) > 1 or (component[0], component[0]) in edges
    )
    result = {
        "schema_version": GRAPH_SCHEMA,
        "valid": not cycles,
        "nodes": ordered_nodes,
        "edges": [
            {"source": source, "target": target, "kind": "input"}
            for source, target in ordered_edges
        ],
        "strongly_connected_components": components,
        "cycles": cycles,
        "failures": [
            {
                "code": "RP-GEN-002",
                "message": (
                    "generated dependency cycle: " + cycle[0] + " -> " + cycle[0]
                    if len(cycle) == 1
                    else "generated dependency cycle component: " + ", ".join(cycle)
                ),
            }
            for cycle in cycles
        ],
    }
    bounded_json_text(result, max_bytes=MAX_RESULT_BYTES)
    return result
