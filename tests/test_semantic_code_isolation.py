from __future__ import annotations

from pathlib import Path

from runtime.semantic_code_lifecycle import SemanticSessionManager
from runtime.semantic_code_query import SymbolQuery


def test_two_projects_never_share_index_state(tmp_path: Path):
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir(); right.mkdir()
    (left / "x.py").write_text("def left_only():\n    pass\n", encoding="utf-8")
    (right / "x.py").write_text("def right_only():\n    pass\n", encoding="utf-8")
    manager = SemanticSessionManager()
    ls = manager.open(left)
    rs = manager.open(right)
    assert ls.find(SymbolQuery("left_only"))
    assert not ls.find(SymbolQuery("right_only"))
    assert rs.find(SymbolQuery("right_only"))
    assert not rs.find(SymbolQuery("left_only"))
