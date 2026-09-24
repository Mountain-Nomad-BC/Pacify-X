from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_graph import build_semantic_graph, traverse_semantic_graph
from runtime.semantic_code_index import build_semantic_project_index


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_graph_contains_structural_and_reference_edges():
    index = build_semantic_project_index(FIXTURE)
    graph = build_semantic_graph(index)
    assert any(edge.relation == "contains" for edge in graph.edges)
    assert any(edge.relation == "references" for edge in graph.edges)
    device = next(item for item in index.symbols if item.qualified_name == "pkg.models.Device")
    walked = traverse_semantic_graph(graph, (device.symbol_id,), max_depth=2)
    assert device.symbol_id in walked
