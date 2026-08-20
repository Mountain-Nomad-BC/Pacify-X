from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from runtime.release_certification import (
    FINALIZER_FULL_REPAIR_PENDING,
    _certificate_ledger_errors,
    _commit_release_evidence,
    _junit_case_gate,
    _junit_metadata_gate,
    _junit_totals,
    _portable_payload_gate,
    _release_environment_gate,
    _sanitize_junit_metadata,
    finalize_release,
    verify_release_certificate,
)
from runtime.corrective_release import validate_corrective_ledger
from runtime.full_repair import validate_full_repair_ledger


ROOT = Path(__file__).parents[1]


def _eligible_clone() -> Path:
    directory = Path(tempfile.mkdtemp())
    clone = directory / "framework"
    shutil.copytree(
        ROOT,
        clone,
        ignore=shutil.ignore_patterns(
            ".git",
            "__pycache__",
            ".venv*",
            "Python",
            "node_modules",
            ".pytest_cache",
            ".ruff_cache",
            ".vscode-test",
            "*.pyc",
            "*.pyo",
            "build",
            "dist",
            "preserved-extension-installations",
            "project-map",
            "project-map-history",
            "project-map-lock-history",
            "quarantine",
            "environment",
            "operation-bus",
        ),
    )
    ledger_path = clone / "registry/corrective_release_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    receipt = clone / "evidence/test-finalizer-prerequisite.json"
    receipt.write_text('{"valid":true}\n', encoding="utf-8")
    for card in ledger["cards"]:
        if card["id"] not in {"REL-010-C", "REL-010-E"}:
            card["status"] = "passed"
            card["receipts"] = ["evidence/test-finalizer-prerequisite.json"]
            card["disposition"] = "Synthetic unit-test prerequisite."
    ledger_path.write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")
    return clone


def _green_gates(root: Path, evidence: Path) -> dict:
    evidence.mkdir(parents=True, exist_ok=True)
    result = {
        "schema_version": "1.0",
        "valid": True,
        "gate_count": 1,
        "gates": {"synthetic": {"valid": True}},
    }
    (evidence / "gate-summary.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def test_junit_totals_aggregate_testsuites_root() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0" />'
            '<testsuite tests="2" failures="0" errors="0" skipped="0" /></testsuites>',
            encoding="utf-8",
        )
        assert _junit_totals(report) == {
            "tests": 5,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }


def test_junit_named_surface_gate_requires_present_green_case() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite><testcase classname="tests.test_installed_wheel_e2e.Suite" '
            'name="test_wheel_installs" /></testsuite></testsuites>',
            encoding="utf-8",
        )
        assert _junit_case_gate(report, "test_installed_wheel_e2e")["valid"]
        assert not _junit_case_gate(report, "test_sanitization_audit")["valid"]


def test_junit_publication_evidence_removes_host_identity() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite hostname="private-workstation" tests="1">'
            '<testcase classname="tests.test_example" name="test_green" /></testsuite></testsuites>',
            encoding="utf-8",
        )
        assert not _junit_metadata_gate(report)["valid"]
        _sanitize_junit_metadata(report)
        result = _junit_metadata_gate(report)
        assert result["valid"], result["errors"]
        assert "private-workstation" not in report.read_text(encoding="utf-8")


def test_junit_publication_evidence_redacts_machine_local_failure_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite hostname="runner"><testcase name="test_failure">'
            "<failure>C:\\Users\\runneradmin\\work\\project\\tests\\test_example.py:10 "
            "/home/runner/work/project/tests/test_example.py:10</failure>"
            "</testcase></testsuite></testsuites>",
            encoding="utf-8",
        )
        _sanitize_junit_metadata(report)
        result = _junit_metadata_gate(report)
        content = report.read_text(encoding="utf-8")
        assert result["valid"], result["errors"]
        assert content.count("[machine-local-path]") == 2
        assert "runneradmin" not in content
        assert "/home/runner" not in content


def test_release_environment_gate_uses_isolated_interpreter() -> None:
    payload = {"schema_version": "1.0", "valid": True, "errors": []}
    completed = subprocess.CompletedProcess(
        [], 0, stdout=json.dumps(payload), stderr=""
    )
    with patch(
        "runtime.release_certification.subprocess.run", return_value=completed
    ) as run:
        result = _release_environment_gate(
            ROOT, "isolated-python", {"PYTHONDONTWRITEBYTECODE": "1"}
        )
    assert result["valid"]
    assert run.call_args.args[0][0] == "isolated-python"


def test_publishable_release_metadata_rejects_machine_local_paths() -> None:
    portable = {
        "custody_class": "external_temporary_quarantine",
        "custody_id": "build-a1b2c3",
    }
    assert _portable_payload_gate(portable)["valid"]
    for local_path in (
        "C:/Users/example/AppData/Local/Temp/build-a1b2c3",
        r"C:\Users\example\AppData\Local\Temp\build-a1b2c3",
        "/Users/example/tmp/build-a1b2c3",
        "/home/example/tmp/build-a1b2c3",
        "../outside/build-a1b2c3",
    ):
        result = _portable_payload_gate({"quarantine": local_path})
        assert not result["valid"]
        assert result["nonportable_path_count"] == 1


def test_in_progress_release_evidence_is_not_a_child_of_staged_product() -> None:
    transaction = Path(tempfile.mkdtemp())
    staged = transaction / "product"
    staged.mkdir()
    evidence = transaction / "release-evidence/1.2.3/run-123"
    evidence.mkdir(parents=True)
    assert staged not in evidence.parents
    assert (
        evidence.relative_to(transaction).as_posix() == "release-evidence/1.2.3/run-123"
    )


def test_release_evidence_commit_preserves_nonconflicting_pre_release_records() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "external/release-evidence/0.6.3"
        destination = root / "product/evidence/releases/0.6.3"
        (source / "run-123").mkdir(parents=True)
        (source / "certificate.json").write_text('{"signed":true}\n', encoding="utf-8")
        (source / "run-123/gate-summary.json").write_text(
            '{"valid":true}\n', encoding="utf-8"
        )
        destination.mkdir(parents=True)
        summary = destination / "local-certification-summary.json"
        summary.write_text('{"status":"pre-release"}\n', encoding="utf-8")

        result = _commit_release_evidence(source, destination)

        assert result["valid"], result["errors"]
        assert result["copied_file_count"] == 2
        assert summary.read_text(encoding="utf-8") == '{"status":"pre-release"}\n'
        assert (destination / "certificate.json").read_text(
            encoding="utf-8"
        ) == '{"signed":true}\n'
        assert (destination / "run-123/gate-summary.json").is_file()


def test_release_evidence_commit_rejects_every_existing_file_collision() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "external/release-evidence/0.6.3"
        destination = root / "product/evidence/releases/0.6.3"
        source.mkdir(parents=True)
        destination.mkdir(parents=True)
        (source / "certificate.json").write_text("new signed bytes\n", encoding="utf-8")
        existing = destination / "certificate.json"
        existing.write_text("existing bytes\n", encoding="utf-8")

        result = _commit_release_evidence(source, destination)

        assert not result["valid"]
        assert result["copied_file_count"] == 0
        assert result["errors"] == ["release evidence collision: certificate.json"]
        assert existing.read_text(encoding="utf-8") == "existing bytes\n"


def test_published_authenticated_certificate_closes_every_release_card() -> None:
    assert not _certificate_ledger_errors(ROOT)
    assert validate_corrective_ledger(ROOT, require_blocking_passed=True)["valid"]
    assert validate_full_repair_ledger(ROOT, require_all_passed=True)["valid"]
    assert FINALIZER_FULL_REPAIR_PENDING == {
        "PC-001",
        "PC-002",
        "PC-003",
        "PC-004",
        "PC-005",
        "PC-006",
        "PC-037",
    }


def test_finalizer_requires_authenticated_offline_release_inputs() -> None:
    root = _eligible_clone()
    result = finalize_release(root, "0.6.2", gate_runner=_green_gates)
    assert not result["valid"] and not result["published"]
    assert "release signing key is required" in result["errors"]
    assert "hash-locked release wheelhouse is required" in result["errors"]


def test_missing_release_inputs_fail_without_state_promotion() -> None:
    root = _eligible_clone()
    original_state = (
        root / ".engineering-bootstrap/project-management/state.json"
    ).read_bytes()
    result = finalize_release(
        root,
        "0.6.2",
        gate_runner=_green_gates,
        mutation_hook=lambda: (root / "runtime/models.py").write_text(
            "# mutated\n", encoding="utf-8"
        ),
    )
    assert not result["valid"]
    assert not result["published"]
    assert (
        root / ".engineering-bootstrap/project-management/state.json"
    ).read_bytes() == original_state


def test_revoked_certificate_cannot_be_reused_after_product_change() -> None:
    root = _eligible_clone()
    with (root / "runtime/release_certification.py").open(
        "a", encoding="utf-8"
    ) as stream:
        stream.write("\n# harness mutation\n")
    result = verify_release_certificate(root, release="0.6.2")
    assert not result["valid"]
    assert any("revoked" in item for item in result["errors"])


def test_manual_state_promotion_without_certificate_fails_closed() -> None:
    root = _eligible_clone()
    state_path = root / ".engineering-bootstrap/project-management/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["lifecycle"] = {
        "phase": "deployment-certified",
        "status": "complete",
        "next_action": "deploy",
    }
    state["evidence"]["validation_receipt"] = (
        "evidence/release-certification-9.9.9.json"
    )
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = verify_release_certificate(root, release="9.9.9")
    assert not result["valid"]
    assert any("missing" in item for item in result["errors"])
