from __future__ import annotations

import json
import hashlib
from pathlib import Path
import zipfile

from runtime.evidence_index import build_index, publish_index
from runtime.engine_identity import write_engine_identity
from runtime.test_profiles import (
    build_test_group_index,
    resolve_test_group,
    resolve_test_section,
)


def _fixture(root: Path) -> None:
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "1.2.3.dev0"\n', encoding="utf-8"
    )
    (root / "extension").mkdir()
    (root / "extension/package.json").write_text(
        json.dumps({"version": "2.0.0"}), encoding="utf-8"
    )
    (root / "tests").mkdir()
    (root / "tests/test_gate.py").write_text(
        "def test_gate(): assert True\n", encoding="utf-8"
    )
    registry = root / "registry"
    registry.mkdir()
    config = {
        "environment": {},
        "sections": {
            "gate": {
                "source_patterns": ["tests/test_gate.py"],
                "command": ["python", "-m", "pytest", "tests/test_gate.py"],
                "timeout_seconds": 30,
            }
        },
        "groups": {
            "all": {
                "include_patterns": ["tests/test_*.py"],
                "parallel_safe": True,
                "timeout_seconds": 30,
            }
        },
        "certification": {
            "required_sections": ["gate"],
            "required_groups": ["all"],
        },
        "profiles": {},
    }
    (registry / "test_profiles.json").write_text(json.dumps(config), encoding="utf-8")
    (registry / "test_group_index.json").write_text(
        json.dumps(build_test_group_index(root)), encoding="utf-8"
    )
    section = resolve_test_section(root, "gate")
    group = resolve_test_group(root, "all")
    section_path = root / ".engineering-bootstrap/test-evidence/sections/gate.json"
    section_path.parent.mkdir(parents=True)
    section_path.write_text(
        json.dumps(
            {
                "schema_version": "px.test-section-receipt/1.0",
                "section": "gate",
                "input_sha256": section["input_sha256"],
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    group_path = root / ".engineering-bootstrap/test-evidence/groups/all.json"
    group_path.parent.mkdir(parents=True)
    group_path.write_text(
        json.dumps(
            {
                "schema_version": "px.test-group-receipt/1.0",
                "group": "all",
                "input_sha256": group["input_sha256"],
                "passed": True,
            }
        ),
        encoding="utf-8",
    )


def _artifact(path: Path, version: str = "2.0.0") -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("extension/package.json", json.dumps({"version": version}))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path, manifest = write_engine_identity(path.parent)
    engine_identity = {
        "manifest_path": "registry/engine_identity.json",
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "tree_sha256": manifest["tree_sha256"],
        "file_total": manifest["file_total"],
    }
    evidence = path.parent / "extension/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    for platform, name in (("win32", "installed-vsix-smoke.json"), ("linux", "installed-vsix-smoke-linux.json")):
        (evidence / name).write_text(json.dumps({
            "schema_version": "px.installed-vsix-certification/1.1",
            "platform": platform,
            "artifact": {"sha256_before": digest, "sha256_after": digest, "unchanged": True},
            "engine_connected": True,
            "engine_identity": engine_identity,
            "process_lifecycle": {"process_tree_closed_verified": True},
            "host": {
                "live_dashboard": {
                    "source": {"version": "1.2.3.dev0", "mode": "canonical-dashboard-api"},
                    "counts": {"effects": 1},
                    "canonical_counts_match": True,
                },
                "listener_health": {"coverage_tier": "B", "coverage_complete": False, "limitations": ["test:unsupported"]},
                "limitations": ["host-dependent"]
            },
        }), encoding="utf-8")
    return path


def test_exact_version_evidence_requires_current_receipts_and_artifact(
    tmp_path,
) -> None:
    _fixture(tmp_path)
    assert build_index(tmp_path)["valid"] is False
    artifact = _artifact(tmp_path / "pacify-x.vsix")
    registry, namespace, value = publish_index(tmp_path, artifacts=[artifact])
    assert value["valid"] is True
    assert value["namespace"] == "python-1.2.3.dev0__vscode-2.0.0"
    assert value["required_receipt_count"] == 2
    assert value["current_required_receipt_count"] == 2
    assert value["blocking_reasons"] == []
    assert any("coverage tier B" in item for item in value["limitations"])
    assert (
        len(next(row for row in value["records"] if row["kind"] == "vsix")["sha256"])
        == 64
    )
    assert registry.is_file() and namespace.is_file()


def test_stale_receipt_and_wrong_artifact_version_fail_closed(tmp_path) -> None:
    _fixture(tmp_path)
    (tmp_path / "tests/test_gate.py").write_text(
        "def test_gate(): assert False\n", encoding="utf-8"
    )
    artifact = _artifact(tmp_path / "pacify-x.vsix", "1.0.0")
    result = build_index(tmp_path, artifacts=[artifact])
    assert result["valid"] is False
    assert any("not current" in value for value in result["blocking_reasons"])
    assert any("version mismatch" in value for value in result["blocking_reasons"])


def test_engine_or_cross_platform_semantic_mismatch_fails_closed(tmp_path) -> None:
    _fixture(tmp_path)
    artifact = _artifact(tmp_path / "pacify-x.vsix")
    linux = tmp_path / "extension/evidence/installed-vsix-smoke-linux.json"
    value = json.loads(linux.read_text(encoding="utf-8"))
    value["host"]["live_dashboard"]["counts"]["effects"] = 2
    linux.write_text(json.dumps(value), encoding="utf-8")
    result = build_index(tmp_path, artifacts=[artifact])
    assert result["valid"] is False
    assert any("semantics differ" in item for item in result["blocking_reasons"])

    value["host"]["live_dashboard"]["counts"]["effects"] = 1
    value["engine_identity"]["tree_sha256"] = "0" * 64
    linux.write_text(json.dumps(value), encoding="utf-8")
    result = build_index(tmp_path, artifacts=[artifact])
    assert result["valid"] is False
    assert any("engine manifest" in item for item in result["blocking_reasons"])
