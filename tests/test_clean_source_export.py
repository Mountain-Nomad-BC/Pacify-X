from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os
import shutil
import subprocess
import tempfile
import zipfile

import pytest

import runtime.effect_surface
import runtime.evidence_index
import runtime.evidence_portability
import runtime.generated_artifacts
import runtime.licensing
import runtime.provider_gateway
import runtime.repository_scope
import runtime.release_audit
import runtime.registry
import runtime.sanitation_assurance
import runtime.structural_integrity
import runtime.test_profiles
import scripts.audit_sanitization
import scripts.audit_source_archive
import scripts.clean_source_export as clean_source_export
from scripts.clean_source_export import create_clean_export


def test_clean_export_is_byte_deterministic_and_non_destructive():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "source"
        root.mkdir()
        (root / "keep.txt").write_text("keep\n", encoding="utf-8")
        (root / "run.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (root / "windows.txt").write_bytes(b"one\r\ntwo\r\n")
        (root / ".git").mkdir()
        (root / ".git/config").write_text("private\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__/x.pyc").write_bytes(b"cache")
        (root / ".venv-certify/Scripts").mkdir(parents=True)
        (root / ".venv-certify/Scripts/tool.exe").write_bytes(b"generated")
        (root / ".tmp_work.json").write_text("temporary\n", encoding="utf-8")
        (root / ".tmp_batch/record.json").parent.mkdir()
        (root / ".tmp_batch/record.json").write_text("temporary\n", encoding="utf-8")
        (root / ".tmp/cache.bin").parent.mkdir()
        (root / ".tmp/cache.bin").write_bytes(b"temporary")
        (root / "tmp_admission.json").write_text("temporary\n", encoding="utf-8")
        (root / "registry/.operational-gap-ledger.lock").parent.mkdir()
        (root / "registry/.operational-gap-ledger.lock").write_text(
            "host-local lock\n", encoding="utf-8"
        )
        (root / ".VSCodeCounter/report.txt").parent.mkdir()
        (root / ".VSCodeCounter/report.txt").write_text("generated\n", encoding="utf-8")
        (root / "evidence/historical-proof.json").parent.mkdir()
        (root / "evidence/historical-proof.json").write_text(
            '{"historical":true}\n', encoding="utf-8"
        )
        first = Path(directory) / "first.zip"
        second = Path(directory) / "second.zip"
        one = create_clean_export(root, first)
        two = create_clean_export(root, second)
        assert one["archive_sha256"] == two["archive_sha256"]
        assert one["hard_delete"] is False
        assert (root / ".git/config").is_file()
        with zipfile.ZipFile(first) as archive:
            assert archive.namelist() == [
                "AUDIT_EXPORT_MANIFEST.json",
                "AUDIT_REPLAY_CONTRACT.json",
                "keep.txt",
                "run.sh",
                "windows.txt",
            ]
            assert archive.read("windows.txt") == b"one\r\ntwo\r\n"
            assert (archive.getinfo("run.sh").external_attr >> 16) & 0o777 == 0o755
            assert (archive.getinfo("keep.txt").external_attr >> 16) & 0o777 == 0o644
            assert archive.getinfo("run.sh").create_system == 3
            assert archive.getinfo("keep.txt").create_system == 3
            manifest = __import__("json").loads(
                archive.read("AUDIT_EXPORT_MANIFEST.json")
            )
            assert (
                manifest["bundle_mode"]
                == "source-only-final-byte-candidate"
            )
            assert manifest["artifacts"] == []
            assert manifest["certification_claim"] is False
            assert manifest["record_count"] == 4
            assert [record["path"] for record in manifest["records"]] == [
                "AUDIT_REPLAY_CONTRACT.json",
                "keep.txt",
                "run.sh",
                "windows.txt",
            ]
            assert manifest["build_time"] == manifest["source_timestamp"]
            assert manifest["source_control_available"] is False
            assert manifest["source_commit"] is None
            assert manifest["source_commit_time"] is None
        receipt = json.loads(Path(one["replay_receipt"]).read_text(encoding="utf-8"))
        assert receipt["archive_sha256"] == one["archive_sha256"]
        assert receipt["valid"] is True


def test_export_uses_shared_repository_scope_for_ephemeral_artifacts() -> None:
    source = __import__("inspect").getsource(clean_source_export.included_files)
    assert "is_external_environment_relative(relative)" in source
    for relative in (
        ".tmp/cache.bin",
        ".tmp_work.json",
        "tmp_admission.json",
        ".VSCodeCounter/report.json",
        ".pacify-x/resource-ledger.json.lock",
        ".engineering-bootstrap/coordination/state.json",
    ):
        assert runtime.repository_scope.is_external_environment_relative(relative)


def test_git_source_archive_is_bounded_and_excludes_local_custody() -> None:
    root = Path(__file__).resolve().parents[1]
    result = scripts.audit_source_archive.audit_source_archive(
        root, worktree_attributes=True
    )
    assert result["valid"], result
    assert result["uncompressed_bytes"] <= result["maximum_uncompressed_bytes"]
    assert result["forbidden_members"] == []


def test_clean_export_refuses_unearned_certified_filename(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "value.txt").write_text("value\n", encoding="utf-8")
    with __import__("pytest").raises(ValueError, match="CERTIFIED filename"):
        create_clean_export(root, tmp_path / "PACIFY_X_CERTIFIED.zip")


def test_frozen_candidate_identity_rejects_preflight_mutation(tmp_path: Path) -> None:
    (tmp_path / "stable.txt").write_text("stable\n", encoding="utf-8")
    expected = clean_source_export._candidate_records(tmp_path)
    (tmp_path / "late.pyc").write_bytes(b"late")
    with pytest.raises(ValueError, match="changed the sealed candidate tree"):
        clean_source_export._assert_frozen_records(
            tmp_path, expected, phase="test preflight"
        )


@pytest.mark.skipif(
    os.name == "nt" or shutil.which("unzip") is None,
    reason="ordinary POSIX unzip execution is verified on a host with unzip",
)
def test_posix_unzip_restores_and_directly_executes_script(tmp_path: Path) -> None:
    root = tmp_path / "source"
    root.mkdir()
    (root / "verify.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8", newline="\n"
    )
    archive = tmp_path / "candidate.zip"
    create_clean_export(root, archive)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    subprocess.run(
        ["unzip", "-q", str(archive), "-d", str(extracted)], check=True
    )
    script = extracted / "verify.sh"
    assert script.stat().st_mode & 0o111 == 0o111
    subprocess.run([str(script)], check=True)


def test_clean_export_retains_only_test_receipts_from_runtime_state_and_omits_dangling_artifact_hashes(
    tmp_path: Path,
):
    root = tmp_path / "source"
    root.mkdir()
    receipt = root / ".engineering-bootstrap/test-evidence/sections/dashboard.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text('{"current":true}\n', encoding="utf-8")
    local_gate = (
        root
        / ".engineering-bootstrap/test-evidence/adversarial-repair-gates/structural.json"
    )
    local_gate.parent.mkdir(parents=True)
    local_gate.write_text('{"local":true}\n', encoding="utf-8")
    volatile = root / ".engineering-bootstrap/operation-bus/events.jsonl"
    volatile.parent.mkdir(parents=True)
    volatile.write_text("volatile\n", encoding="utf-8")
    authority = root / ".engineering-bootstrap/.ledger-authority/commissioning-events"
    head = authority / "head.json"
    anchor = authority / "anchors/00000001-example.json"
    anchor.parent.mkdir(parents=True)
    head.write_text('{"sequence":1}\n', encoding="utf-8")
    anchor.write_bytes(head.read_bytes())
    checksums = root / "extension/SHA256SUMS.txt"
    checksums.parent.mkdir()
    checksums.write_text("0" * 64 + "  dist/absent.vsix\n", encoding="ascii")
    output = tmp_path / "audit.zip"
    result = create_clean_export(root, output)
    assert result["test_receipt_count"] == 1
    with zipfile.ZipFile(output) as archive:
        assert (
            ".engineering-bootstrap/test-evidence/sections/dashboard.json"
            in archive.namelist()
        )
        assert (
            ".engineering-bootstrap/test-evidence/adversarial-repair-gates/structural.json"
            not in archive.namelist()
        )
        assert (
            ".engineering-bootstrap/operation-bus/events.jsonl"
            not in archive.namelist()
        )
        assert (
            ".engineering-bootstrap/.ledger-authority/commissioning-events/head.json"
            in archive.namelist()
        )
        assert (
            ".engineering-bootstrap/.ledger-authority/commissioning-events/anchors/00000001-example.json"
            in archive.namelist()
        )
        assert "extension/SHA256SUMS.txt" not in archive.namelist()


def test_certification_preflight_returns_aggregated_gate_result(
    monkeypatch, tmp_path: Path
):
    def valid(*args, **kwargs):
        return {"valid": True, "schema_version": "test/1.0"}

    for module, name in (
        (runtime.effect_surface, "validate_effect_surfaces"),
        (runtime.evidence_index, "build_index"),
        (runtime.evidence_portability, "validate_evidence_portability"),
        (runtime.generated_artifacts, "validate_generated_artifacts"),
        (runtime.licensing, "validate_licensing"),
        (runtime.provider_gateway, "scan_direct_provider_routes"),
            (runtime.release_audit, "audit_framework"),
            (runtime.registry, "validate_registry"),
        (runtime.sanitation_assurance, "build_sanitation_summary"),
        (runtime.structural_integrity, "audit_structural_integrity"),
        (runtime.test_profiles, "group_status"),
        (runtime.test_profiles, "section_status"),
        (scripts.audit_sanitization, "audit"),
    ):
        monkeypatch.setattr(module, name, valid)
    completion = {"schema_version": "test.completion/1.0", "complete": True}
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/completion_status.json").write_text(json.dumps(completion), encoding="utf-8")
    monkeypatch.setattr(
        __import__("scripts.build_completion_status", fromlist=["build"]),
        "build",
        lambda root: completion,
    )
    result = clean_source_export._certification_preflight(tmp_path, ())
    assert result["valid"] is True
    assert result["failed"] == []
    assert len(result["checks"]) == 14


def test_candidate_publication_does_not_rewrite_sealed_envelope(
    monkeypatch, tmp_path: Path
) -> None:
    envelope = tmp_path / "registry/registry_envelope_inventory.json"
    envelope.parent.mkdir(parents=True)
    envelope.write_bytes(b"sealed-envelope\n")

    monkeypatch.setattr(
        runtime.test_profiles,
        "section_status",
        lambda root: {"valid": True, "sections": []},
    )
    monkeypatch.setattr(clean_source_export, "_run_candidate_command", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime.evidence_index, "publish_index", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        __import__("scripts.build_completion_status", fromlist=["build"]),
        "build",
        lambda root: {"schema_version": "test/1.0"},
    )

    clean_source_export._certify_candidate_bytes(tmp_path, ())

    assert envelope.read_bytes() == b"sealed-envelope\n"
    assert (tmp_path / "registry/completion_status.json").is_file()


def test_candidate_commands_disable_bytecode_and_user_site(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(clean_source_export.subprocess, "run", run)

    clean_source_export._run_candidate_command(
        tmp_path, "validate", timeout=17
    )

    environment = captured["env"]
    assert environment["PYTHONDONTWRITEBYTECODE"] == "1"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONPATH"] == str(tmp_path)
    assert captured["timeout"] == 17
