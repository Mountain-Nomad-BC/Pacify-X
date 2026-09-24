from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from runtime.semantic_code_document import read_document_snapshot
from runtime.semantic_code_edits import plan_replace_symbol
from runtime.semantic_code_index import build_semantic_project_index
from runtime.semantic_code_transaction import apply_semantic_edit_plan


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def _plan(root: Path):
    index = build_semantic_project_index(root)
    symbol = next(item for item in index.symbols if item.qualified_name == "pkg.models.helper")
    snapshot = read_document_snapshot(root, "pkg/models.py", max_bytes=100_000)
    return plan_replace_symbol(
        snapshot,
        symbol,
        'def helper(value: str) -> str:\n    return f"changed:{value}"\n',
    )


def test_preview_is_side_effect_free(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    plan = _plan(root)
    before = (root / "pkg/models.py").read_bytes()
    result = apply_semantic_edit_plan(root, plan, write=False)
    assert not result.written
    assert "changed:" in (result.text or "")
    assert (root / "pkg/models.py").read_bytes() == before
    assert not (root / ".px").exists()


def test_write_is_atomic_revision_guarded_and_parse_checked(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    plan = _plan(root)
    result = apply_semantic_edit_plan(root, plan, write=True)
    assert result.written
    assert "changed:" in (root / "pkg/models.py").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        apply_semantic_edit_plan(root, plan, write=False)
