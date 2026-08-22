from __future__ import annotations

from dataclasses import replace
import json

from runtime.native_skills import build_skill_index
from runtime.skill_studio import SkillStudio
from runtime.studio_catalog_status import project
from runtime.studio_models import SkillPackage


def _source(root, name: str, body: str = "# Demo\n", version: str = "1.0.0"):
    path = root / name
    for child in ("agents", "contracts", "tests", "resources"):
        (path / child).mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(body, encoding="utf-8")
    native_manifest = {
        "schema_version": "px.native-skill-package/1.0",
        "id": "demo",
        "version": version,
        "domain": "px-standard",
    }
    manifest_text = json.dumps(native_manifest, indent=2) + "\n"
    (path / "capability.json").write_text(manifest_text, encoding="utf-8")
    (path / "skill.yaml").write_text(manifest_text, encoding="utf-8")
    (path / "agents/openai.yaml").write_text(
        "interface:\n  display_name: Demo\n  short_description: Demo skill\n",
        encoding="utf-8",
    )
    (path / "contracts/manifest.json").write_text(
        json.dumps(
            {"schema_version": "px.skill-contract-links/1.0", "contracts": []}
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "resources/index.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-resources/1.0",
                "resources": [
                    "agents/openai.yaml",
                    "capability.json",
                    "contracts/manifest.json",
                    "SKILL.md",
                    "skill.yaml",
                    "tests/validation.json",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "tests/validation.json").write_text(
        json.dumps(
            {
                "schema_version": "px.skill-test/1.1",
                "cases": [
                    {
                        "name": "required",
                        "assertion": {
                            "kind": "required-files",
                            "paths": ["SKILL.md", "capability.json", "skill.yaml"],
                        },
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _package(version: str = "1.0.0") -> SkillPackage:
    return SkillPackage(
        "skill:demo",
        version,
        "owner",
        ("demo task",),
        ("unrelated task",),
        ("read",),
        ("read",),
        ("resources/index.json",),
        ("contracts/manifest.json",),
        ("tests/validation.json",),
        {"source": "local", "license": "Apache-2.0"},
    )


def _scaffold(root):
    (root / "registry/skill_packages").mkdir(parents=True)
    (root / "registry/skill_catalog.toml").write_text(
        'schema_version = "1.0"\n', encoding="utf-8"
    )
    (root / ".px").mkdir()
    (root / ".px/skill-index.json").write_text(
        json.dumps(build_skill_index([])), encoding="utf-8"
    )


def _promote(studio: SkillStudio, root, package: SkillPackage, name: str, body: str):
    selected = _source(root, name, body, version=package.version)
    token = studio.admit_source(selected, approved_by="human:owner")
    studio.stage_draft(package, selected, source_token=token)
    assert studio.validate(package)["passed"] is True
    assert studio.admit(package, approved=True, approver="human:owner")["decision"] == "admitted"
    return studio.promote(package, approved=True)


def _revision_row(root, version: str):
    result = project(root, "skills")
    key = next(key for key in result["records"] if key.endswith(f"/revisions/{version}/package-record.json"))
    return result["records"][key]


def test_catalog_status_authenticates_framed_promotion_and_projection_images(tmp_path):
    _scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    _promote(studio, tmp_path, _package(), "first", "# First\n")

    row = _revision_row(tmp_path, "1.0.0")
    assert row["status"] == "promoted"
    assert row["authenticated"] is True
    assert row["rollback_available"] is False
    assert row["lifecycle_transaction_relative"].endswith("manifest.json") is False


def test_catalog_status_authenticates_rollback_and_disables_repeat_rollback(tmp_path):
    _scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    _promote(studio, tmp_path, _package(), "first", "# First\n")
    second = replace(_package(), version="1.1.0")
    _promote(studio, tmp_path, second, "second", "# Second\n")
    before = _revision_row(tmp_path, "1.1.0")
    assert before["status"] == "promoted"
    assert before["rollback_available"] is True
    promotion_receipt = next(
        (tmp_path / ".engineering-bootstrap/studios/skills").glob(
            "*/revisions/1.1.0/promotion-receipt.json"
        )
    )
    studio.rollback(promotion_receipt, approved=True, approver="human:owner")

    after = _revision_row(tmp_path, "1.1.0")
    assert after["status"] == "rolled-back"
    assert after["authenticated"] is True
    assert after["rollback_available"] is False


def test_catalog_status_refuses_current_projection_drift(tmp_path):
    _scaffold(tmp_path)
    studio = SkillStudio(tmp_path)
    _promote(studio, tmp_path, _package(), "first", "# First\n")
    index_path = tmp_path / ".px/skill-index.json"
    index_path.write_text(index_path.read_text(encoding="utf-8") + " ", encoding="utf-8")

    row = _revision_row(tmp_path, "1.0.0")
    assert row["status"] != "promoted"
    assert row["authenticated"] is True  # admission remains authenticated
    assert "promotion:PermissionError" in row["reason"]
    assert "rollback_available" not in row
