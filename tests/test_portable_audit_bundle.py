from __future__ import annotations

from pathlib import Path
import json
import zipfile

from runtime.portable_audit_bundle import (
    build_portable_audit_bundle,
    verify_portable_audit_bundle,
)


def test_bundle_reconstructs_and_verifies_without_source_roots(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "report.json").write_text('{"valid":true}\n', encoding="utf-8")
    (source / "screen.png").write_bytes(b"not-a-real-image")
    prerequisite = tmp_path / "readiness.json"
    prerequisite.write_text('{"classification":"ready"}\n', encoding="utf-8")
    attestation = tmp_path / "attestation.json"
    attestation.write_text('{"signed":false}\n', encoding="utf-8")
    output = tmp_path / "delivery" / "audit.zip"
    checksum = tmp_path / "delivery" / "audit.zip.sha256"
    result = build_portable_audit_bundle(
        {"engine-evidence": source},
        output_zip=output,
        checksum_path=checksum,
        prerequisites=prerequisite,
        attestation=attestation,
    )
    assert result["file_count"] == 2
    source.rename(tmp_path / "source-removed")
    verified = verify_portable_audit_bundle(output, checksum)
    assert verified["valid"] is True
    assert verified["file_count"] == 2


def test_external_checksum_tampering_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("one", encoding="utf-8")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_text("{}", encoding="utf-8")
    bundle = tmp_path / "out" / "audit.zip"
    checksum = tmp_path / "out" / "audit.sha256"
    build_portable_audit_bundle(
        {"evidence": source},
        output_zip=bundle,
        checksum_path=checksum,
        prerequisites=prerequisites,
    )
    checksum.write_text(f"{'0' * 64}  {bundle.name}\n", encoding="ascii")
    report = verify_portable_audit_bundle(bundle, checksum)
    assert report["valid"] is False
    assert "external bundle checksum mismatch" in report["errors"]


def test_payload_tampering_is_rejected_even_with_recomputed_outer_hash(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.txt").write_text("one", encoding="utf-8")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_text("{}", encoding="utf-8")
    bundle = tmp_path / "out" / "audit.zip"
    checksum = tmp_path / "out" / "audit.sha256"
    build_portable_audit_bundle(
        {"evidence": source},
        output_zip=bundle,
        checksum_path=checksum,
        prerequisites=prerequisites,
    )
    with zipfile.ZipFile(bundle, "a") as archive:
        archive.writestr("payload/evidence/one.txt", b"two")
    import hashlib

    checksum.write_text(
        f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n",
        encoding="ascii",
    )
    report = verify_portable_audit_bundle(bundle, checksum)
    assert report["valid"] is False
    assert "duplicate archive member" in report["errors"]


def test_clean_bundle_excludes_dependencies_runtime_state_and_env_values(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    (source / "node_modules" / "pkg").mkdir(parents=True)
    (source / ".engineering-bootstrap" / "operation-bus").mkdir(parents=True)
    (source / "node_modules" / "pkg" / "index.js").write_text("dependency")
    (source / ".engineering-bootstrap" / "operation-bus" / "events.jsonl").write_text(
        "volatile"
    )
    (source / ".env.local").write_text("SECRET=must-not-ship\n", encoding="utf-8")
    (source / "tracked.txt").write_text("safe\n", encoding="utf-8")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_text("{}", encoding="utf-8")
    bundle = tmp_path / "out" / "audit.zip"
    checksum = tmp_path / "out" / "audit.sha256"

    result = build_portable_audit_bundle(
        {"source": source},
        output_zip=bundle,
        checksum_path=checksum,
        prerequisites=prerequisites,
    )

    assert result["file_count"] == 1
    with zipfile.ZipFile(bundle) as archive:
        assert "payload/source/tracked.txt" in archive.namelist()
        manifest = json.loads(archive.read("AUDIT_MANIFEST.json"))
    assert manifest["excluded_count"] == 3
    reasons = {item["reason"] for item in manifest["excluded"]}
    assert reasons == {
        "generated-or-dependency-directory",
        "secret-bearing-environment-file",
        "volatile-runtime-state",
    }
