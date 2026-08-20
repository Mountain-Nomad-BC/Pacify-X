from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.global_skill_isolation import (
    isolate_global_skills,
    preview_global_skill_isolation,
    restore_global_skills,
)
from runtime.native_skills import inventory_tree, tree_hash


def _source(root: Path) -> Path:
    source = root / "home" / ".agents" / "skills"
    body = source / "microsoft-foundry" / "SKILL.md"
    body.parent.mkdir(parents=True)
    body.write_text("---\nname: microsoft-foundry\n---\n", encoding="utf-8")
    return source


def test_global_skill_isolation_preview_is_read_only(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    relocation = tmp_path / "home" / ".px_canonical_skills"

    preview = preview_global_skill_isolation(
        project, source=source, relocation_root=relocation
    )

    assert preview["valid"] is True
    assert preview["snapshots_match"] is True
    assert preview["approval_required"] is True
    assert source.is_dir()
    assert not (project / ".px/global-skill-isolation").exists()
    assert not relocation.exists()


def test_global_skill_isolation_recovers_and_restores_exact_tree(tmp_path: Path) -> None:
    source = _source(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    relocation = tmp_path / "home" / ".px_canonical_skills"
    original_hash = tree_hash(inventory_tree(source))

    with pytest.raises(RuntimeError, match="injected isolation stop"):
        isolate_global_skills(
            project,
            source=source,
            relocation_root=relocation,
            apply=True,
            _stop_after_state="source-relocated",
        )
    journal_path = project / ".px/global-skill-isolation/journal.json"
    interrupted = json.loads(journal_path.read_text(encoding="utf-8"))
    assert interrupted["state"] == "source-relocated"
    assert not source.exists()

    completed = isolate_global_skills(
        project, source=source, relocation_root=relocation, apply=True
    )
    assert completed["valid"] is True
    assert source.is_dir() and not any(source.iterdir())
    destination = Path(completed["journal"]["destination"])
    backup = Path(completed["journal"]["permanent_backup"])
    assert tree_hash(inventory_tree(destination)) == original_hash
    assert tree_hash(inventory_tree(backup)) == original_hash

    preview = restore_global_skills(project)
    assert preview["apply"] is False
    restored = restore_global_skills(project, apply=True)
    assert restored["restored"] is True
    assert tree_hash(inventory_tree(source)) == original_hash
    assert backup.is_dir()
