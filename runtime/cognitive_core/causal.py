"""Small causal-DAG analysis kernel with auditable adjustment-set checks."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from typing import Any

from .common import stable_hash


class CausalGraph:
    def __init__(self, nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> None:
        self.nodes = frozenset(map(str, nodes))
        self.children: dict[str, set[str]] = {node: set() for node in self.nodes}
        self.parents: dict[str, set[str]] = {node: set() for node in self.nodes}
        for source, target in edges:
            source, target = str(source), str(target)
            if source not in self.nodes or target not in self.nodes:
                raise ValueError(f"edge references unknown node: {source} -> {target}")
            if source == target:
                raise ValueError("causal self-edges are forbidden")
            self.children[source].add(target)
            self.parents[target].add(source)
        cycle = self._cycle_nodes()
        if cycle:
            raise ValueError(
                f"causal graph must be acyclic; cycle nodes: {sorted(cycle)}"
            )

    def _cycle_nodes(self) -> set[str]:
        indegree = {node: len(self.parents[node]) for node in self.nodes}
        queue = deque(sorted(node for node, degree in indegree.items() if degree == 0))
        seen = set()
        while queue:
            node = queue.popleft()
            seen.add(node)
            for child in sorted(self.children[node]):
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        return set(self.nodes) - seen

    def ancestors(self, nodes: Iterable[str]) -> set[str]:
        result = set(map(str, nodes))
        queue = list(result)
        while queue:
            node = queue.pop()
            for parent in self.parents[node]:
                if parent not in result:
                    result.add(parent)
                    queue.append(parent)
        return result

    def descendants(self, nodes: Iterable[str]) -> set[str]:
        result = set(map(str, nodes))
        queue = list(result)
        while queue:
            node = queue.pop()
            for child in self.children[node]:
                if child not in result:
                    result.add(child)
                    queue.append(child)
        return result

    def d_separated(
        self,
        left: Iterable[str],
        right: Iterable[str],
        conditioned: Iterable[str],
        *,
        remove_outgoing_from: Iterable[str] = (),
    ) -> bool:
        """Use the ancestral moral-graph criterion for d-separation."""
        x, y, z = set(map(str, left)), set(map(str, right)), set(map(str, conditioned))
        unknown = (x | y | z) - self.nodes
        if unknown:
            raise ValueError(f"unknown causal nodes: {sorted(unknown)}")
        relevant = self.ancestors(x | y | z)
        removed_outgoing = set(map(str, remove_outgoing_from))
        undirected: dict[str, set[str]] = {node: set() for node in relevant}
        local_parents: dict[str, set[str]] = {node: set() for node in relevant}
        for source in relevant:
            for target in self.children[source]:
                if target not in relevant or source in removed_outgoing:
                    continue
                undirected[source].add(target)
                undirected[target].add(source)
                local_parents[target].add(source)
        for child, parents in local_parents.items():
            parent_list = sorted(parents)
            for index, first in enumerate(parent_list):
                for second in parent_list[index + 1 :]:
                    undirected[first].add(second)
                    undirected[second].add(first)
        blocked = z
        queue = deque(sorted(x - blocked))
        seen = set(queue)
        while queue:
            node = queue.popleft()
            if node in y:
                return False
            for neighbor in sorted(undirected[node] - blocked - seen):
                seen.add(neighbor)
                queue.append(neighbor)
        return True

    def validate_backdoor(
        self, treatment: str, outcome: str, adjustment: Iterable[str]
    ) -> dict[str, Any]:
        treatment, outcome = str(treatment), str(outcome)
        adjustment_set = set(map(str, adjustment))
        if treatment not in self.nodes or outcome not in self.nodes:
            raise ValueError("treatment and outcome must be graph nodes")
        descendants = self.descendants({treatment}) - {treatment}
        descendant_adjustments = sorted(adjustment_set & descendants)
        separated = self.d_separated(
            {treatment}, {outcome}, adjustment_set, remove_outgoing_from={treatment}
        )
        valid = (
            separated
            and not descendant_adjustments
            and treatment not in adjustment_set
            and outcome not in adjustment_set
        )
        return {
            "valid": valid,
            "treatment": treatment,
            "outcome": outcome,
            "adjustment": sorted(adjustment_set),
            "blocks_backdoor_paths": separated,
            "descendants_of_treatment_in_adjustment": descendant_adjustments,
            "warning": "A graph can test assumptions encoded in the DAG; it cannot prove the DAG is causally correct.",
        }

    def directed_paths(
        self, source: str, target: str, *, limit: int = 50, max_depth: int = 12
    ) -> list[list[str]]:
        if source not in self.nodes or target not in self.nodes:
            raise ValueError("source and target must be graph nodes")
        paths: list[list[str]] = []
        stack: list[tuple[str, list[str]]] = [(source, [source])]
        while stack and len(paths) < limit:
            node, path = stack.pop()
            if len(path) > max_depth:
                continue
            if node == target:
                paths.append(path)
                continue
            for child in sorted(self.children[node], reverse=True):
                if child not in path:
                    stack.append((child, path + [child]))
        return paths


def analyze(payload: Mapping[str, Any]) -> dict[str, Any]:
    nodes = [str(item) for item in payload.get("nodes", ())]
    edges = [
        (str(item["source"]), str(item["target"])) for item in payload.get("edges", ())
    ]
    graph = CausalGraph(nodes, edges)
    operation = str(payload.get("operation", "describe"))
    if operation == "validate-backdoor":
        result = graph.validate_backdoor(
            str(payload["treatment"]),
            str(payload["outcome"]),
            payload.get("adjustment", ()),
        )
    elif operation == "d-separated":
        result = {
            "valid": True,
            "d_separated": graph.d_separated(
                payload.get("left", ()),
                payload.get("right", ()),
                payload.get("conditioned", ()),
            ),
        }
    elif operation == "effect-paths":
        paths = graph.directed_paths(
            str(payload["source"]),
            str(payload["target"]),
            limit=int(payload.get("limit", 50)),
            max_depth=int(payload.get("max_depth", 12)),
        )
        result = {"valid": True, "paths": paths, "path_count": len(paths)}
    else:
        result = {
            "valid": True,
            "nodes": sorted(graph.nodes),
            "edges": [
                {"source": source, "target": target} for source, target in sorted(edges)
            ],
            "roots": sorted(node for node in graph.nodes if not graph.parents[node]),
            "leaves": sorted(node for node in graph.nodes if not graph.children[node]),
        }
    return {**result, "result_sha256": stable_hash(result)}
