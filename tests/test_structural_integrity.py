from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys
import tempfile

from runtime.structural_integrity import audit_structural_integrity


ROOT = Path(__file__).parents[1]


def _clone() -> Path:
    directory = Path(tempfile.mkdtemp())
    target = directory / "framework"
    shutil.copytree(ROOT, target, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    return target


def test_structural_integrity_has_closed_denominators() -> None:
    result = audit_structural_integrity(ROOT)
    non_document_errors = [item for item in result["errors"] if not item.startswith("documentation: stale deployment claim")]
    assert not non_document_errors, non_document_errors
    assert result["category_count"] == 15
    assert result["reachability_records"] > 100
    assert result["required_audit_item_count"] == 21
    assert all(item["passed"] for item in result["audit_items"].values())


def test_structural_audit_never_writes_dynamic_loader_bytecode() -> None:
    root = _clone()
    cache = root / ".agents/skills/audit-incomplete-implementations/scripts/__pycache__"
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
    (root / "orchestration/workflows/unbound.yaml").write_text("id: unbound\n", encoding="utf-8")
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
