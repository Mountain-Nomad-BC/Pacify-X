from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.native_skills import build_skill_index, inventory_tree, tree_hash
from scripts.migrate_px_skills import migrate, refresh_eligibility


def _scaffold(root: Path) -> Path:
    skill = root / ".agents/skills/demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: demo\ndescription: migration demo\n---\n", encoding="utf-8"
    )
    (root / "registry").mkdir()
    (root / "registry/skill_catalog.toml").write_text(
        'schema_version = "1.0"\n'
        '[[skills]]\n'
        'id = "demo"\n'
        'version = "1.0.0"\n'
        'status = "active"\n'
        'body = ".agents/skills/demo/SKILL.md"\n'
        'tags = ["demo"]\n',
        encoding="utf-8",
    )
    (root / "registry/ms_enterprise_catalog.json").write_text(
        json.dumps({"skills": []}), encoding="utf-8"
    )
    (root / "pyproject.toml").write_text(
        '[tool.setuptools.data-files]\n'
        '# BEGIN GENERATED OPERATIONAL SKILL DATA FILES\n'
        '# END GENERATED OPERATIONAL SKILL DATA FILES\n',
        encoding="utf-8",
    )
    user = root / "user-skills"
    (user / "personal").mkdir(parents=True)
    (user / "personal/SKILL.md").write_text(
        "---\nname: personal\ndescription: preserved\n---\n", encoding="utf-8"
    )
    return user


def test_first_initialization_recovers_after_relocation_and_then_stays_incremental(
    tmp_path: Path,
) -> None:
    user = _scaffold(tmp_path)
    with pytest.raises(RuntimeError, match="injected migration stop"):
        migrate(tmp_path, user, _stop_after_state="source-relocated")
    journal_path = tmp_path / ".px/skill-first-initialization/journal.json"
    interrupted = json.loads(journal_path.read_text(encoding="utf-8"))
    assert interrupted["state"] == "source-relocated"
    assert not (tmp_path / ".agents/skills").exists()

    result = migrate(tmp_path, user)
    assert result["state"] == "committed"
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    first = json.loads(
        (tmp_path / ".px/skill-first-initialization/workspace-snapshot-a.json").read_text(
            encoding="utf-8"
        )
    )
    second = json.loads(
        (tmp_path / ".px/skill-first-initialization/workspace-snapshot-b.json").read_text(
            encoding="utf-8"
        )
    )
    assert first["files"] == second["files"]
    assert journal["pre_move_tree_sha256"] == first["tree_sha256"]
    original = tmp_path / ".px/preserved-skills/initial/workspace-original"
    backup = tmp_path / ".px/preserved-skills/initial/workspace-verified-copy"
    assert tree_hash(inventory_tree(original)) == tree_hash(inventory_tree(backup))
    assert (tmp_path / ".agents/skills").is_dir()

    facade = tmp_path / ".agents/skills/px-query-skills"
    facade.mkdir()
    (facade / "SKILL.md").write_text("# query\n", encoding="utf-8")
    second_run = migrate(tmp_path, user)
    assert second_run["mode"] == "incremental-only"
    assert (facade / "SKILL.md").read_text(encoding="utf-8") == "# query\n"


def test_first_initialization_refuses_a_tree_that_changes_between_snapshots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _scaffold(tmp_path)
    import scripts.migrate_px_skills as migration

    original = migration._snapshot_record
    calls = 0

    def changing_snapshot(source: Path, snapshot_id: str):
        nonlocal calls
        result = original(source, snapshot_id)
        calls += 1
        if calls == 1:
            (source / "demo/changed.txt").write_text("drift\n", encoding="utf-8")
        return result

    monkeypatch.setattr(migration, "_snapshot_record", changing_snapshot)
    with pytest.raises(RuntimeError, match="changed between required snapshots"):
        migration.migrate(tmp_path, user)
    assert not (tmp_path / ".px/preserved-skills/initial/workspace-original").exists()


def test_eligibility_refresh_commits_manifests_index_and_projection_together(
    tmp_path: Path,
) -> None:
    user = _scaffold(tmp_path)
    migrate(tmp_path, user)
    index_path = tmp_path / ".px/skill-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"][0]["default_eligible"] = False
    index_path.write_text(
        json.dumps(build_skill_index(index["records"], template=index)),
        encoding="utf-8",
    )
    manifest_path = tmp_path / ".px/skills/demo/capability.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["isolation"]["default_eligible"] = False
    rendered = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_path.write_text(rendered, encoding="utf-8")
    (manifest_path.parent / "skill.yaml").write_text(rendered, encoding="utf-8")

    result = refresh_eligibility(tmp_path)
    assert result["changed"] == 1
    transaction = next(
        (tmp_path / ".px/skill-publication-transactions").glob(
            "refresh-eligibility-*/manifest.json"
        )
    )
    assert json.loads(transaction.read_text(encoding="utf-8"))["state"] == "committed"
    refreshed = json.loads(index_path.read_text(encoding="utf-8"))
    assert refreshed["records"][0]["default_eligible"] is True
    assert refreshed["counts"]["px-standard"] == 1
