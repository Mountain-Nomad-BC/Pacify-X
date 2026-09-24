from __future__ import annotations

from pathlib import Path

import pytest

from runtime.semantic_code_lifecycle import SemanticSessionManager
from runtime.semantic_code_limits import SemanticCodeLimits
from runtime.semantic_code_registry import SemanticBackendRegistry


def test_session_manager_evicts_oldest_project(tmp_path: Path):
    roots = []
    for name in ("a", "b", "c"):
        root = tmp_path / name
        root.mkdir()
        (root / "x.py").write_text("x=1\n", encoding="utf-8")
        roots.append(root)
    manager = SemanticSessionManager(max_sessions=2)
    first = manager.open(roots[0])
    manager.open(roots[1])
    manager.open(roots[2])
    assert roots[0].resolve().as_posix() not in manager.active_projects()
    try:
        first.index()
    except RuntimeError:
        pass
    else:
        raise AssertionError("evicted session remained usable")


def test_session_manager_rejects_incompatible_reopen(tmp_path: Path):
    root = tmp_path / "p"
    root.mkdir()
    (root / "x.py").write_text("x=1\n", encoding="utf-8")
    manager = SemanticSessionManager()
    registry = SemanticBackendRegistry()
    manager.open(root, registry=registry, read_only=True)
    with pytest.raises(ValueError, match="write authority"):
        manager.open(root, registry=registry, read_only=False)
    with pytest.raises(ValueError, match="resource limits"):
        manager.open(root, registry=registry, limits=SemanticCodeLimits(max_files=10))
    with pytest.raises(ValueError, match="backend registry"):
        manager.open(root, registry=SemanticBackendRegistry())
