from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_index import build_semantic_project_index
from runtime.semantic_code_query import SymbolQuery, find_references, find_symbols, symbol_overview
from runtime.semantic_code_types import SymbolKind


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_symbol_query_supports_exact_substring_and_kind_filter():
    index = build_semantic_project_index(FIXTURE)
    exact = find_symbols(index, SymbolQuery("pkg.models.Device.status"))
    assert len(exact) == 1
    methods = find_symbols(index, SymbolQuery("status", kinds=(SymbolKind.METHOD,), substring=True))
    assert len(methods) == 2


def test_overview_and_reference_query_are_bounded():
    index = build_semantic_project_index(FIXTURE)
    device = next(item for item in index.symbols if item.qualified_name == "pkg.models.Device")
    overview = symbol_overview(index, "pkg/models.py", max_depth=2, max_results=20)
    assert overview
    refs = find_references(index, device.symbol_id, max_results=10)
    assert isinstance(refs, tuple)
