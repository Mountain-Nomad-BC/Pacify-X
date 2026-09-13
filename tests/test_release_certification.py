from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest.mock import patch

import pytest

from runtime.release_certification import (
    FINALIZER_FULL_REPAIR_PENDING,
    RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT,
    RELEASE_SANITATION_EXCLUDED_NAMES,
    _certificate_ledger_errors,
    _commit_release_evidence,
    _compact_coverage_contexts,
    _copy_clean,
    _junit_case_gate,
    _junit_metadata_gate,
    _junit_skip_policy_gate,
    _junit_totals,
    _portable_payload_gate,
    _redact_machine_local_value,
    _release_environment_gate,
    _resolve_release_gate_roots,
    _run_release_test_process,
    _sanitize_junit_metadata,
    finalize_release,
    validate_release_gate_repository_context,
    verify_release_certificate,
)
from runtime.corrective_release import validate_corrective_ledger
from runtime.full_repair import validate_full_repair_ledger
from tests.repository_copy import canonical_copy_ignore


ROOT = Path(__file__).parents[1]


def test_release_test_owner_refreshes_projection_before_process(
    tmp_path: Path, monkeypatch
) -> None:
    events = []

    def prepare(root: Path):
        events.append(("prepare", root))
        return {"valid": True, "failures": []}

    def run(command, **kwargs):
        events.append(("run", list(command), kwargs))
        return {"valid": True, "exit_code": 0, "timed_out": False}

    monkeypatch.setattr(
        "runtime.release_preflight.prepare_release_test_completion_projection",
        prepare,
    )
    monkeypatch.setattr("runtime.release_certification.run_test_command", run)
    output = tmp_path / "output.xml"

    projection, process = _run_release_test_process(
        tmp_path,
        ["python", "-m", "pytest"],
        {"SAFE": "1"},
        timeout_seconds=30,
        disk_consumption_paths=(output,),
    )

    assert projection["valid"] is True
    assert process["valid"] is True
    assert events[0] == ("prepare", tmp_path)
    assert events[1][0] == "run"
    assert events[1][2]["disk_consumption_paths"] == (output,)
    assert events[1][2]["manage_process_temp"] is True


def test_release_test_owner_does_not_start_when_projection_refresh_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "runtime.release_preflight.prepare_release_test_completion_projection",
        lambda root: {
            "valid": False,
            "failures": [{"code": "RP-TST-002", "message": "stale"}],
        },
    )
    monkeypatch.setattr(
        "runtime.release_certification.run_test_command",
        lambda *args, **kwargs: pytest.fail("test process must not start"),
    )

    projection, process = _run_release_test_process(
        tmp_path,
        ["python", "-m", "pytest"],
        {},
        timeout_seconds=30,
        disk_consumption_paths=(),
    )

    assert projection["valid"] is False
    assert process["valid"] is False
    assert process["exit_code"] is None


def test_release_gate_repository_context_fails_before_expensive_gates(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "materialized-candidate"
    candidate.mkdir()

    result = validate_release_gate_repository_context(candidate)

    assert result["valid"] is False
    assert ".git" in result["missing"]
    assert "evidence/externalized-payload-index.json" in result["missing"]


def test_release_gate_roots_keep_authenticated_repository_distinct_from_candidate(
    tmp_path: Path,
) -> None:
    source = tmp_path / "authenticated-source"
    candidate = tmp_path / "frozen-candidate"
    source.mkdir()
    candidate.mkdir()
    (source / ".git").mkdir()
    for relative in RELEASE_GATE_REQUIRED_REPOSITORY_CONTEXT:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    roots = _resolve_release_gate_roots(candidate, source)

    assert roots["candidate_root"] == candidate.resolve()
    assert roots["authenticated_source_root"] == source.resolve()
    assert roots["repository_context"]["valid"] is True
    assert not (candidate / ".git").exists()


def test_release_sanitation_excludes_generated_control_custody_only(
    tmp_path: Path,
) -> None:
    from scripts.audit_sanitization import audit

    generated = tmp_path / ".engineering-bootstrap/control.json"
    generated.parent.mkdir()
    generated.write_text(
        "C:" + "/Users/LocalOwner/generated.json\n", encoding="utf-8"
    )
    live = tmp_path / "runtime/live.json"
    live.parent.mkdir()
    live.write_text("C:" + "/Users/LocalOwner/live.json\n", encoding="utf-8")

    result = audit(tmp_path, excluded_names=RELEASE_SANITATION_EXCLUDED_NAMES)

    assert result["host_home_path_hit_count"] == 1
    assert result["host_home_path_hits"][0]["path"] == "runtime/live.json"


def test_clean_release_copy_uses_the_canonical_product_boundary() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "source"
        destination = root / "destination"
        (source / "runtime").mkdir(parents=True)
        (source / "runtime/owned.py").write_text("owned = True\n", encoding="utf-8")
        (source / ".engineering-bootstrap").mkdir()
        (source / ".engineering-bootstrap/owned.json").write_text("{}\n", encoding="utf-8")
        for relative in (
            ".tmp/host-cache.bin",
            ".venv-certify/dependency.txt",
            "Python/runtime.txt",
            ".engineering-bootstrap/diagnostics/cache.json",
            ".engineering-bootstrap/operation-bus/wal/owned.zip",
            ".engineering-bootstrap/project-map-history-archives/owned.zip",
            ".engineering-bootstrap/.lock-recovery-receipts/release.lock/receipt.json",
        ):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("not product input\n", encoding="utf-8")

        _copy_clean(source, destination)

        assert (destination / "runtime/owned.py").is_file()
        assert (destination / ".engineering-bootstrap/owned.json").is_file()
        assert not (destination / ".tmp").exists()
        assert not (destination / ".venv-certify").exists()
        assert not (destination / "Python").exists()
        assert not (destination / ".engineering-bootstrap/diagnostics").exists()
        assert not (destination / ".engineering-bootstrap/operation-bus").exists()
        assert not (
            destination / ".engineering-bootstrap/project-map-history-archives"
        ).exists()
        assert not (
            destination / ".engineering-bootstrap/.lock-recovery-receipts"
        ).exists()


def test_finalizer_uses_bounded_packaged_evidence_materializer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "source"
    root.mkdir()
    key = tmp_path / "release-key"
    key.write_text("private key fixture is not inspected\n", encoding="utf-8")
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    observed: dict[str, Path] = {}

    class MaterializationObserved(RuntimeError):
        """Sentinel proving finalization reached bounded materialization."""

    def stop_after_materialization(source: Path, destination: Path) -> None:
        observed["source"] = source
        observed["destination"] = destination
        raise MaterializationObserved

    monkeypatch.setattr(
        "runtime.release_certification.validate_version_surfaces",
        lambda _root, asserted=None: {
            "authoritative_version": asserted,
            "errors": [],
        },
    )
    monkeypatch.setattr("runtime.release_certification._eligible_ledger", lambda _root: [])
    monkeypatch.setattr(
        "runtime.release_certification.capture_git_identity",
        lambda _root, version=None: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_preflight.validate_preflight_receipt",
        lambda _root, _release: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.classify_tree",
        lambda _root: {
            "valid": True,
            "product_valid": True,
            "product_digest": "a" * 64,
            "harness_digest": "b" * 64,
            "errors": [],
        },
    )
    monkeypatch.setattr(
        "runtime.release_certification.build_wheelhouse_manifest",
        lambda _wheelhouse, _requirements: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.materialize_release_source",
        stop_after_materialization,
    )
    monkeypatch.setattr(
        "runtime.release_certification.tempfile.gettempdir", lambda: str(tmp_path)
    )

    with pytest.raises(MaterializationObserved):
        finalize_release(
            root,
            "0.7.0",
            signing_key=key,
            wheelhouse=wheelhouse,
            artifact_dir=tmp_path / "artifacts",
        )

    assert observed["source"] == root.resolve()
    assert observed["destination"].name == "product"
    assert observed["destination"].parent.parent.name == "pacify-x-release-quarantine"


def _eligible_clone() -> Path:
    directory = Path(tempfile.mkdtemp())
    clone = directory / "framework"
    ignore = canonical_copy_ignore(
        ROOT,
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
    )

    shutil.copytree(
        ROOT,
        clone,
        ignore=ignore,
    )
    ledger_path = clone / "registry/corrective_release_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    receipt = clone / "evidence/test-finalizer-prerequisite.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text('{"valid":true}\n', encoding="utf-8")
    shutil.copy2(
        ROOT / "evidence/release-revocation-0.6.2.json",
        clone / "evidence/release-revocation-0.6.2.json",
    )
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
            '<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0">'
            '<testcase classname="a" name="one"/><testcase classname="a" name="two"/>'
            '<testcase classname="a" name="three"/></testsuite>'
            '<testsuite tests="2" failures="0" errors="0" skipped="0">'
            '<testcase classname="b" name="one"/><testcase classname="b" name="two"/>'
            '</testsuite></testsuites>',
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


def test_junit_skip_policy_allows_only_reviewed_host_conditionals() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite tests="1" skipped="1">'
            '<testcase classname="tests.test_clean_source_export" '
            'name="test_posix_unzip_restores_and_directly_executes_script">'
            '<skipped message="ordinary POSIX unzip execution is verified on a host with unzip" />'
            '</testcase></testsuite></testsuites>',
            encoding="utf-8",
        )
        result = _junit_skip_policy_gate(report)
        assert result["valid"]
        assert result["allowed_count"] == 1

        report.write_text(
            '<testsuites><testsuite tests="1" skipped="1">'
            '<testcase classname="tests.test_unknown" name="test_unreviewed">'
            '<skipped message="environment unavailable" />'
            '</testcase></testsuite></testsuites>',
            encoding="utf-8",
        )
        result = _junit_skip_policy_gate(report)
        assert not result["valid"]
        assert result["unexpected"] == ["tests.test_unknown::test_unreviewed"]


def test_coverage_context_compaction_retains_only_governed_modules(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "policies").mkdir(parents=True)
    (root / "policies/coverage-assurance.json").write_text(
        json.dumps(
            {
                "classes": {
                    "critical": {"modules": ["runtime/critical.py"]},
                }
            }
        ),
        encoding="utf-8",
    )
    coverage_path = root / "coverage.json"
    coverage_path.write_text(
        json.dumps(
            {
                "meta": {"branch_coverage": True, "show_contexts": True},
                "files": {
                    "runtime/critical.py": {
                        "summary": {"num_branches": 2, "missing_branches": 0},
                        "contexts": {"1": ["test_critical"]},
                        "functions": {
                            "critical": {"contexts": {"1": ["test_critical"]}}
                        },
                    },
                    "runtime/ordinary.py": {
                        "summary": {"num_branches": 4, "missing_branches": 1},
                        "contexts": {"1": ["test_ordinary"]},
                        "classes": {
                            "Ordinary": {"contexts": {"1": ["test_ordinary"]}}
                        },
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    result = _compact_coverage_contexts(root, coverage_path)
    compacted = json.loads(coverage_path.read_text(encoding="utf-8"))

    assert result["files_with_contexts_retained"] == 1
    assert result["files_with_contexts_removed"] == 1
    assert result["nested_context_fields_removed"] == 2
    assert compacted["files"]["runtime/critical.py"]["contexts"]
    assert "contexts" not in compacted["files"]["runtime/critical.py"]["functions"]["critical"]
    assert "contexts" not in compacted["files"]["runtime/ordinary.py"]
    assert "contexts" not in compacted["files"]["runtime/ordinary.py"]["classes"]["Ordinary"]
    assert compacted["files"]["runtime/ordinary.py"]["summary"]["num_branches"] == 4
    assert compacted["meta"]["pacify_x_context_scope"] == "policy-governed-modules"


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
            '<testsuites><testsuite hostname="runner"><testcase classname="tests.test_example" name="test_failure">'
            "<failure>C:" + "\\Users\\runneradmin\\work\\project\\tests\\test_example.py:10 "
            "/" + "home/runner/work/project/tests/test_example.py:10</failure>"
            "</testcase></testsuite></testsuites>",
            encoding="utf-8",
        )
        _sanitize_junit_metadata(report)
        result = _junit_metadata_gate(report)
        content = report.read_text(encoding="utf-8")
        assert result["valid"], result["errors"]
        assert content.count("[machine-local-path]") == 2
        assert "runneradmin" not in content
        assert "/" + "home/runner" not in content


def test_junit_publication_evidence_redacts_parent_traversing_traceback_paths() -> None:
    with tempfile.TemporaryDirectory() as directory:
        report = Path(directory) / "report.xml"
        report.write_text(
            '<testsuites><testsuite><testcase classname="tests.test_example" name="test_failure">'
            "<failure>..\\..\\..\\pytest\\test_nested.py:14 ../pytest/test_nested.py:9</failure>"
            "</testcase></testsuite></testsuites>",
            encoding="utf-8",
        )
        _sanitize_junit_metadata(report)
        result = _junit_metadata_gate(report)
        content = report.read_text(encoding="utf-8")
        assert result["valid"], result["errors"]
        assert "..\\" not in content
        assert "../" not in content


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
        "C:" + "/" + "Users/example/AppData/Local/Temp/build-a1b2c3",
        "C:" + r"\Users\example\AppData\Local\Temp\build-a1b2c3",
        "/" + "Users/example/tmp/build-a1b2c3",
        "/" + "home/example/tmp/build-a1b2c3",
        "../outside/build-a1b2c3",
    ):
        result = _portable_payload_gate({"quarantine": local_path})
        assert not result["valid"]
        assert result["nonportable_path_count"] == 1


def test_release_evidence_redaction_preserves_shape_and_removes_local_paths() -> None:
    value = {
        "python_executable": "C:" + r"\Users\example\Temp\venv\Scripts\python.exe",
        "errors": ["from /tmp/release/venv/bin/python"],
        "valid": True,
    }
    redacted = _redact_machine_local_value(value)
    assert isinstance(redacted, dict)
    assert redacted["valid"] is True
    assert redacted["errors"] == ["from [machine-local-path]"]
    assert _portable_payload_gate(redacted)["valid"]


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


def test_certificate_verifier_binds_artifacts_to_recorded_frozen_manifest(
    tmp_path: Path, monkeypatch
) -> None:
    release = "0.7.0"
    product_digest = "1" * 64
    harness_digest = "2" * 64
    manifest_digest = "3" * 64
    release_root = tmp_path / f"evidence/releases/{release}"
    run_root = release_root / "run-frozen"
    run_root.mkdir(parents=True)
    evidence_manifest = run_root / "evidence-manifest.json"
    evidence_manifest.write_text("{}\n", encoding="utf-8")
    artifact_manifest = {
        "schema_version": "1.0",
        "manifest_sha256": manifest_digest,
        "records": [],
    }
    (run_root / "artifact-manifest.json").write_text(
        json.dumps(artifact_manifest), encoding="utf-8"
    )
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    artifact_bytes = b"owned artifact bytes for the isolated mocked format-binding seam"
    (artifact_dir / "fixture-0.7.0-py3-none-any.whl").write_bytes(artifact_bytes)
    records = [
        {
            "type": "wheel",
            "filename": "fixture-0.7.0-py3-none-any.whl",
            "sha256": hashlib.sha256(artifact_bytes).hexdigest(),
            "size_bytes": len(artifact_bytes),
        }
    ]
    (release_root / "certificate.json.sig").write_bytes(
        b"mocked signature seam; not cryptographic evidence"
    )
    certificate = {
        "release": release,
        "status": "self_certified",
        "certification_platform": {},
        "signature": {"path": "certificate.json.sig"},
        "source_control": {},
        "product_digest": product_digest,
        "harness_digest": harness_digest,
        "coverage_evidence": f"evidence/releases/{release}/run-frozen/coverage.json",
        "evidence_manifest": f"evidence/releases/{release}/run-frozen/evidence-manifest.json",
        "evidence_manifest_sha256": hashlib.sha256(
            evidence_manifest.read_bytes()
        ).hexdigest(),
        "artifact_manifest": f"evidence/releases/{release}/run-frozen/artifact-manifest.json",
        "artifact_manifest_sha256": manifest_digest,
        "artifacts": records,
    }
    (release_root / "certificate.json").write_text(
        json.dumps(certificate), encoding="utf-8"
    )
    observed: dict[str, object] = {}

    monkeypatch.setattr(
        "runtime.release_certification.validate_certification_platform",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.verify_certificate_signature",
        lambda *_args, **_kwargs: {"valid": True, "errors": [], "identity": {}},
    )
    monkeypatch.setattr(
        "runtime.release_certification.validate_version_surfaces",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.verify_recorded_git_identity",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.classify_tree",
        lambda *_args, **_kwargs: {
            "valid": True,
            "errors": [],
            "product_digest": product_digest,
            "harness_digest": harness_digest,
        },
    )
    monkeypatch.setattr(
        "runtime.release_certification._verify_coverage_binding",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification.verify_evidence_manifest",
        lambda *_args, **_kwargs: {"valid": True, "errors": []},
    )
    monkeypatch.setattr(
        "runtime.release_certification._certificate_ledger_errors", lambda *_args: []
    )

    def bind(*_args, **kwargs):
        observed.update(kwargs)
        return {
            "valid": True,
            "errors": [],
            "artifact_manifest_sha256": manifest_digest,
        }

    monkeypatch.setattr("runtime.release_certification.bind_artifact_set", bind)

    result = verify_release_certificate(
        tmp_path, release=release, artifact_dir=artifact_dir
    )

    assert result["valid"], result["errors"]
    assert observed["artifact_manifest"] == artifact_manifest
    assert "source_root" not in observed


def test_junit_totals_refuse_invented_case_denominator(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuite tests="5"/>', encoding="utf-8")
    with pytest.raises(ValueError):
        _junit_totals(report)


def test_junit_named_surface_handles_namespaced_failure(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuite xmlns="urn:junit"><testcase classname="tests.target" name="ok"/>'
                      '<testcase classname="tests.target" name="bad"><failure/></testcase></testsuite>', encoding="utf-8")
    result = _junit_case_gate(report, "tests.target")
    assert not result["valid"]
    assert result["tests"] == 2 and result["failures"] == 1


def test_release_evidence_commit_reports_partial_effects(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "a.json").write_bytes(b"first")
    (source / "b.json").write_bytes(b"second")
    original = Path.open

    def fail_second(path, mode="r", *args, **kwargs):
        if path == destination / "b.json" and mode == "xb":
            raise OSError("injected second publication failure")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_second)
    result = _commit_release_evidence(source, destination)
    assert not result["valid"]
    assert (destination / "a.json").read_bytes() == b"first"
    assert result["copied_file_count"] == 1
    assert result["copied_records"][0]["path"] == "a.json"
    assert result["publication_state"] == "partial"


def test_release_evidence_commit_requires_nonempty_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    destination = tmp_path / "destination"
    result = _commit_release_evidence(source, destination)
    assert not result["valid"]
    assert not destination.exists()


def test_release_evidence_commit_rejects_destination_source_overlap(tmp_path):
    (tmp_path / "proof.json").write_bytes(b"proof")
    result = _commit_release_evidence(tmp_path, tmp_path / "nested")
    assert not result["valid"]
    assert not (tmp_path / "nested").exists()


def _complete_gate_summary_for_contract_test():
    from runtime.release_certification import REQUIRED_RELEASE_GATES

    gates = {name: {"valid": True, "errors": []} for name in REQUIRED_RELEASE_GATES}
    gates["full_tests"].update(tests=1, failures=0, errors=0, skipped=0, exit_code=0,
                              timed_out=False, runner_valid=True, process_tree_terminated=True,
                              workspace_reclaimed=True)
    gates["full_test_skip_policy"].update(allowed_count=0, unexpected_count=0, allowed=[], unexpected=[])
    gates["exact_tools"].update(denominator=1, passed=1)
    return {"schema_version": "1.0", "valid": True, "gate_count": len(gates), "gates": gates}


@pytest.mark.parametrize("mutation", ["empty", "missing", "false-count", "error", "no-cases", "no-tools", "live-child", "workspace", "exit-bool"])
def test_release_summary_refuses_incomplete_or_contradictory_proof(mutation):
    from runtime.release_certification import _release_gate_summary_errors

    value = _complete_gate_summary_for_contract_test()
    assert not _release_gate_summary_errors(value)
    if mutation == "empty":
        value["gates"] = {}
        value["gate_count"] = 0
    elif mutation == "missing":
        value["gates"].pop("contracts")
        value["gate_count"] -= 1
    elif mutation == "false-count":
        value["gate_count"] += 1
    elif mutation == "error":
        value["gates"]["contracts"]["errors"] = ["contract failed"]
    elif mutation == "no-cases":
        value["gates"]["full_tests"]["tests"] = 0
    elif mutation == "no-tools":
        value["gates"]["exact_tools"].update(denominator=0, passed=0)
    elif mutation == "live-child":
        value["gates"]["full_tests"]["process_tree_terminated"] = False
    elif mutation == "workspace":
        value["gates"]["full_tests"]["workspace_reclaimed"] = False
    else:
        value["gates"]["full_tests"]["exit_code"] = False
    assert _release_gate_summary_errors(value)


@pytest.mark.parametrize("mutation", ["none", "missing-role", "changed-report", "resealed-false-count", "unknown-skip"])
def test_release_gate_report_binding_checks_actual_image_and_denominator(tmp_path, mutation):
    from runtime.release_certification import REQUIRED_RELEASE_EVIDENCE, _verify_release_gate_binding
    from runtime.release_evidence import build_evidence_manifest

    evidence = tmp_path / "evidence/releases/0.7.0/run-test"
    evidence.mkdir(parents=True)
    for name in REQUIRED_RELEASE_EVIDENCE:
        (evidence / name).write_bytes(b"{}")
    summary = _complete_gate_summary_for_contract_test()
    if mutation == "resealed-false-count":
        summary["gates"]["full_tests"]["tests"] = 2
    if mutation == "unknown-skip":
        summary["gates"]["full_tests"].update(tests=2, skipped=1)
    (evidence / "gate-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    (evidence / "full-tests.junit.xml").write_text(
        '<testsuite tests="1"><testcase classname="tests.example" name="actual_case"/></testsuite>', encoding="utf-8")
    if mutation == "unknown-skip":
        (evidence / "full-tests.junit.xml").write_text(
            '<testsuite tests="2" skipped="1"><testcase classname="tests.example" name="executed"/><testcase classname="tests.example" name="actual_case"><skipped message="unknown reason"/></testcase></testsuite>', encoding="utf-8")
    roles = {name: {"required": True} for name in REQUIRED_RELEASE_EVIDENCE}
    if mutation == "missing-role":
        roles.pop("installed-wheel.json")
    manifest = build_evidence_manifest(evidence, roles=roles)
    assert manifest["valid"], manifest["errors"]
    (evidence / "evidence-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    certificate = {
        "evidence_manifest": "evidence/releases/0.7.0/run-test/evidence-manifest.json",
        "gate_summary": "evidence/releases/0.7.0/run-test/gate-summary.json",
        "gate_summary_sha256": hashlib.sha256((evidence / "gate-summary.json").read_bytes()).hexdigest(),
    }
    if mutation == "changed-report":
        (evidence / "full-tests.junit.xml").write_bytes(b"<testsuite/>")
    errors = _verify_release_gate_binding(tmp_path, "0.7.0", certificate, manifest)
    assert bool(errors) == (mutation != "none"), errors


def test_junit_refuses_hidden_failure_structure(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuite><testcase classname="a" name="b"><wrapper><failure/></wrapper></testcase></testsuite>', encoding="utf-8")
    with pytest.raises(ValueError):
        _junit_totals(report)


def test_junit_sanitizer_refuses_doctype_before_rewriting(tmp_path):
    report = tmp_path / "report.xml"
    raw = b'<!DOCTYPE testsuite [<!ENTITY name "expanded">]><testsuite><testcase classname="a" name="&name;"/></testsuite>'
    report.write_bytes(raw)
    with pytest.raises(ValueError):
        _sanitize_junit_metadata(report)
    assert report.read_bytes() == raw


def test_release_publication_reports_directory_effect_before_file_open(tmp_path, monkeypatch):
    source, destination = tmp_path / "source", tmp_path / "destination"
    source.mkdir()
    (source / "a.json").write_bytes(b"first")
    original = Path.open

    def fail_open(path, mode="r", *args, **kwargs):
        if path == destination / "a.json" and mode == "xb":
            raise OSError("injected first publication failure")
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_open)
    result = _commit_release_evidence(source, destination)
    assert not result["valid"] and destination.is_dir()
    assert result["publication_state"] != "not_started"


def test_junit_named_surface_does_not_accept_lookalike_identity(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuite><testcase classname="tests.not_test_installed_wheel_e2e" name="fake_test_installed_wheel_e2e_pass"/></testsuite>', encoding="utf-8")
    assert not _junit_case_gate(report, "test_installed_wheel_e2e")["valid"]


def test_release_summary_requires_executed_non_skipped_cases():
    from runtime.release_certification import _release_gate_summary_errors

    summary = _complete_gate_summary_for_contract_test()
    summary["gates"]["full_tests"]["skipped"] = summary["gates"]["full_tests"]["tests"]
    assert _release_gate_summary_errors(summary)
