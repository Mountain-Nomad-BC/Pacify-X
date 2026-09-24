from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from runtime.semantic_code_index import build_semantic_project_index
from runtime.semantic_code_limits import SemanticCodeLimits
from runtime.semantic_code_types import ReferenceResolution


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_index_is_deterministic_and_resolves_local_references(tmp_path: Path):
    root = tmp_path / "project"
    shutil.copytree(FIXTURE, root)
    first = build_semantic_project_index(root)
    second = build_semantic_project_index(root)
    assert first.revision == second.revision
    assert first.analyzed_files == 5
    helper = next(item for item in first.symbols if item.qualified_name == "pkg.models.helper")
    refs = [r for r in first.references if helper.symbol_id in r.target_symbol_ids]
    assert refs
    assert all(r.resolution == ReferenceResolution.RESOLVED for r in refs if r.name == "helper")


def test_index_enforces_semantic_file_budget(tmp_path: Path):
    for n in range(3):
        (tmp_path / f"{n}.py").write_text(f"x{n}=1\n", encoding="utf-8")
    with pytest.raises(Exception):
        build_semantic_project_index(tmp_path, limits=SemanticCodeLimits(max_files=2))
