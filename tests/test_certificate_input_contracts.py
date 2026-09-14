"""Causal certificate locator, authentication and immutable-input contracts.

Most collaborator fixtures isolate a boundary and do not prove cryptography.
Explicit native tests use real OpenSSH and disposable keys under the owned runner.
"""

import base64
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import runtime.input_files as inputs
import runtime.release_certification as certifier
import runtime.release_signing as signing
import runtime.coverage_assurance as coverage_owner
from tests.test_coverage_assurance import _write_fixture
from tests.test_release_identity_controls import _signing_fixture


def _json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _junction(path, target):
    if os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(path))
    else:
        path.symlink_to(target, target_is_directory=True)


def _forbid(*args, **kwargs):
    raise AssertionError("a rejected input must not reach dependent work")


def _mock_certificate(root, monkeypatch):
    release = "1.2.3"
    folder = root / "evidence/releases" / release
    run = folder / "run-1"
    run.mkdir(parents=True)
    evidence = run / "evidence-manifest.json"
    _json(evidence, {"marker": "original"})
    artifact_manifest = run / "artifact-manifest.json"
    _json(artifact_manifest, {"manifest_sha256": "3" * 64, "records": []})
    (folder / "certificate.json.sig").write_bytes(b"isolated mocked signature seam")
    artifacts = root / "artifacts"
    artifacts.mkdir()
    raw = b"isolated artifact file consistency; format binding is mocked"
    filename = "fixture-1.2.3-py3-none-any.whl"
    (artifacts / filename).write_bytes(raw)
    value = {
        "release": release,
        "status": "self_certified",
        "run_id": "run-1",
        "signature": {"path": "certificate.json.sig"},
        "source_control": {},
        "certification_platform": {},
        "product_digest": "1" * 64,
        "harness_digest": "2" * 64,
        "coverage_evidence": f"evidence/releases/{release}/run-1/coverage.json",
        "coverage_evidence_sha256": "4" * 64,
        "evidence_manifest": evidence.relative_to(root).as_posix(),
        "evidence_manifest_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "artifact_manifest": artifact_manifest.relative_to(root).as_posix(),
        "artifact_manifest_sha256": "3" * 64,
        "artifacts": [
            {
                "type": "wheel",
                "filename": filename,
                "size_bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        ],
    }
    path = folder / "certificate.json"
    _json(path, value)
    for name in [
        "validate_certification_platform",
        "validate_version_surfaces",
        "verify_recorded_git_identity",
        "_verify_coverage_binding",
        "verify_evidence_manifest",
    ]:
        monkeypatch.setattr(
            certifier, name, lambda *a, **k: {"valid": True, "errors": []}
        )
    monkeypatch.setattr(
        certifier,
        "verify_certificate_signature",
        lambda *a, **k: {"valid": True, "errors": [], "identity": "mocked"},
    )
    monkeypatch.setattr(
        certifier,
        "classify_tree",
        lambda *a, **k: {
            "valid": True,
            "errors": [],
            "product_digest": "1" * 64,
            "harness_digest": "2" * 64,
        },
    )
    monkeypatch.setattr(
        certifier,
        "bind_artifact_set",
        lambda *a, **k: {
            "valid": True,
            "errors": [],
            "artifact_manifest_sha256": "3" * 64,
        },
    )
    monkeypatch.setattr(certifier, "_certificate_ledger_errors", lambda *a, **k: [])
    # This fixture isolates artifact/authentication/input-image boundaries. The
    # release report owner has independent unmocked integration cases below.
    monkeypatch.setattr(certifier, "_verify_release_gate_binding", lambda *a, **k: [])
    return path, value, artifacts


def test_actual_artifact_bytes_preserve_isolated_verifier_binding(
    tmp_path, monkeypatch
):
    _, _, artifacts = _mock_certificate(tmp_path, monkeypatch)
    result = certifier.verify_release_certificate(
        tmp_path, release="1.2.3", artifact_dir=artifacts
    )
    assert result["valid"], result["errors"]
    next(artifacts.iterdir()).write_bytes(b"changed bytes")
    assert (
        certifier.verify_release_certificate(
            tmp_path, release="1.2.3", artifact_dir=artifacts
        )["valid"]
        is False
    )


@pytest.mark.parametrize(
    "result",
    [
        {"valid": False, "errors": []},
        {"errors": []},
        {"valid": 1, "errors": []},
        {"valid": False, "errors": ["bad signature"]},
    ],
)
def test_failed_or_implicit_authentication_stops_all_dependents(
    tmp_path, monkeypatch, result
):
    _, _, artifacts = _mock_certificate(tmp_path, monkeypatch)
    monkeypatch.setattr(
        certifier, "verify_certificate_signature", lambda *a, **k: result
    )
    for name in [
        "validate_certification_platform",
        "validate_version_surfaces",
        "verify_recorded_git_identity",
        "classify_tree",
        "_verify_coverage_binding",
        "verify_evidence_manifest",
        "verify_artifact_records",
        "bind_artifact_set",
    ]:
        monkeypatch.setattr(certifier, name, _forbid)
    result = certifier.verify_release_certificate(
        tmp_path, release="1.2.3", artifact_dir=artifacts
    )
    assert result["valid"] is False and result["errors"]


@pytest.mark.parametrize(
    "release",
    [True, {}, [], "", "../outside", "1.2.3/../../outside", "1.2.3\n", "x" * 4097],
)
def test_original_release_contract_precedes_file_bodies(tmp_path, monkeypatch, release):
    monkeypatch.setattr(Path, "open", _forbid)
    result = certifier.verify_release_certificate(tmp_path, release=release)
    assert result["valid"] is False


def test_original_linked_certificate_root_precedes_body(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.mkdir()
    _mock_certificate(actual, monkeypatch)
    link = tmp_path / "linked"
    _junction(link, actual)
    monkeypatch.setattr(Path, "open", _forbid)
    assert certifier.verify_release_certificate(link, release="1.2.3")["valid"] is False


@pytest.mark.parametrize("field", ["evidence_manifest", "artifact_manifest"])
def test_traversal_with_valid_lexical_release_prefix_precedes_outside_read(
    tmp_path, monkeypatch, field
):
    path, value, artifacts = _mock_certificate(tmp_path, monkeypatch)
    outside = tmp_path / "evidence/outside.json"
    _json(outside, {"marker": "outside", "manifest_sha256": "3" * 64})
    value[field] = "evidence/releases/1.2.3/../../outside.json"
    value[field + "_sha256"] = (
        hashlib.sha256(outside.read_bytes()).hexdigest()
        if field == "evidence_manifest"
        else "3" * 64
    )
    _json(path, value)
    original = Path.open

    def checked(p, *a, **k):
        if p.resolve() == outside.resolve():
            return _forbid()
        return original(p, *a, **k)

    monkeypatch.setattr(Path, "open", checked)
    assert (
        certifier.verify_release_certificate(
            tmp_path, release="1.2.3", artifact_dir=artifacts
        )["valid"]
        is False
    )


@pytest.mark.parametrize(
    "name", ["../outside.sig", "/outside.sig", "nested/signature.sig", True, []]
)
def test_signature_locator_refuses_before_authenticator(tmp_path, monkeypatch, name):
    path, value, artifacts = _mock_certificate(tmp_path, monkeypatch)
    value["signature"]["path"] = name
    _json(path, value)
    monkeypatch.setattr(certifier, "verify_certificate_signature", _forbid)
    assert (
        certifier.verify_release_certificate(
            tmp_path, release="1.2.3", artifact_dir=artifacts
        )["valid"]
        is False
    )


def test_oversized_certificate_refuses_before_body(tmp_path, monkeypatch):
    path = tmp_path / "evidence/releases/1.2.3/certificate.json"
    path.parent.mkdir(parents=True)
    with path.open("wb") as stream:
        stream.truncate(8 * 1024 * 1024 + 1)
    monkeypatch.setattr(Path, "open", _forbid)
    assert (
        certifier.verify_release_certificate(tmp_path, release="1.2.3")["valid"]
        is False
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b'{"release":"1.2.3","release":"1.2.3"}',
        b'{"x":NaN}',
        b'{"x":' + b"[" * 65 + b"0" + b"]" * 65 + b"}",
    ],
)
def test_certificate_json_shape_is_bounded_and_unambiguous(tmp_path, raw):
    path = tmp_path / "evidence/releases/1.2.3/certificate.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    assert (
        certifier.verify_release_certificate(tmp_path, release="1.2.3")["valid"]
        is False
    )


def test_evidence_manifest_is_parsed_from_the_hashed_image(tmp_path, monkeypatch):
    _, value, artifacts = _mock_certificate(tmp_path, monkeypatch)
    evidence = tmp_path / value["evidence_manifest"]
    original = Path.open
    opens = []
    observed = []

    def checked(p, *a, **k):
        if p == evidence and "r" in (a[0] if a else k.get("mode", "r")):
            opens.append(p)
            if len(opens) == 2:
                with original(p, "wb") as stream:
                    stream.write(b'{"marker":"replacement"}')
        return original(p, *a, **k)

    monkeypatch.setattr(Path, "open", checked)

    def verify_manifest(folder, manifest):
        observed.append(manifest["marker"])
        return {"valid": True, "errors": []}

    monkeypatch.setattr(certifier, "verify_evidence_manifest", verify_manifest)
    result = certifier.verify_release_certificate(
        tmp_path, release="1.2.3", artifact_dir=artifacts
    )
    assert result["valid"], result["errors"]
    assert observed == ["original"] and len(opens) == 1


def test_coverage_and_policy_hashes_describe_evaluated_images(tmp_path, monkeypatch):
    path = _write_fixture(tmp_path)
    policy = tmp_path / "policies/coverage-assurance.json"
    expected_coverage = hashlib.sha256(path.read_bytes()).hexdigest()
    expected_policy = hashlib.sha256(policy.read_bytes()).hexdigest()
    loads = json.loads

    def changed(raw, *a, **k):
        value = loads(raw, *a, **k)
        if type(value) is dict and "files" in value:
            path.write_text("{}", encoding="utf-8")
            policy.write_text("{}", encoding="utf-8")
        return value

    monkeypatch.setattr(json, "loads", changed)
    result = coverage_owner.validate_coverage_evidence(tmp_path, path)
    assert result["valid"], result["errors"]
    assert result["coverage_sha256"] == expected_coverage
    assert result["policy_sha256"] == expected_policy


def test_coverage_binding_compares_digest_returned_by_evaluator(tmp_path, monkeypatch):
    source = _write_fixture(tmp_path)
    target = tmp_path / "evidence/releases/1.2.3/run/coverage.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    certificate = {
        "coverage_evidence": target.relative_to(tmp_path).as_posix(),
        "coverage_evidence_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(
        certifier,
        "validate_coverage_evidence",
        lambda *a: {"valid": True, "errors": [], "coverage_sha256": "0" * 64},
    )
    assert (
        certifier._verify_coverage_binding(tmp_path, "1.2.3", certificate)["valid"]
        is False
    )


def test_coverage_traversal_refuses_before_outside_body(tmp_path, monkeypatch):
    source = _write_fixture(tmp_path)
    (tmp_path / "evidence/releases/1.2.3").mkdir(parents=True)
    (tmp_path / "evidence/outside.json").write_bytes(source.read_bytes())
    certificate = {
        "coverage_evidence": "evidence/releases/1.2.3/../../outside.json",
        "coverage_evidence_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(Path, "open", _forbid)
    assert (
        certifier._verify_coverage_binding(tmp_path, "1.2.3", certificate)["valid"]
        is False
    )


def test_coverage_supports_explicit_independent_owned_input(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    source = _write_fixture(root)
    outside = tmp_path / "coverage.json"
    outside.write_bytes(source.read_bytes())
    assert coverage_owner.validate_coverage_evidence(root, outside)["valid"]


@pytest.mark.parametrize(
    "relative,limit",
    [
        ("policies/coverage-assurance.json", 1024 * 1024),
        ("coverage.json", 64 * 1024 * 1024),
    ],
)
def test_coverage_preflights_both_sizes_before_any_body(
    tmp_path, monkeypatch, relative, limit
):
    path = _write_fixture(tmp_path)
    with (tmp_path / relative).open("wb") as stream:
        stream.truncate(limit + 1)
    monkeypatch.setattr(Path, "open", _forbid)
    assert coverage_owner.validate_coverage_evidence(tmp_path, path)["valid"] is False


def test_independent_file_preserves_external_input_and_refuses_original_links(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    source = target / "input.json"
    source.write_text("{}", encoding="utf-8")
    path, info = inputs.independent_file(source)
    assert path == source and info.st_size == 2
    linked = tmp_path / "linked"
    _junction(linked, target)
    with pytest.raises(ValueError):
        inputs.independent_file(linked / "input.json")


@pytest.mark.parametrize("value", ["input.json", True, None])
def test_independent_file_requires_actual_native_path(value):
    with pytest.raises(ValueError):
        inputs.independent_file(value)


def _mock_trust_fixture(root):
    # Structural fixture only: _run is mocked in these tests, never crypto proof.
    blob = b"\0\0\0\x0bssh-ed25519\0\0\0 " + bytes(32)
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(blob).digest()
    ).decode().rstrip("=")
    policy = {
        "trusted_signers": [
            {
                "fingerprint": fingerprint,
                "identity": "px-release",
                "publisher": "Test Publisher",
                "public_key": "ssh-ed25519 "
                + base64.b64encode(blob).decode()
                + " fixture",
            }
        ],
        "revoked_fingerprints": [],
    }
    path = root / "trust.json"
    _json(path, policy)
    signature = root / "certificate.json.sig"
    signature.write_bytes(b"original-signature-image")
    value = signing.bind_content_digest(
        {
            "release": "1.2.3",
            "signature": {
                "path": signature.name,
                "algorithm": "ssh-ed25519",
                "namespace": signing.SIGNING_NAMESPACE,
                "publisher": "Test Publisher",
                "key_fingerprint": fingerprint,
            },
        }
    )
    return path, policy, signature, value


@pytest.mark.parametrize(
    "kind",
    [
        "signers-object",
        "signers-empty",
        "signers-too-many",
        "signer-duplicate",
        "identity-injection",
        "key-injection",
        "key-fingerprint-mismatch",
        "revoked-object",
        "revoked-too-many",
        "revoked-nontext",
    ],
)
def test_invalid_trust_contract_precedes_native_verifier(tmp_path, monkeypatch, kind):
    path, policy, signature, value = _mock_trust_fixture(tmp_path)
    signer = policy["trusted_signers"][0]
    if kind == "signers-object":
        policy["trusted_signers"] = {}
    elif kind == "signers-empty":
        policy["trusted_signers"] = []
    elif kind == "signers-too-many":
        policy["trusted_signers"] = [signer] * 65
    elif kind == "signer-duplicate":
        policy["trusted_signers"].append(signer)
    elif kind == "identity-injection":
        signer["identity"] = "principal\n*"
    elif kind == "key-injection":
        signer["public_key"] += "\n* other"
    elif kind == "key-fingerprint-mismatch":
        signer["public_key"] = (
            "ssh-ed25519 "
            + base64.b64encode(
                b"\0\0\0\x0bssh-ed25519\0\0\0 " + bytes([1]) * 32
            ).decode()
        )
    elif kind == "revoked-object":
        policy["revoked_fingerprints"] = {}
    elif kind == "revoked-too-many":
        policy["revoked_fingerprints"] = ["SHA256:" + "a" * 43] * 513
    else:
        policy["revoked_fingerprints"] = [False]
    _json(path, policy)
    monkeypatch.setattr(signing, "_run", _forbid)
    result = signing.verify_certificate_signature(
        value, signature_path=signature, trust_policy_path=path
    )
    assert result["valid"] is False and result["errors"]


def test_native_verifier_receives_signature_snapshot_and_certificate_snapshot(
    tmp_path, monkeypatch
):
    path, _, signature, value = _mock_trust_fixture(tmp_path)
    original = signature.read_bytes()
    expected = signing.canonical_bytes(value)
    observed = []

    def run(command, *, stdin=None):
        signature.write_bytes(b"replaced original signature")
        value["release"] = "changed caller object"
        selected = Path(command[command.index("-s") + 1])
        observed.append((selected != signature, selected.read_bytes(), stdin))
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(signing, "_run", run)
    assert signing.verify_certificate_signature(
        value, signature_path=signature, trust_policy_path=path
    )["valid"]
    assert observed == [(True, original, expected)]


@pytest.mark.parametrize("target,limit", [("trust", 1024 * 1024), ("signature", 65536)])
def test_signature_input_budget_precedes_its_body(tmp_path, monkeypatch, target, limit):
    policy, _, signature, value = _mock_trust_fixture(tmp_path)
    selected = policy if target == "trust" else signature
    with selected.open("wb") as stream:
        stream.truncate(limit + 1)
    original = Path.open

    def checked(path, *a, **k):
        if path == selected:
            return _forbid()
        return original(path, *a, **k)

    monkeypatch.setattr(Path, "open", checked)
    monkeypatch.setattr(signing, "_run", _forbid)
    assert (
        signing.verify_certificate_signature(
            value, signature_path=signature, trust_policy_path=policy
        )["valid"]
        is False
    )


def test_actual_openssh_signature_verifies_after_original_file_replacement(
    tmp_path, monkeypatch
):
    root, private, policy, value = _signing_fixture()
    signature = root / "certificate.json.sig"
    certificate = signing.sign_certificate(
        value, private_key=private, signature_path=signature
    )
    real_run = signing._run

    def replace_before_native(command, *, stdin=None):
        signature.write_bytes(b"replacement is not the acquired signature")
        return real_run(command, stdin=stdin)

    monkeypatch.setattr(signing, "_run", replace_before_native)
    result = signing.verify_certificate_signature(
        certificate, signature_path=signature, trust_policy_path=policy
    )
    assert result["valid"], result["errors"]


@pytest.mark.parametrize("selected", ["signature", "trust"])
def test_original_linked_signature_or_trust_parent_refuses(
    tmp_path, monkeypatch, selected
):
    actual = tmp_path / "actual"
    actual.mkdir()
    policy, _, signature, value = _mock_trust_fixture(actual)
    linked = tmp_path / "linked"
    _junction(linked, actual)
    if selected == "signature":
        signature = linked / signature.name
    else:
        policy = linked / policy.name
    monkeypatch.setattr(signing, "_run", _forbid)
    assert (
        signing.verify_certificate_signature(
            value, signature_path=signature, trust_policy_path=policy
        )["valid"]
        is False
    )


def test_original_linked_coverage_policy_parent_refuses_before_body(
    tmp_path, monkeypatch
):
    actual = tmp_path / "actual"
    actual.mkdir()
    coverage = _write_fixture(actual)
    linked = tmp_path / "linked"
    _junction(linked, actual)
    monkeypatch.setattr(Path, "open", _forbid)
    assert coverage_owner.validate_coverage_evidence(linked, coverage)["valid"] is False


def test_linked_release_parent_refuses_before_certificate_body(tmp_path, monkeypatch):
    actual = tmp_path / "actual"
    actual.mkdir()
    _mock_certificate(actual, monkeypatch)
    root = tmp_path / "root"
    root.mkdir()
    _junction(root / "evidence", actual / "evidence")
    monkeypatch.setattr(Path, "open", _forbid)
    assert certifier.verify_release_certificate(root, release="1.2.3")["valid"] is False


def test_independent_file_rejects_original_parent_traversal(tmp_path):
    (tmp_path / "child").mkdir()
    (tmp_path / "input.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        inputs.independent_file(tmp_path / "child/../input.json")



def test_real_authentication_seam_stops_tampered_certificate_before_source(tmp_path, monkeypatch):
    path, value, artifacts = _mock_certificate(tmp_path, monkeypatch)
    _, private, trust, _ = _signing_fixture()
    policy = tmp_path / "policies/release-trust.json"
    policy.parent.mkdir()
    policy.write_bytes(trust.read_bytes())
    signature = path.parent / "certificate.json.sig"
    signed = signing.sign_certificate(value, private_key=private, signature_path=signature)
    _json(path, signed)
    monkeypatch.setattr(certifier, "verify_certificate_signature", signing.verify_certificate_signature)
    result = certifier.verify_release_certificate(tmp_path, release="1.2.3", artifact_dir=artifacts)
    assert result["valid"], result["errors"]
    signed["product_digest"] = "f" * 64
    _json(path, signed)
    monkeypatch.setattr(certifier, "verify_recorded_git_identity", _forbid)
    assert certifier.verify_release_certificate(tmp_path, release="1.2.3", artifact_dir=artifacts)["valid"] is False


@pytest.mark.parametrize("unknown_skip", [False, True])
def test_certificate_verifier_consumes_required_report_contract(tmp_path, monkeypatch, unknown_skip):
    from runtime.release_evidence import build_evidence_manifest
    from tests.test_release_certification import _complete_gate_summary_for_contract_test

    report_owner = certifier._verify_release_gate_binding
    certificate_path, certificate, artifacts = _mock_certificate(tmp_path, monkeypatch)
    monkeypatch.setattr(certifier, "_verify_release_gate_binding", report_owner)
    evidence = certificate_path.parent / "run-1"
    for name in certifier.REQUIRED_RELEASE_EVIDENCE:
        if not (evidence / name).exists():
            (evidence / name).write_bytes(b"{}")
    summary = _complete_gate_summary_for_contract_test()
    outcome = '<skipped message="unknown"/>' if unknown_skip else ''
    summary["gates"]["full_tests"].update(tests=2, skipped=int(unknown_skip))
    (evidence / "full-tests.junit.xml").write_text(
        '<testsuite><testcase classname="tests.example" name="executed"/><testcase classname="tests.example" name="case">' + outcome + '</testcase></testsuite>', encoding="utf-8")
    _json(evidence / "gate-summary.json", summary)
    manifest = build_evidence_manifest(evidence, roles={name: {"required": True} for name in certifier.REQUIRED_RELEASE_EVIDENCE})
    assert manifest["valid"], manifest["errors"]
    _json(evidence / "evidence-manifest.json", manifest)
    certificate.update(
        evidence_manifest_sha256=hashlib.sha256((evidence / "evidence-manifest.json").read_bytes()).hexdigest(),
        gate_summary="evidence/releases/1.2.3/run-1/gate-summary.json",
        gate_summary_sha256=hashlib.sha256((evidence / "gate-summary.json").read_bytes()).hexdigest(),
    )
    _json(certificate_path, certificate)
    result = certifier.verify_release_certificate(tmp_path, release="1.2.3", artifact_dir=artifacts)
    assert result["valid"] is (not unknown_skip), result["errors"]
    if unknown_skip:
        assert any("skip policy" in error for error in result["errors"])
