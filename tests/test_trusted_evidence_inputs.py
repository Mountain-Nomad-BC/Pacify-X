from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from runtime import trusted_evidence as te
from runtime.admission_controller import review_authoritative
from tests.test_trust_boundaries import _authority

KINDS = {
    "policy_decision": {"allowed": True},
    "postcondition": {"postconditions": {"check": True}},
    "provenance": {"verified": True},
    "license": {"reviewed": True, "allowed": True},
    "tests": {"passed": True},
    "security": {"malicious_or_unsafe": False},
    "transfer_sanitization": {"accepted": True},
    "human_approval": {"accepted": True},
    "destination_ownership": {"accepted": True},
    "transfer_tests": {"accepted": True},
}


@pytest.fixture
def authority(tmp_path):
    key, policy, identity, publisher = _authority(tmp_path)
    value = json.loads(policy.read_text(encoding="utf-8"))
    value["trusted_signers"][0]["evidence_producers"] = {"reviewer": list(KINDS)}
    policy.write_text(json.dumps(value), encoding="utf-8")
    store = tmp_path / "evidence/store"
    store.mkdir(parents=True)
    return tmp_path, key, policy, identity, publisher, store


def record(kind="security"):
    value = {
        "schema_version": "1.0",
        "evidence_id": "record",
        "evidence_type": kind,
        "producer": "reviewer",
        "project_id": "destination",
        "subject_id": "subject",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "result": copy.deepcopy(KINDS[kind]),
    }
    if kind in {
        "transfer_sanitization",
        "human_approval",
        "destination_ownership",
        "transfer_tests",
    }:
        value.update(source_project_id="source", destination_project_id="destination")
    return value


def signed(authority, value):
    _, key, _, identity, publisher, store = authority
    path = store / "record.json"
    result = te.sign_evidence_record(
        value,
        private_key=key,
        signature_path=path.with_suffix(".json.sig"),
        identity=identity,
        publisher=publisher,
    )
    path.write_text(json.dumps(result), encoding="utf-8")
    return path


def resolve(authority, **kwargs):
    options = {
        "scope": te.EvidenceScope("destination", "subject"),
        "accepted_producers": {"reviewer"},
        "max_age_seconds": 3600,
    }
    options.update(kwargs)
    return te.TrustedEvidenceResolver(authority[-1], authority[2]).resolve(
        "evidence:record", **options
    )


def test_signed_future_evidence_is_not_current(authority):
    from datetime import timedelta
    value = record()
    value['created_at'] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    signed(authority, value)
    assert resolve(authority).fresh is False


def test_reused_resolver_evaluates_current_clock_each_operation(authority, monkeypatch):
    from datetime import timedelta
    issued = datetime.now(timezone.utc)
    value = record()
    value['created_at'] = issued.isoformat()
    signed(authority, value)
    current = [issued]
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0]
    monkeypatch.setattr(te, 'datetime', Clock)
    resolver = te.TrustedEvidenceResolver(authority[-1], authority[2])
    options = dict(scope=te.EvidenceScope('destination', 'subject'),
                   accepted_producers={'reviewer'}, max_age_seconds=60)
    assert resolver.resolve('evidence:record', **options).verified
    current[0] += timedelta(seconds=61)
    assert resolver.resolve('evidence:record', **options).fresh is False


@pytest.mark.parametrize("kind", list(KINDS))
def test_real_signed_record_types_remain_usable(authority, kind):
    signed(authority, record(kind))
    assert resolve(authority, required_type=kind).verified


@pytest.mark.parametrize(
    "case",
    [
        "missing_security",
        "string_security",
        "null_security",
        "integer_security",
        "array_result",
        "missing_license_allowed",
        "string_test",
        "empty_postconditions",
        "string_postcondition",
        "string_effects",
        "duplicate_effects",
        "null_approval",
        "transfer_source_missing",
        "transfer_destination_missing",
        "identity_alias",
        "empty_subject",
        "integer_project",
        "unknown_type",
        "extra_field",
        "bad_timestamp",
    ],
)
def test_authentic_malformed_assessments_cannot_become_authority(authority, case):
    value = record()
    if case == "missing_security":
        value["result"] = {}
    elif case == "string_security":
        value["result"]["malicious_or_unsafe"] = "false"
    elif case == "null_security":
        value["result"]["malicious_or_unsafe"] = None
    elif case == "integer_security":
        value["result"]["malicious_or_unsafe"] = 0
    elif case == "array_result":
        value["result"] = []
    elif case == "missing_license_allowed":
        value = record("license")
        value["result"].pop("allowed")
    elif case == "string_test":
        value = record("tests")
        value["result"]["passed"] = "yes"
    elif case == "empty_postconditions":
        value = record("postcondition")
        value["result"]["postconditions"] = {}
    elif case == "string_postcondition":
        value = record("postcondition")
        value["result"]["postconditions"]["check"] = "true"
    elif case == "string_effects":
        value = record("policy_decision")
        value["result"]["approved_effects"] = "read_local"
    elif case == "duplicate_effects":
        value = record("policy_decision")
        value["result"]["approved_effects"] = ["read_local"] * 2
    elif case == "null_approval":
        value = record("policy_decision")
        value["result"]["approval_id"] = None
    elif case == "transfer_source_missing":
        value = record("transfer_tests")
        value.pop("source_project_id")
    elif case == "transfer_destination_missing":
        value = record("transfer_tests")
        value.pop("destination_project_id")
    elif case == "identity_alias":
        value["evidence_id"] = "different"
    elif case == "empty_subject":
        value["subject_id"] = ""
    elif case == "integer_project":
        value["project_id"] = 123
    elif case == "unknown_type":
        value["evidence_type"] = "unknown"
    elif case == "extra_field":
        value["undeclared"] = True
    elif case == "bad_timestamp":
        value["created_at"] = "2026-09-09"
    signed(authority, value)
    assert not resolve(authority).verified


@pytest.mark.parametrize(
    "case",
    [
        "missing_grants",
        "wrong_producer",
        "wrong_type",
        "string_grants",
        "duplicate_types",
        "unknown_type",
        "injected_principal",
        "duplicate_signer",
        "revoked",
    ],
)
def test_caller_allowlist_cannot_expand_signer_authority(authority, case):
    signed(authority, record())
    policy = authority[2]
    value = json.loads(policy.read_text(encoding="utf-8"))
    signer = value["trusted_signers"][0]
    if case == "missing_grants":
        signer.pop("evidence_producers")
    elif case == "wrong_producer":
        signer["evidence_producers"] = {"other": ["security"]}
    elif case == "wrong_type":
        signer["evidence_producers"] = {"reviewer": ["tests"]}
    elif case == "string_grants":
        signer["evidence_producers"] = "reviewer"
    elif case == "duplicate_types":
        signer["evidence_producers"] = {"reviewer": ["security", "security"]}
    elif case == "unknown_type":
        signer["evidence_producers"] = {"reviewer": ["unknown"]}
    elif case == "injected_principal":
        signer["identity"] += "\nother"
    elif case == "duplicate_signer":
        value["trusted_signers"].append(copy.deepcopy(signer))
    elif case == "revoked":
        value["revoked_fingerprints"] = [signer["fingerprint"]]
    policy.write_text(json.dumps(value), encoding="utf-8")
    assert not resolve(authority, accepted_producers={"reviewer"}).verified


@pytest.mark.parametrize(
    "raw",
    [
        b"[]",
        b"null",
        b'{"a":1,"a":2}',
        b'{"x":NaN}',
        b'{"x":' + b"[" * 40 + b"0" + b"]" * 40 + b"}",
        b" " * (1024 * 1024 + 1),
    ],
    ids=["array", "null", "duplicate-key", "nonfinite", "depth-limit", "byte-limit"],
)
def test_invalid_record_images_refuse_without_native_verification(
    authority, monkeypatch, raw
):
    (authority[-1] / "record.json").write_bytes(raw)
    monkeypatch.setattr(
        te,
        "_verify_signature",
        lambda *args: pytest.fail("native verification before record admission"),
    )
    assert not resolve(authority).verified


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_age_seconds", True),
        ("max_age_seconds", 1.5),
        ("max_age_seconds", 0),
        ("max_age_seconds", -1),
        ("max_age_seconds", 31536001),
        ("expected_sha256", ""),
        ("expected_sha256", 1),
        ("accepted_producers", "reviewer"),
        ("accepted_producers", set()),
        ("scope", te.EvidenceScope("", "subject")),
    ],
)
def test_invalid_resolution_requests_do_not_acquire_records(
    authority, monkeypatch, field, value
):
    signed(authority, record())
    monkeypatch.setattr(
        Path, "read_bytes", lambda *args: pytest.fail("body read for malformed request")
    )
    result = resolve(authority, **{field: value})
    assert not result.verified


def test_untrusted_record_does_not_read_directed_artifact(authority, monkeypatch):
    artifact = authority[-1] / "artifact.bin"
    artifact.write_bytes(b"content")
    value = record()
    value["artifact"] = {
        "path": "artifact.bin",
        "sha256": hashlib.sha256(b"content").hexdigest(),
    }
    signed(authority, value)
    policy = authority[2]
    p = json.loads(policy.read_text(encoding="utf-8"))
    p["trusted_signers"][0].pop("evidence_producers")
    policy.write_text(json.dumps(p), encoding="utf-8")
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != artifact, "unauthenticated evidence directed an artifact read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert not resolve(authority).verified


def test_actual_artifact_hash_is_required(authority):
    artifact = authority[-1] / "artifact.bin"
    artifact.write_bytes(b"content")
    value = record()
    value["artifact"] = {
        "path": "artifact.bin",
        "sha256": hashlib.sha256(b"content").hexdigest(),
    }
    signed(authority, value)
    assert resolve(authority).verified
    artifact.write_bytes(b"changed")
    assert not resolve(authority).verified


@pytest.mark.parametrize(
    "relative", ["../evidence/store", "evidence/../evidence/store", ".", "", 1]
)
def test_store_original_path_is_not_normalized_into_acceptance(authority, relative):
    helper = getattr(te, "evidence_store_path", None)
    assert callable(helper), "shared original-path evidence boundary is missing"
    with pytest.raises((OSError, ValueError, TypeError)):
        helper(authority[0], relative)


def test_missing_security_flag_cannot_admit_candidate(authority):
    root, key, _, identity, publisher, store = authority
    manifest = {
        "id": "subject",
        "version": "1",
        "owner": "owner",
        "provides": ["report"],
        "consumes": [],
        "effects": ["read_local"],
        "dependencies": [],
    }
    (root / 'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'assessment.json').write_text(json.dumps({'required_evidence':['provenance','license','tests','security']}), encoding='utf-8')
    binding, _, _ = te.acquire_evaluation_binding(root, subject_source='candidate.json',
        assessment_contract='assessment.json', interpretation='candidate-assessments/1')
    for kind in ["provenance", "license", "tests", "security"]:
        value = record(kind)
        value["evidence_id"] = kind
        value.update(schema_version="2.0", evaluation=binding)
        if kind == "security":
            value["result"] = {}
        value = te.sign_evidence_record(
            value,
            private_key=key,
            signature_path=store / (kind + ".json.sig"),
            identity=identity,
            publisher=publisher,
        )
        (store / (kind + ".json")).write_text(json.dumps(value), encoding="utf-8")
    request = {
        "schema_version":"2.0", "subject_source":"candidate.json", "assessment_contract":"assessment.json",
        "project_id": "destination",
        "evidence_store": "evidence/store",
        "accepted_producers": ["reviewer"],
        "evidence_refs": {
            kind: "evidence:" + kind
            for kind in ["provenance", "license", "tests", "security"]
        },
    }
    decision = review_authoritative(root, manifest, request)
    assert not decision.accepted and not decision.authoritative

    assert decision.request_valid and len(decision.verified_evidence_ids) == 3


@pytest.mark.parametrize("kind", ["trust", "signature", "duplicate_trust"])
def test_signature_inputs_refuse_before_native_work(authority, monkeypatch, kind):
    signed(authority, record())
    if kind == "trust":
        policy = authority[2]
        raw = policy.read_bytes()
        policy.write_bytes(raw + b" " * (1024 * 1024 + 1 - len(raw)))
    elif kind == "signature":
        (authority[-1] / "record.json.sig").write_bytes(b"x" * (64 * 1024 + 1))
    else:
        policy = authority[2]
        raw = policy.read_bytes()
        policy.write_bytes(b'{"trusted_signers": [],' + raw[1:])
    monkeypatch.setattr(
        te.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail(
            "native verifier reached before input admission"
        ),
    )
    assert not resolve(authority).verified


@pytest.mark.parametrize(
    "reference",
    [None, 1, [], "evidence:" + "x" * 129, "evidence:..", "evidence:.hidden"],
)
def test_reference_shape_is_bounded_before_resolution(authority, reference):
    resolver = te.TrustedEvidenceResolver(authority[-1], authority[2])
    result = resolver.resolve(
        reference,
        scope=te.EvidenceScope("destination", "subject"),
        accepted_producers={"reviewer"},
    )
    assert not result.resolved and "invalid_evidence_reference" in result.reasons


def test_oversized_artifact_refuses_before_body_acquisition(authority, monkeypatch):
    artifact = authority[-1] / "artifact.bin"
    with artifact.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024 + 1)
    value = record()
    value["artifact"] = {"path": "artifact.bin", "sha256": "0" * 64}
    signed(authority, value)
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != artifact, "oversized artifact body was opened"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    assert not resolve(authority).verified
