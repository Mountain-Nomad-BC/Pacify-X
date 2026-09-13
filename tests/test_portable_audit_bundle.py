from __future__ import annotations

from pathlib import Path
import json
import hashlib
import os
import zipfile
import pytest

from runtime.portable_audit_bundle import (
    build_portable_audit_bundle,
    verify_portable_audit_bundle,
)


def _forged_bundle(tmp_path, mutation):
    data = b"one"
    record = {
        "label": "evidence",
        "path": "one.txt",
        "archive_path": "payload/evidence/one.txt",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    manifest = {
        "schema_version": "px.portable-audit-manifest/1.0",
        "files": [record],
        "file_count": 1,
        "payload_bytes": 3,
        "excluded": [],
        "excluded_count": 0,
        "prerequisites_sha256": hashlib.sha256(b"{}").hexdigest(),
        "attestation_sha256": None,
    }
    payloads = {record["archive_path"]: data}
    if mutation == "empty":
        manifest.update(files=[], file_count=0, payload_bytes=0)
        payloads = {}
    elif mutation == "duplicate":
        manifest.update(files=[record, dict(record)], file_count=2, payload_bytes=6)
    elif mutation == "bool-count":
        manifest["file_count"] = True
    elif mutation == "wrong-bytes":
        manifest["payload_bytes"] = 42
    elif mutation == "wrong-exclusion-count":
        manifest["excluded_count"] = 1
    elif mutation == "unsafe-record-path":
        record["path"] = "../one.txt"
    elif mutation == "mismatched-label":
        record["label"] = "different"
    elif mutation == "wrong-schema":
        manifest["schema_version"] = "unknown"
    elif mutation == "list-root":
        manifest = []
    bundle = tmp_path / "forged.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.writestr("AUDIT_MANIFEST.json", json.dumps(manifest))
        archive.writestr("PREREQUISITES.json", b"{}")
        for name, body in payloads.items():
            archive.writestr(name, body)
    checksum = tmp_path / "forged.sha256"
    checksum.write_text(
        hashlib.sha256(bundle.read_bytes()).hexdigest() + "  forged.zip\n",
        encoding="ascii",
    )
    return bundle, checksum


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "duplicate",
        "bool-count",
        "wrong-bytes",
        "wrong-exclusion-count",
        "unsafe-record-path",
        "mismatched-label",
        "wrong-schema",
        "list-root",
    ],
)
def test_audit_verification_rejects_self_consistent_but_invalid_manifest(
    tmp_path, mutation
):
    bundle, checksum = _forged_bundle(tmp_path, mutation)
    result = verify_portable_audit_bundle(bundle, checksum)
    assert not result["valid"]
    assert result["errors"]


def test_outer_checksum_failure_stops_before_zip_parsing(tmp_path, monkeypatch):
    bundle, checksum = _forged_bundle(tmp_path, "valid")
    checksum.write_text("0" * 64 + "  forged.zip\n", encoding="ascii")

    def forbidden(*args, **kwargs):
        raise AssertionError("unverified container must not be parsed")

    monkeypatch.setattr("runtime.portable_audit_bundle.zipfile.ZipFile", forbidden)
    result = verify_portable_audit_bundle(bundle, checksum)
    assert not result["valid"]


def test_audit_missing_inputs_return_structured_invalid_result(tmp_path):
    result = verify_portable_audit_bundle(
        tmp_path / "missing.zip", tmp_path / "missing.sha256"
    )
    assert not result["valid"] and result["errors"]


@pytest.mark.parametrize(
    "kind", ["not-mapping", "too-many", "bad-label", "bad-path", "bad-output"]
)
def test_audit_request_shape_fails_before_any_filesystem_access(
    tmp_path, monkeypatch, kind
):
    inputs = {"evidence": tmp_path / "source"}
    output = tmp_path / "output.zip"
    if kind == "not-mapping":
        inputs = [tmp_path]
    elif kind == "too-many":
        inputs = {f"input{i}": tmp_path for i in range(65)}
    elif kind == "bad-label":
        inputs = {"../bad": tmp_path}
    elif kind == "bad-path":
        inputs = {"evidence": "source"}
    else:
        output = "output.zip"
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda *a, **k: pytest.fail("invalid request touched filesystem"),
    )
    with pytest.raises(ValueError):
        build_portable_audit_bundle(
            inputs,
            output_zip=output,
            checksum_path=tmp_path / "output.sha256",
            prerequisites=tmp_path / "prerequisites.json",
        )


def test_audit_exclusions_are_portable_and_do_not_scan_quarantine(
    tmp_path, monkeypatch
):
    source = tmp_path / "source"
    (source / "NODE_MODULES").mkdir(parents=True)
    (source / "quarantine").mkdir()
    (source / "NODE_MODULES/dependency.js").write_text("dependency", encoding="utf-8")
    (source / ".ENV.local").write_text("SECRET=fixture\n", encoding="utf-8")
    (source / "safe.txt").write_text("safe\n", encoding="utf-8")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_text("{}", encoding="utf-8")
    original = os.scandir

    def refuse_quarantine(path):
        if Path(path) == source / "quarantine":
            raise AssertionError("quarantine must be pruned before enumeration")
        return original(path)

    monkeypatch.setattr(os, "scandir", refuse_quarantine)
    result = build_portable_audit_bundle(
        {"source": source},
        output_zip=tmp_path / "out/a.zip",
        checksum_path=tmp_path / "out/a.sha256",
        prerequisites=prerequisites,
    )
    assert result["file_count"] == 1


def test_audit_original_root_link_is_rejected_before_resolution(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "safe.txt").write_text("safe", encoding="utf-8")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_text("{}", encoding="utf-8")
    linked_source = tmp_path / "linked-root"
    if __import__("os").name == "nt":
        import _winapi

        _winapi.CreateJunction(str(source), str(linked_source))
    else:
        linked_source.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match="link"):
        build_portable_audit_bundle(
            {"source": linked_source},
            output_zip=tmp_path / "out/a.zip",
            checksum_path=tmp_path / "out/a.sha256",
            prerequisites=prerequisites,
        )


def test_complete_audit_envelope_budget_is_checked_before_payload_reads(
    tmp_path, monkeypatch
):
    from runtime.archive_io import ArchiveLimits

    source = tmp_path / "source"
    source.mkdir()
    payload = source / "body.txt"
    payload.write_bytes(b"small")
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_bytes(b"{}")
    original = Path.open

    def guarded(path, *args, **kwargs):
        if path == payload:
            raise AssertionError(
                "metadata already exceeds the complete envelope budget"
            )
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    with pytest.raises(ValueError, match="budget"):
        build_portable_audit_bundle(
            {"source": source},
            output_zip=tmp_path / "out/a.zip",
            checksum_path=tmp_path / "out/a.sha256",
            prerequisites=prerequisites,
            limits=ArchiveLimits(max_expanded_bytes=128),
        )


def test_private_key_markers_are_rejected_under_the_declared_content_policy(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "unexpected.txt").write_bytes(
        b"-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----\n"
    )
    prerequisites = tmp_path / "ready.json"
    prerequisites.write_bytes(b"{}")
    with pytest.raises(ValueError, match="private-key content"):
        build_portable_audit_bundle(
            {"source": source},
            output_zip=tmp_path / "out/a.zip",
            checksum_path=tmp_path / "out/a.sha256",
            prerequisites=prerequisites,
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


def test_payload_tampering_is_rejected_even_with_recomputed_outer_hash(
    tmp_path: Path,
) -> None:
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
