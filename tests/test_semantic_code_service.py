from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from runtime.semantic_code_service import SemanticCodeService


FIXTURE = Path(__file__).parent / "fixtures" / "semantic_code" / "python_project"


def test_service_exposes_client_neutral_reads_and_receipts(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    service = SemanticCodeService()
    summary = service.project_summary(root)
    assert summary["symbol_count"] > 0
    assert summary["receipt"]["receipt_sha256"]
    result = service.find_symbols(root, "Device", substring=True)
    assert any(item["name"] == "Device" for item in result["matches"])
    assert result["receipt"]["receipt_sha256"]
    overview = service.symbol_overview(root, "pkg/models.py")
    assert overview["receipt"]["receipt_sha256"]
    symbol_id = result["matches"][0]["symbol_id"]
    references = service.find_references(root, symbol_id)
    assert references["receipt"]["receipt_sha256"]
    diagnostics = service.diagnostics(root, relative_path="broken.py")
    assert diagnostics["receipt"]["receipt_sha256"]


def test_service_write_requires_explicit_write_enabled_instance(tmp_path: Path):
    root = tmp_path / "p"
    shutil.copytree(FIXTURE, root)
    service = SemanticCodeService()
    plan = service.plan_replace_symbol(
        root,
        pattern="pkg.models.helper",
        relative_path="pkg/models.py",
        replacement='def helper(value: str) -> str:\n    return value\n',
    )
    preview = service.apply_plan(root, plan, write=False)
    assert not preview.written
    with pytest.raises(PermissionError):
        service.apply_plan(root, plan, write=True)

    writer = SemanticCodeService(allow_writes=True)
    writer.project_summary(root)
    plan = writer.plan_replace_symbol(
        root,
        pattern="pkg.models.helper",
        relative_path="pkg/models.py",
        replacement='def helper(value: str) -> str:\n    return value\n',
    )
    assert writer.apply_plan(root, plan, write=True).written
