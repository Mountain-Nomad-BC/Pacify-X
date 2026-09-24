from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from runtime.semantic_code_project import SemanticProjectSession
from runtime.semantic_code_query import SymbolQuery


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_project_session_isolated_refresh_and_unique_lookup(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    session = SemanticProjectSession(root)
    first = session.index()
    symbol = session.find_unique(SymbolQuery("pkg.models.Device"))
    assert symbol.name == "Device"
    (root / "pkg/models.py").write_text(
        (root / "pkg/models.py").read_text(encoding="utf-8") + "\nNEW_VALUE = 1\n",
        encoding="utf-8",
    )
    assert session.index().revision == first.revision
    assert session.index(refresh=True).revision != first.revision
    session.close()
    with pytest.raises(RuntimeError):
        session.index()
