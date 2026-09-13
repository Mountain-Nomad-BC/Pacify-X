from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from runtime.admission_controller import review_authoritative
from runtime.execution_contract import authorize_with_policy_evidence
from runtime.outcome_verifier import verify_authoritative
from runtime.release_signing import public_key_fingerprint
from runtime.trusted_evidence import (
    EvidenceScope,
    TrustedEvidenceResolver,
    sign_evidence_record,
)


def _authority(root: Path) -> tuple[Path, Path, str, str]:
    root.mkdir(parents=True, exist_ok=True)
    key = root / "key"
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True
    )
    public = key.with_suffix(".pub").read_text(encoding="utf-8").split()
    identity, publisher = "test-authority@example", "test-authority"
    policy = root / "policies/effect-grant-trust.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "trusted_signers": [
                    {
                        "identity": identity,
                        "publisher": publisher,
                        "fingerprint": public_key_fingerprint(key.with_suffix(".pub")),
                        "public_key": " ".join(public[:2]),
                        "evidence_producers": {"trusted-test-producer": [
                            "policy_decision", "postcondition", "provenance", "license", "tests", "security",
                        ]},
                    }
                ],
                "revoked_fingerprints": [],
            }
        ),
        encoding="utf-8",
    )
    return key, policy, identity, publisher


def _record(
    root: Path,
    key: Path,
    identity: str,
    publisher: str,
    evidence_id: str,
    evidence_type: str,
    result: dict,
    evaluation: dict | None = None,
    **scope: str,
) -> Path:
    store = root / "evidence/store"
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{evidence_id}.json"
    value = sign_evidence_record(
        {
            "schema_version": "2.0" if evaluation is not None else "1.0",
            **({"evaluation": evaluation} if evaluation is not None else {}),
            "evidence_id": evidence_id,
            "evidence_type": evidence_type,
            "producer": "trusted-test-producer",
            "project_id": scope.get("project_id", "project-a"),
            "subject_id": scope.get("subject_id", "outcome-a"),
            "task_id": scope.get("task_id", "task-a"),
            "execution_id": scope.get("execution_id", "exec-a"),
            "actor_id": scope.get("actor_id", ""),
            "session_id": scope.get("session_id", ""),
            "created_at": scope.get(
                "created_at", datetime.now(timezone.utc).isoformat()
            ),
            "result": result,
        },
        private_key=key,
        signature_path=path.with_suffix(".json.sig"),
        identity=identity,
        publisher=publisher,
    )
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def _outcome_fixture(tmp_path: Path) -> tuple[dict, Path, Path, str, str]:
    key, _, identity, publisher = _authority(tmp_path)
    contract = tmp_path / "contracts/outcome.json"
    contract.parent.mkdir()
    contract.write_text(
        json.dumps({"required_checks": ["tests", "mapping"]}), encoding="utf-8"
    )
    from runtime.trusted_evidence import acquire_evaluation_binding
    (tmp_path / "subject.bin").write_bytes(b"evaluated result")
    binding, _, _ = acquire_evaluation_binding(tmp_path, subject_source="subject.bin",
        assessment_contract="contracts/outcome.json", interpretation="outcome-postconditions/1")
    _record(
        tmp_path,
        key,
        identity,
        publisher,
        "policy",
        "policy_decision",
        {"allowed": True},
        evaluation=binding,
    )
    evidence = _record(
        tmp_path,
        key,
        identity,
        publisher,
        "postconditions",
        "postcondition",
        {"postconditions": {"tests": True, "mapping": True}},
        evaluation=binding,
    )
    request = {
        "schema_version": "2.0",
        "subject_source": "subject.bin",
        "outcome_id": "outcome-a",
        "project_id": "project-a",
        "task_id": "task-a",
        "execution_id": "exec-a",
        "postcondition_contract": "contracts/outcome.json",
        "policy_decision_ref": "evidence:policy",
        "evidence_refs": [
            {
                "ref": "evidence:postconditions",
                "sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
            }
        ],
        "evidence_store": "evidence/store",
        "accepted_producers": ["trusted-test-producer"],
        "max_age_seconds": 3600,
    }
    return request, key, evidence, identity, publisher


def test_authoritative_outcome_passes_only_with_signed_scoped_evidence(
    tmp_path: Path,
) -> None:
    request, *_ = _outcome_fixture(tmp_path)
    result = verify_authoritative(tmp_path, request)
    assert result["verified"] and result["authoritative"]


def test_outcome_refuses_changed_subject_with_same_identity(tmp_path):
    request, *_ = _outcome_fixture(tmp_path)
    (tmp_path / 'subject.bin').write_bytes(b'different result')
    assert verify_authoritative(tmp_path, request)['authoritative'] is False


def test_outcome_refuses_changed_contract_bytes_with_same_checks(tmp_path):
    request, *_ = _outcome_fixture(tmp_path)
    contract = tmp_path / 'contracts/outcome.json'
    contract.write_bytes(contract.read_bytes() + b'\n')
    assert verify_authoritative(tmp_path, request)['authoritative'] is False


def test_outcome_conflicts_are_order_independent(tmp_path):
    request, key, evidence, identity, publisher = _outcome_fixture(tmp_path)
    binding = json.loads(evidence.read_bytes())['evaluation']
    _record(tmp_path, key, identity, publisher, 'negative', 'postcondition',
        {'postconditions': {'tests': False, 'mapping': True}}, evaluation=binding)
    positive = request['evidence_refs'][0]
    for refs in ([{'ref': 'evidence:negative'}, positive], [positive, {'ref': 'evidence:negative'}]):
        request['evidence_refs'] = refs
        assert verify_authoritative(tmp_path, request)['authoritative'] is False


def test_caller_truth_fields_cannot_create_authoritative_outcome(
    tmp_path: Path,
) -> None:
    _authority(tmp_path)
    contract = tmp_path / "contracts/outcome.json"
    contract.parent.mkdir()
    contract.write_text('{"required_checks":["tests"]}')
    request = {
        "outcome_id": "outcome-a",
        "project_id": "project-a",
        "task_id": "task-a",
        "execution_id": "exec-a",
        "postcondition_contract": "contracts/outcome.json",
        "policy_decision_ref": "evidence:missing",
        "evidence_refs": [{"ref": "evidence:missing"}],
        "evidence_store": "evidence",
        "accepted_producers": ["caller"],
        "valid": True,
        "policy_allowed": True,
    }
    result = verify_authoritative(tmp_path, request)
    assert not result["verified"] and not result["authoritative"]


def test_outcome_rejects_hash_staleness_scope_and_producer_failures(
    tmp_path: Path,
) -> None:
    request, key, evidence, identity, publisher = _outcome_fixture(tmp_path)
    request["evidence_refs"][0]["sha256"] = "0" * 64
    assert (
        verify_authoritative(tmp_path, request)["decision"]
        == "evidence_integrity_failure"
    )
    request, *_ = _outcome_fixture(tmp_path / "stale")
    request["max_age_seconds"] = 1
    old = datetime.now(timezone.utc) - timedelta(days=2)
    store = tmp_path / "stale"
    path = _record(
        store,
        store / "key",
        identity,
        publisher,
        "postconditions",
        "postcondition",
        {"postconditions": {"tests": True, "mapping": True}},
        created_at=old.isoformat(),
        evaluation=json.loads((store / "evidence/store/postconditions.json").read_text())["evaluation"],
    )
    request["evidence_refs"][0]["sha256"] = hashlib.sha256(
        path.read_bytes()
    ).hexdigest()
    stale_result = verify_authoritative(store, request)
    assert not stale_result["authoritative"]
    assert "evidence_stale" in stale_result["reasons"]
    request, *_ = _outcome_fixture(tmp_path / "scope")
    request["project_id"] = "other-project"
    assert (
        "evidence_scope_mismatch"
        in verify_authoritative(tmp_path / "scope", request)["reasons"]
    )
    request, *_ = _outcome_fixture(tmp_path / "producer")
    request["accepted_producers"] = ["untrusted"]
    assert (
        "evidence_producer_unapproved"
        in verify_authoritative(tmp_path / "producer", request)["reasons"]
    )


def test_unsigned_or_tampered_record_fails_closed(tmp_path: Path) -> None:
    request, _, evidence, *_ = _outcome_fixture(tmp_path)
    value = json.loads(evidence.read_text(encoding="utf-8"))
    value["result"]["postconditions"]["tests"] = False
    evidence.write_text(json.dumps(value), encoding="utf-8")
    request["evidence_refs"][0]["sha256"] = hashlib.sha256(
        evidence.read_bytes()
    ).hexdigest()
    result = verify_authoritative(tmp_path, request)
    assert result["decision"] == "evidence_integrity_failure"


def _admission_fixture(tmp_path):
    key, _, identity, publisher = _authority(tmp_path)
    manifest = {"id":"reader", "version":"1", "owner":"framework", "provides":["report"],
                "consumes":["path"], "effects":["read_local"], "dependencies":[]}
    (tmp_path / 'candidate.json').write_text(json.dumps(manifest), encoding='utf-8')
    (tmp_path / 'assessment.json').write_text(json.dumps({'required_evidence':['provenance','license','tests','security']}), encoding='utf-8')
    from runtime.trusted_evidence import acquire_evaluation_binding
    binding, _, _ = acquire_evaluation_binding(tmp_path, subject_source='candidate.json',
        assessment_contract='assessment.json', interpretation='candidate-assessments/1')
    for name, result in {'provenance':{'verified':True}, 'license':{'reviewed':True,'allowed':True},
                         'tests':{'passed':True}, 'security':{'malicious_or_unsafe':False}}.items():
        _record(tmp_path, key, identity, publisher, name, name, result, evaluation=binding,
                subject_id='reader', task_id='', execution_id='')
    request = {'schema_version':'2.0', 'subject_source':'candidate.json', 'assessment_contract':'assessment.json',
               'project_id':'project-a','evidence_store':'evidence/store',
               'accepted_producers':['trusted-test-producer'],
               'evidence_refs':{name:'evidence:'+name for name in ('provenance','license','tests','security')}}
    return manifest, request


def test_authoritative_admission_derives_all_four_receipts(tmp_path):
    manifest, request = _admission_fixture(tmp_path)
    result = review_authoritative(tmp_path, manifest, request)
    assert result.accepted and result.authoritative and result.disposition == 'admit'
    assert result.evaluation_binding['subject']['sha256'] == hashlib.sha256((tmp_path/'candidate.json').read_bytes()).hexdigest()
    assert not review_authoritative(tmp_path, manifest, {'project_id':'project-a','tests_passed':True}).accepted


def test_admission_refuses_same_id_changed_candidate(tmp_path):
    manifest, request = _admission_fixture(tmp_path)
    manifest['owner'] = 'changed'
    (tmp_path/'candidate.json').write_text(json.dumps(manifest),encoding='utf-8')
    assert not review_authoritative(tmp_path, manifest, request).accepted


def test_admission_refuses_supplied_object_differing_from_acquired_manifest(tmp_path):
    manifest, request = _admission_fixture(tmp_path)
    manifest['effects'] = ['network']
    assert not review_authoritative(tmp_path, manifest, request).accepted


def test_admission_refuses_changed_assessment_contract(tmp_path):
    manifest, request = _admission_fixture(tmp_path)
    path=tmp_path/'assessment.json'
    path.write_bytes(path.read_bytes()+b'\n')
    assert not review_authoritative(tmp_path, manifest, request).accepted


def test_actual_authoritative_cli_returns_bound_artifact_assessments(tmp_path):
    from contextlib import redirect_stdout
    from io import StringIO
    from runtime.cli import main
    outcome_root = tmp_path / 'outcome'
    request, *_ = _outcome_fixture(outcome_root)
    request_path = outcome_root / 'request.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    stream = StringIO()
    with redirect_stdout(stream):
        status = main(['--root', str(outcome_root), 'verify-outcome', '--request', str(request_path)])
    result = json.loads(stream.getvalue())
    assert status == 0 and result['authoritative'] is True
    assert result['evaluation_binding']['subject']['sha256'] == hashlib.sha256((outcome_root/'subject.bin').read_bytes()).hexdigest()
    admission_root = tmp_path / 'admission'
    _, request = _admission_fixture(admission_root)
    request_path = admission_root / 'request.json'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    stream = StringIO()
    with redirect_stdout(stream):
        status = main(['--root', str(admission_root), 'review-candidate', '--manifest', str(admission_root/'candidate.json'), '--evidence', str(request_path)])
    result = json.loads(stream.getvalue())
    assert status == 0 and result['authoritative'] is True
    assert result['evaluation_binding']['subject']['path'] == 'candidate.json'


def test_legacy_unbound_signed_records_do_not_satisfy_current_outcome(tmp_path):
    request, key, _, identity, publisher = _outcome_fixture(tmp_path)
    _record(tmp_path, key, identity, publisher, 'legacy', 'postcondition',
            {'postconditions':{'tests':True,'mapping':True}})
    request['evidence_refs'] = [{'ref':'evidence:legacy'}]
    result = verify_authoritative(tmp_path, request)
    assert not result['authoritative']
    assert 'evidence_evaluation_mismatch' in result['reasons']


def test_bound_record_and_request_schema_agree_with_runtime(tmp_path):
    import copy
    import pytest
    from runtime.contracts import validate_instance
    from runtime.trusted_evidence import _validate_evidence_record
    request, _, evidence, *_ = _outcome_fixture(tmp_path)
    contracts = Path(__file__).resolve().parents[1] / 'contracts'
    record = json.loads(evidence.read_bytes())
    validate_instance(request, contracts/'outcome-verification-request.schema.json')
    validate_instance(record, contracts/'trusted-evidence-record.schema.json')
    assert _validate_evidence_record(record)
    for mutation in ('missing-binding', 'legacy-with-binding', 'boolean-size', 'wrong-kind'):
        changed = copy.deepcopy(record)
        if mutation == 'missing-binding':
            del changed['evaluation']
        elif mutation == 'legacy-with-binding':
            changed['schema_version'] = '1.0'
        elif mutation == 'boolean-size':
            changed['evaluation']['subject']['size_bytes'] = True
        else:
            changed['evaluation']['subject']['kind'] = 'candidate-manifest'
        with pytest.raises(ValueError):
            _validate_evidence_record(changed)
        with pytest.raises(ValueError):
            validate_instance(changed, contracts/'trusted-evidence-record.schema.json')


def test_authorization_requires_signed_scoped_policy_and_effect_grant_for_writes(
    tmp_path: Path,
) -> None:
    key, _, identity, publisher = _authority(tmp_path)
    _record(
        tmp_path,
        key,
        identity,
        publisher,
        "policy",
        "policy_decision",
        {
            "allowed": True,
            "approved_effects": ["read_local"],
            "approval_id": "approval-a",
        },
        subject_id="reader",
        task_id="",
        execution_id="exec-a",
        actor_id="actor-a",
        session_id="session-a",
    )
    manifest = {"id": "reader", "status": "active", "effects": ["read_local"]}
    request = {
        "capability_id": "reader",
        "effects": ["read_local"],
        "project_id": "project-a",
        "actor_id": "actor-a",
        "session_id": "session-a",
        "execution_id": "exec-a",
        "evidence_store": "evidence/store",
        "policy_decision_ref": "evidence:policy",
        "accepted_policy_producers": ["trusted-test-producer"],
    }
    result = authorize_with_policy_evidence(tmp_path, manifest, request)
    assert result["approved"] and result["authoritative"]
    request["actor_id"] = "other"
    assert not authorize_with_policy_evidence(tmp_path, manifest, request)["approved"]


def test_resolver_rejects_traversal_reference(tmp_path: Path) -> None:
    _, policy, *_ = _authority(tmp_path)
    (tmp_path / "evidence/store").mkdir(parents=True)
    resolver = TrustedEvidenceResolver(tmp_path / "evidence/store", policy)
    result = resolver.resolve(
        "evidence:../secret", scope=EvidenceScope("p", "s"), accepted_producers={"x"}
    )
    assert not result.resolved and "invalid_evidence_reference" in result.reasons
