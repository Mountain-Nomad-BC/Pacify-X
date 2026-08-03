from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

from runtime.release_certification import _junit_case_gate, _junit_metadata_gate, _junit_totals, _portable_payload_gate, _release_environment_gate, _sanitize_junit_metadata, finalize_release, verify_release_certificate
from runtime.artifact_reachability import build_artifact_reachability


ROOT = Path(__file__).parents[1]


def _eligible_clone() -> Path:
    directory = Path(tempfile.mkdtemp())
    clone = directory / "framework"
    shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", ".ruff_cache", "*.pyc", "*.pyo", "build", "dist"))
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
    result = {"schema_version": "1.0", "valid": True, "gate_count": 1, "gates": {"synthetic": {"valid": True}}}
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
        assert _junit_totals(report) == {"tests": 5, "failures": 0, "errors": 0, "skipped": 0}


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


def test_release_environment_gate_uses_isolated_interpreter() -> None:
    payload = {"schema_version": "1.0", "valid": True, "errors": []}
    completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
    with patch("runtime.release_certification.subprocess.run", return_value=completed) as run:
        result = _release_environment_gate(ROOT, "isolated-python", {"PYTHONDONTWRITEBYTECODE": "1"})
    assert result["valid"]
    assert run.call_args.args[0][0] == "isolated-python"


def test_publishable_release_metadata_rejects_machine_local_paths() -> None:
    portable = {"custody_class": "external_temporary_quarantine", "custody_id": "build-a1b2c3"}
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


def test_finalizer_publishes_digest_bound_certificate_and_state_last() -> None:
    root = _eligible_clone()
    result = finalize_release(root, "0.6.2", gate_runner=_green_gates)
    assert result["valid"], result["errors"]
    assert result["published"]
    assert verify_release_certificate(root, release="0.6.2")["valid"]
    recorded_reachability = json.loads((root / "registry/artifact_reachability.json").read_text(encoding="utf-8"))
    assert recorded_reachability == build_artifact_reachability(root)
    state = json.loads((root / ".engineering-bootstrap/project-management/state.json").read_text(encoding="utf-8"))
    assert state["lifecycle"]["next_action"] == state["checkpoint"]["next_safe_action"]
    transaction = json.loads((root / ".engineering-bootstrap/release-transaction.json").read_text(encoding="utf-8"))
    assert transaction["status"] == "committed"
    certificate = json.loads((root / result["certificate"]).read_text(encoding="utf-8"))
    publication = root / certificate["publication_receipt"]
    assert publication.is_file()
    (root / ".engineering-bootstrap/release-transaction.json").unlink()
    assert verify_release_certificate(root, release="0.6.2")["valid"]


def test_product_mutation_during_finalization_fails_without_promotion() -> None:
    root = _eligible_clone()
    original_state = (root / ".engineering-bootstrap/project-management/state.json").read_bytes()
    result = finalize_release(root, "0.6.2", gate_runner=_green_gates, mutation_hook=lambda: (root / "runtime/models.py").write_text("# mutated\n", encoding="utf-8"))
    assert not result["valid"]
    assert not result["published"]
    assert (root / ".engineering-bootstrap/project-management/state.json").read_bytes() == original_state


def test_reused_certificate_fails_after_harness_or_product_change() -> None:
    root = _eligible_clone()
    assert finalize_release(root, "0.6.2", gate_runner=_green_gates)["valid"]
    with (root / "runtime/release_certification.py").open("a", encoding="utf-8") as stream:
        stream.write("\n# harness mutation\n")
    result = verify_release_certificate(root, release="0.6.2")
    assert not result["valid"]
    assert any("digest" in item for item in result["errors"])


def test_manual_state_promotion_without_certificate_fails_closed() -> None:
    root = _eligible_clone()
    state_path = root / ".engineering-bootstrap/project-management/state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["lifecycle"] = {"phase": "deployment-certified", "status": "complete", "next_action": "deploy"}
    state["evidence"]["validation_receipt"] = "evidence/release-certification-9.9.9.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    result = verify_release_certificate(root, release="9.9.9")
    assert not result["valid"]
    assert any("missing" in item for item in result["errors"])
