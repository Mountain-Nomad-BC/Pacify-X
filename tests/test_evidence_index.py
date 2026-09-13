from __future__ import annotations

import json
import hashlib
from pathlib import Path
import zipfile

import runtime.evidence_index as evidence_index
from runtime.evidence_index import build_index, publish_index
from runtime.engine_identity import build_engine_identity, write_engine_identity
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
    from runtime.test_profiles import (
        section_receipt, group_receipt, write_section_receipt, write_group_receipt,
    )
    execution = {"valid": True, "exit_code": 0, "timed_out": False,
                 "duration_seconds": 0.1, "stdout": "1 passed\n", "stderr": ""}
    write_section_receipt(root, section_receipt(section, execution))
    write_group_receipt(root, group_receipt(group, execution))


def test_engine_identity_excludes_test_group_topology(tmp_path) -> None:
    (tmp_path / "registry").mkdir()
    topology = tmp_path / "registry/test_group_index.json"
    topology.write_text('{"revision":1}\n', encoding="utf-8")
    before = build_engine_identity(tmp_path)
    topology.write_text('{"revision":2}\n', encoding="utf-8")
    after = build_engine_identity(tmp_path)
    assert before == after


def test_engine_identity_excludes_generated_world_state_projection(tmp_path) -> None:
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/engine.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "registry").mkdir()
    world_state = tmp_path / "registry/px_world_state.json"
    world_state.write_text('{"source_revision":"first"}\n', encoding="utf-8")
    before = build_engine_identity(tmp_path)
    world_state.write_text('{"source_revision":"second"}\n', encoding="utf-8")
    after_projection = build_engine_identity(tmp_path)
    (tmp_path / "runtime/engine.py").write_text("value = 2\n", encoding="utf-8")
    after_source = build_engine_identity(tmp_path)
    assert before == after_projection
    assert before != after_source


def test_engine_identity_excludes_mutable_operational_ledger_controls(
    tmp_path,
) -> None:
    (tmp_path / "runtime").mkdir()
    source = tmp_path / "runtime/engine.py"
    source.write_text("value = 1\n", encoding="utf-8")
    registry = tmp_path / "registry"
    registry.mkdir()
    lock = registry / ".operational-gap-ledger.lock"
    head = registry / "operational_gap_ledger.head.json"
    recovery = (
        registry
        / ".lock-recovery-receipts"
        / ".operational-gap-ledger.lock"
        / "receipt.json"
    )
    recovery.parent.mkdir(parents=True)
    lock.write_text('{"owner":1}\n', encoding="utf-8")
    head.write_text('{"sequence":1}\n', encoding="utf-8")
    recovery.write_text('{"recovered":1}\n', encoding="utf-8")
    before = build_engine_identity(tmp_path)

    lock.write_text('{"owner":2}\n', encoding="utf-8")
    head.write_text('{"sequence":2}\n', encoding="utf-8")
    recovery.write_text('{"recovered":2}\n', encoding="utf-8")
    after_controls = build_engine_identity(tmp_path)
    source.write_text("value = 2\n", encoding="utf-8")
    after_source = build_engine_identity(tmp_path)

    assert before == after_controls
    assert before != after_source


def test_engine_identity_excludes_external_runtime_custody(tmp_path) -> None:
    (tmp_path / "runtime").mkdir()
    source = tmp_path / "runtime/engine.py"
    source.write_text("value = 1\n", encoding="utf-8")
    before = build_engine_identity(tmp_path)
    (tmp_path / ".tmp/session").mkdir(parents=True)
    (tmp_path / ".tmp/session/state.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "projects/pacify-x").mkdir(parents=True)
    (tmp_path / "projects/pacify-x/runtime.py").write_text(
        "value = 2\n", encoding="utf-8"
    )
    after = build_engine_identity(tmp_path)
    assert before == after


def test_test_group_index_bytes_do_not_depend_on_incremental_cache_state(
    tmp_path,
) -> None:
    _fixture(tmp_path)
    first = build_test_group_index(tmp_path)
    (tmp_path / "registry/test_group_index.json").write_text(
        json.dumps(first), encoding="utf-8"
    )
    second = build_test_group_index(tmp_path)
    assert second == first
    assert first["verified_file_count"] == len(first["files"])


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


def test_invalid_current_index_is_returned_without_publication(
    tmp_path, monkeypatch
) -> None:
    invalid = {"namespace": "invalid-fixture", "valid": False}
    monkeypatch.setattr(evidence_index, "build_index", lambda *_args, **_kwargs: invalid)
    registry, namespace, value = publish_index(tmp_path)
    assert value is invalid
    assert registry == tmp_path / "registry/current_evidence_index.json"
    assert namespace == tmp_path / "evidence/releases/invalid-fixture/EVIDENCE_INDEX.json"
    assert not registry.exists()
    assert not namespace.exists()


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
