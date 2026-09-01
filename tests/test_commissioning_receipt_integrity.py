from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

import runtime.commissioning as commissioning
from runtime.commissioning import (
    commission,
    project_check,
    rebind_commissioning_framework,
    scaffold_files,
)
from runtime.event_ledger import validate_event_ledger


ROOT = Path(__file__).parents[1]


def _sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _rewrite_receipt(path: Path, mutate) -> None:
    receipt = json.loads(path.read_text())
    receipt.pop("receipt_sha256")
    mutate(receipt)
    receipt["receipt_sha256"] = _sha(receipt)
    path.write_text(json.dumps(receipt), encoding="utf-8")


def test_modified_commissioning_receipt_is_detected() -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        receipt_path = project / ".engineering-bootstrap/commissioning-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        target_name = next(iter(receipt["managed_file_sha256"]))
        target = project / target_name
        target.write_text("forged", encoding="utf-8")

        def mutate(value):
            value["managed_file_sha256"][target_name] = hashlib.sha256(
                target.read_bytes()
            ).hexdigest()
            value["managed_manifest_sha256"] = _sha(value["managed_file_sha256"])
            base = {
                key: item
                for key, item in value.items()
                if key not in {"receipt_payload_sha256", "commissioning_event_sha256"}
            }
            value["receipt_payload_sha256"] = _sha(base)

        _rewrite_receipt(receipt_path, mutate)
        assert not project_check(project, source_root=ROOT)["valid"]


def test_commissioning_receipt_is_bound_to_project() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = root / "first"
        second = root / "second"
        commission(first, "new", apply=True, source_root=ROOT)
        commission(second, "new", apply=True, source_root=ROOT)
        (second / ".engineering-bootstrap/commissioning-receipt.json").write_bytes(
            (first / ".engineering-bootstrap/commissioning-receipt.json").read_bytes()
        )
        result = project_check(second, source_root=ROOT)
        assert not result["valid"] and any(
            "project binding" in error for error in result["errors"]
        )


def test_commissioning_receipt_is_bound_to_framework_release() -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        path = project / ".engineering-bootstrap/commissioning-receipt.json"
        _rewrite_receipt(
            path, lambda value: value["framework_release"].update({"version": "99.0.0"})
        )
        result = project_check(project, source_root=ROOT)
        assert not result["valid"] and any(
            "framework release binding" in error for error in result["errors"]
        )


def test_recommissioning_preserves_prior_receipt() -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        prior = (
            project / ".engineering-bootstrap/commissioning-receipt.json"
        ).read_bytes()
        commission(project, "new", apply=True, source_root=ROOT)
        history = (
            project
            / ".engineering-bootstrap/commissioning-history"
            / f"{hashlib.sha256(prior).hexdigest()}.json"
        )
        assert history.read_bytes() == prior
        assert (
            validate_event_ledger(
                project / ".engineering-bootstrap/commissioning-events"
            )["event_count"]
            == 2
        )


def test_commissioning_manifest_covers_all_managed_files() -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        receipt = json.loads(
            (project / ".engineering-bootstrap/commissioning-receipt.json").read_text()
        )
        expected = scaffold_files("new", project, ROOT)
        mutable = tuple(receipt["mutable_project_management"])
        managed_expected = {
            path.as_posix()
            for path in expected
            if not any(
                path.as_posix() == prefix or path.as_posix().startswith(prefix)
                for prefix in mutable
            )
        }
        assert set(receipt["managed_file_sha256"]) == managed_expected


def test_framework_rebind_preserves_receipt_and_managed_files(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        receipt_path = project / ".engineering-bootstrap/commissioning-receipt.json"
        prior = receipt_path.read_bytes()
        prior_sha256 = hashlib.sha256(prior).hexdigest()
        prior_receipt = json.loads(prior)
        managed = {
            relative: (project / relative).read_bytes()
            for relative in prior_receipt["managed_file_sha256"]
        }
        current = commissioning._framework_binding(ROOT)
        future = {**current, "version": "99.0.0-test"}
        monkeypatch.setattr(commissioning, "_framework_binding", lambda source: future)

        preview = rebind_commissioning_framework(project, source_root=ROOT)
        assert preview["valid"] and preview["changed"]
        assert preview["approval_required"] and not preview["applied"]
        assert receipt_path.read_bytes() == prior

        result = rebind_commissioning_framework(project, source_root=ROOT, apply=True)
        assert result["valid"] and result["applied"] and result["changed"]
        history = (
            project
            / ".engineering-bootstrap/commissioning-history"
            / f"{prior_sha256}.json"
        )
        assert history.read_bytes() == prior
        assert all(
            (project / relative).read_bytes() == content
            for relative, content in managed.items()
        )
        rebound = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert rebound["framework_release"] == future
        assert rebound["commissioning_tool_version"] == future["version"]
        assert project_check(project, source_root=ROOT)["valid"]


def test_framework_rebind_refuses_a_damaged_receipt(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory) / "project"
        commission(project, "new", apply=True, source_root=ROOT)
        receipt_path = project / ".engineering-bootstrap/commissioning-receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["receipt_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        current = commissioning._framework_binding(ROOT)
        monkeypatch.setattr(
            commissioning,
            "_framework_binding",
            lambda source: {**current, "version": "99.0.0-test"},
        )

        result = rebind_commissioning_framework(
            project, source_root=ROOT, apply=True
        )
        assert not result["valid"]
        assert not result["applied"]
        assert result["errors"] == ["commissioning receipt digest mismatch"]
        assert not (project / ".engineering-bootstrap/commissioning-history").exists()
