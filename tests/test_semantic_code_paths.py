from __future__ import annotations

from pathlib import Path
import os
import pytest

from runtime.semantic_code_paths import SemanticPathError, normalize_relative_path, resolve_project_path


def test_path_normalization_rejects_escape_and_absolute(tmp_path: Path):
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert normalize_relative_path("a.py") == "a.py"
    with pytest.raises(SemanticPathError):
        normalize_relative_path("../a.py")
    with pytest.raises(SemanticPathError):
        normalize_relative_path("/tmp/a.py")


def test_resolve_rejects_symlink_escape_when_supported(tmp_path: Path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir(exist_ok=True)
    target = outside / "outside.py"
    target.write_text("x=1\n", encoding="utf-8")
    link = tmp_path / "escape.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlink unavailable")
    with pytest.raises(SemanticPathError):
        resolve_project_path(tmp_path, "escape.py", require_file=True)
