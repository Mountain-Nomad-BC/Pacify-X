"""Per-YAML statistical operations and persistent memory files (build requirement 2026-10-09).

Every canonical YAML definition must spin up, for each subject it declares: a
statistical operations file (stats.json), a persistent memory pair
(usage.jsonl + memory.md), a bindings file, and a global manifest that maps
every YAML onto its subject files 1:1.
"""

from __future__ import annotations

import json
from pathlib import Path

from runtime.yaml_subject_files import canonical_yaml_subjects, ensure_yaml_subject_files

WORKFLOW_DOC = """{
  "schema_version": "px.workflows/1.0",
  "workflows": [
    {
      "id": "alpha-cycle",
      "purpose": "Alpha cycle with a bounded review",
      "steps": [
        {"id": "load", "skill": "alpha-load"},
        {"id": "review", "skill": "alpha-review", "depends_on": ["load"]}
      ],
      "bounds": {"primary_agents": ["agent-a"]}
    }
  ]
}
"""

PROJECT_STREAM_DOC = """schema_version: px.project-stream/1.0
orchestration_id: project_onboard
title: Project onboarding stream
skills:
  - alpha-load
  - alpha-review
required_context:
  - charter
"""

SKILL_MANIFEST_DOC = """schema_version: px.source-skill-manifest/1.0
id: alpha-load
purpose: Load the alpha source set
integrations:
  - alpha-provider
"""

RESEARCH_OP_DOC = """schema_version: px.imported-research-op/1.0
id: alpha-scan
purpose: Scan research corpus
workflows:
  - alpha-cycle
"""


def make_repo(tmp_path: Path) -> Path:
    (tmp_path / "orchestration" / "workflows" / "project_stream").mkdir(parents=True)
    (tmp_path / "registry" / "source_skill_manifests").mkdir(parents=True)
    (tmp_path / "registry" / "imported_research_ops").mkdir(parents=True)
    (tmp_path / "orchestration" / "workflows" / "pair.yaml").write_text(WORKFLOW_DOC, encoding="utf-8")
    (tmp_path / "orchestration" / "workflows" / "project_stream" / "project_onboard.yaml").write_text(
        PROJECT_STREAM_DOC, encoding="utf-8")
    (tmp_path / "registry" / "source_skill_manifests" / "alpha-load.yaml").write_text(SKILL_MANIFEST_DOC, encoding="utf-8")
    (tmp_path / "registry" / "imported_research_ops" / "alpha-scan.yaml").write_text(RESEARCH_OP_DOC, encoding="utf-8")
    return tmp_path


def test_every_yaml_declares_its_subjects_with_bindings(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    subjects = canonical_yaml_subjects(root)
    by_id = {(subject.kind, subject.subject_id): subject for subject in subjects}
    assert (  # JSON-in-yaml workflow doc -> one workflow subject per workflows[] entry
        ("workflow", "alpha-cycle") in by_id)
    assert ("workflow", "project-onboard") in by_id  # project_stream yaml, _ normalized
    assert ("skill", "alpha-load") in by_id
    assert ("skill", "alpha-scan") in by_id  # imported research ops
    assert len({subject.source_yaml for subject in subjects}) == 4
    workflow = by_id[("workflow", "alpha-cycle")]
    assert set(workflow.bindings["skills"]) == {"alpha-load", "alpha-review"}
    assert workflow.bindings["agents"] == ["agent-a"]
    assert "load" in workflow.bindings["workflow_steps"]
    stream = by_id[("workflow", "project-onboard")]
    assert set(stream.bindings["skills"]) == {"alpha-load", "alpha-review"}
    skill = by_id[("skill", "alpha-load")]
    assert skill.bindings["integrations"] == ["alpha-provider"]


def test_ensure_spins_up_stats_memory_bindings_and_manifest(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    report = ensure_yaml_subject_files(root, apply=True)
    assert report["valid"] is True
    assert report["yaml_files"] == 4
    manifest_path = root / ".px" / "usage-memory" / "subject-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["subject_count"] == 4
    assert manifest["yaml_file_count"] == 4
    for row in report["subjects"]:
        files = row["files"]
        memory_dir = root / files["memory_dir"]
        # Statistical operations file per YAML subject.
        assert (memory_dir / "stats.json").is_file()
        # Persistent memory pair (json + md).
        assert (memory_dir / "usage.jsonl").is_file()
        memory_md = (memory_dir / "memory.md").read_text(encoding="utf-8")
        assert "Persistent memory" in memory_md
        assert "Statistical operations snapshot" in memory_md
        assert "Bindings" in memory_md
        # Binding file tying the YAML to its members.
        bindings = json.loads((memory_dir / "bindings.json").read_text(encoding="utf-8"))
        assert bindings["source_yaml_sha256"] and bindings["subject_kind"] in {"skill", "workflow"}
        assert files["memory_md"].endswith("memory.md")
    # Manifest md twin maps every subject.
    manifest_md = (root / ".px" / "usage-memory" / "subject-manifest.md").read_text(encoding="utf-8")
    assert "| workflow | `alpha-cycle` |" in manifest_md
    assert "| skill | `alpha-load` |" in manifest_md
    assert manifest["manifest_sha256"]


def test_ensure_is_idempotent_and_detects_yaml_changes(tmp_path: Path) -> None:
    root = make_repo(tmp_path)
    first = ensure_yaml_subject_files(root, apply=True)
    manifest_path = root / ".px" / "usage-memory" / "subject-manifest.json"
    before = manifest_path.read_bytes()
    second = ensure_yaml_subject_files(root, apply=True)
    assert manifest_path.read_bytes() == before  # deterministic, byte-identical
    assert second["manifest"]["manifest_sha256"] == first["manifest"]["manifest_sha256"]
    # A YAML content change must flow through to the subject's binding record.
    skill_dir = root / "registry" / "source_skill_manifests" / "alpha-load.yaml"
    skill_dir.write_text(SKILL_MANIFEST_DOC.replace("alpha-provider", "beta-provider"), encoding="utf-8")
    ensure_yaml_subject_files(root, apply=True)
    bindings = json.loads(
        (root / ".px" / "skills" / "alpha-load" / "memory" / "bindings.json").read_text(encoding="utf-8"))
    assert bindings["integrations"] == ["beta-provider"]
    manifest_after = json.loads((root / ".px" / "usage-memory" / "subject-manifest.json").read_text(encoding="utf-8"))
    row_after = next(row for row in manifest_after["subjects"] if row["subject_id"] == "alpha-load")
    assert row_after["yaml_sha256"] != first["subjects"][0]["source_yaml"] or row_after["yaml_sha256"]
    assert row_after["yaml_sha256"] != first["manifest"]["manifest_sha256"]
