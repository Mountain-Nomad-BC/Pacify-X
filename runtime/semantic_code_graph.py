"""Bounded semantic symbol graph construction and traversal."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .semantic_code_index import SemanticProjectIndex
from .semantic_code_limits import SemanticCodeLimits


@dataclass(frozen=True, slots=True, order=True)
class SemanticEdge:
    source: str
    relation: str
    target: str


@dataclass(frozen=True, slots=True)
class SemanticGraph:
    nodes: tuple[str, ...]
    edges: tuple[SemanticEdge, ...]
    index_revision: str


def build_semantic_graph(
    index: SemanticProjectIndex,
    *,
    limits: SemanticCodeLimits = SemanticCodeLimits(),
) -> SemanticGraph:
    node_ids = {symbol.symbol_id for symbol in index.symbols}
    if len(node_ids) > limits.max_graph_nodes:
        raise ValueError(
            f"semantic graph node budget exceeded: {len(node_ids)} > {limits.max_graph_nodes}"
        )
    edges: set[SemanticEdge] = set()
    for symbol in index.symbols:
        if symbol.parent_symbol_id and symbol.parent_symbol_id in node_ids:
            edges.add(SemanticEdge(symbol.parent_symbol_id, "contains", symbol.symbol_id))
    for reference in index.references:
        if reference.source_symbol_id is None:
            continue
        if reference.source_symbol_id not in node_ids:
            continue
        for target in reference.target_symbol_ids:
            if target in node_ids and target != reference.source_symbol_id:
                edges.add(SemanticEdge(reference.source_symbol_id, "references", target))
        if len(edges) > limits.max_graph_edges:
            raise ValueError(
                f"semantic graph edge budget exceeded: {len(edges)} > {limits.max_graph_edges}"
            )
    ordered = tuple(sorted(edges))
    return SemanticGraph(tuple(sorted(node_ids)), ordered, index.revision)


def traverse_semantic_graph(
    graph: SemanticGraph,
    seeds: tuple[str, ...],
    *,
    max_depth: int = 2,
    max_nodes: int = 200,
    relations: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if not isinstance(seeds, tuple) or not seeds:
        raise ValueError("semantic graph seeds must be a non-empty tuple")
    if type(max_depth) is not int or not 0 <= max_depth <= 16:
        raise ValueError("max_depth must be between 0 and 16")
    if type(max_nodes) is not int or not 1 <= max_nodes <= 10_000:
        raise ValueError("max_nodes must be between 1 and 10000")
    allowed = set(relations)
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if allowed and edge.relation not in allowed:
            continue
        adjacency.setdefault(edge.source, []).append(edge.target)
    for values in adjacency.values():
        values.sort()
    seen: set[str] = set()
    queue = deque((seed, 0) for seed in seeds)
    while queue:
        node, depth = queue.popleft()
        if node in seen:
            continue
        if len(seen) >= max_nodes:
            break
        seen.add(node)
        if depth >= max_depth:
            continue
        for target in adjacency.get(node, ()):
            if target not in seen:
                queue.append((target, depth + 1))
    return tuple(sorted(seen))
