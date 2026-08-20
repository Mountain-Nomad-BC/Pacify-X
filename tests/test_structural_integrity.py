from __future__ import annotations

import json
import ast
import hashlib
import importlib.util
from pathlib import Path
import shutil
import sys
import tempfile

from runtime.structural_integrity import (
    _exclude_structural_path,
    _stable_ast,
    audit_structural_integrity,
)


ROOT = Path(__file__).parents[1]


def test_completed_wal_images_are_inactive_but_pending_wal_remains_auditable() -> None:
    assert _exclude_structural_path(
        ".engineering-bootstrap/doctor/wal/committed/tx/after/0000.json"
    )
    assert not _exclude_structural_path(
        ".engineering-bootstrap/doctor/wal/pending/tx/after/0000.json"
    )


def test_logic_review_identity_is_interpreter_neutral() -> None:
    node = ast.parse(
        "def sample(x: int = 1):\n"
        "    y = x + 2\n"
        "    if y > 2:\n"
        "        return y\n"
        "    return 0\n"
    ).body[0]
    digest = hashlib.sha256(
        repr(_stable_ast(node, function_root=True)).encode()
    ).hexdigest()
    assert digest == "448822aedd5e47d05dfb53a36144e696ef8a25dda4aac8442734064b71a93456"


def test_ellipsis_finding_identity_is_source_derived_across_python_versions(
    tmp_path,
) -> None:
    scanner = (
        ROOT
        / ".px/skills/audit-incomplete-implementations/scripts/audit_incomplete.py"
    )
    spec = importlib.util.spec_from_file_location("_portable_incomplete_audit", scanner)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    source = "class Surface:\n    def run(self, value: int) -> str: ...\n"
    (tmp_path / "sample.py").write_text(source, encoding="utf-8")
    result = module.audit(tmp_path)
    finding = next(
        item for item in result["findings"] if item["rule"] == "python-ellipsis-body"
    )
    semantic = "def run(self, value: int) -> str: ..."
    expected = hashlib.sha256(
        f"sample.py:python-ellipsis-body:{semantic}".encode()
    ).hexdigest()[:20]
    assert finding["id"] == expected


def _clone() -> Path:
    directory = Path(tempfile.mkdtemp())
    target = directory / "framework"
    shutil.copytree(
        ROOT,
        target,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv*",
            ".vscode-test",
            "Python",
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".ruff_cache",
            "quarantine",
            "operation-bus",
            "preserved-extension-installations",
        ),
    )
    return target


def test_structural_integrity_has_closed_denominators() -> None:
    result = audit_structural_integrity(ROOT)
    non_document_errors = [
        item
        for item in result["errors"]
        if not item.startswith("documentation: stale deployment claim")
    ]
    assert not non_document_errors, non_document_errors


def test_hash_ledger_head_and_anchor_are_a_reviewed_exact_projection() -> None:
    result = audit_structural_integrity(ROOT)
    groups = [
        item
        for item in result["duplicate_file_groups"]
        if item["classification"] == "ledger-authority-head-anchor"
    ]
    assert len(groups) == 1
    assert any(path.endswith("/head.json") for path in groups[0]["paths"])
    assert any("/anchors/" in path for path in groups[0]["paths"])
    assert result["category_count"] == 15
    assert result["reachability_records"] > 100
    assert result["required_audit_item_count"] == 21
    assert all(item["passed"] for item in result["audit_items"].values())


def test_structural_audit_never_writes_dynamic_loader_bytecode() -> None:
    root = _clone()
    cache = root / ".px/skills/audit-incomplete-implementations/scripts/__pycache__"
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = False
    try:
        audit_structural_integrity(root)
    finally:
        sys.dont_write_bytecode = previous
    assert not cache.exists()


def test_orphan_registry_file_fails_closed() -> None:
    root = _clone()
    (root / "registry/orphan.json").write_text("{}\n", encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["reachability"]["passed"]


def test_defined_but_unbound_orchestration_fails_closed() -> None:
    root = _clone()
    (root / "orchestration/workflows/unbound.yaml").write_text(
        "id: unbound\n", encoding="utf-8"
    )
    result = audit_structural_integrity(root)
    assert not result["categories"]["orchestrations"]["passed"]


def test_undiscoverable_skill_fails_closed() -> None:
    root = _clone()
    index_path = root / "registry/semantic_capability_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["records"] = index["records"][1:]
    index_path.write_text(json.dumps(index), encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["skills"]["passed"]


def test_unowned_yaml_fails_closed() -> None:
    root = _clone()
    (root / "bootstrap/orphan.yaml").write_text("id: orphan\n", encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["reachability"]["passed"]


def test_dead_contract_fails_closed() -> None:
    root = _clone()
    ownership_path = root / "registry/contract_ownership.json"
    ownership = json.loads(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["packaged"] = False
    ownership_path.write_text(json.dumps(ownership), encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["contracts"]["passed"]


def test_stale_release_pinned_execution_plan_fails_closed() -> None:
    root = _clone()
    path = root / "EXECUTION_PLAN_PUNCH_CARDS_AND_ACCEPTANCE.md"
    path.write_text("# Plan\n\n`REL-006` is complete.\n", encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["documentation"]["passed"]


def test_project_management_checkpoint_drift_fails_closed() -> None:
    root = _clone()
    path = root / ".engineering-bootstrap/project-management/state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["checkpoint"]["next_safe_action"] = "different"
    path.write_text(json.dumps(state), encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["documentation"]["passed"]


def test_declared_generated_duplicates_regenerate_cleanly() -> None:
    result = audit_structural_integrity(ROOT)
    declared = [
        item
        for item in result["duplicate_file_groups"]
        if item["classification"] != "unreviewed"
    ]
    assert all(item.get("equivalence_rule") for item in declared)
    classifications = {item["classification"] for item in declared}
    assert "native-skill-manifest-aliases" in classifications
    assert "native-skill-surface-scaffolds" in classifications
    assert "native-skill-policy-projections" in classifications


def test_undeclared_duplicate_group_fails_audit() -> None:
    root = _clone()
    (root / "docs/a.md").write_text("duplicate", encoding="utf-8")
    (root / "docs/b.md").write_text("duplicate", encoding="utf-8")
    result = audit_structural_integrity(root)
    assert not result["categories"]["duplicate_files"]["passed"]


def test_portable_hash_helpers_have_behavioral_parity() -> None:
    result = audit_structural_integrity(ROOT)
    helpers = [
        item
        for item in result["duplicate_logic_groups"]
        if item["classification"] == "portable-skill-hash-helpers"
    ]
    assert all(item["equivalence_rule"] == "behavioral parity" for item in helpers)
