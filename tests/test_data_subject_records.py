"""Real native authority and disposable canonical stores; no production erasure."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import hashlib

import pytest

from runtime.data_controls import data_control_request
from runtime.data_subject_records import CONTROL_ROOT, _digest
from runtime.personal_record_store import STORE
from runtime.studio_authority import StudioAuthorityStore
from runtime.studio_models import EffectGrant
from tests.test_memory_vault import record
from runtime.memory_vault import MemoryVault, _json_default

from tests.studio_approval_testkit import approval_proof

def call(root, request):
    proof = approval_proof(root, "data-controls", request["operation"], request)
    return data_control_request(root, {**request, "approval_capability": proof})


@pytest.fixture
def configured(tmp_path, monkeypatch):
    key_root = tmp_path / "host-keys"
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(key_root))
    tmp_path = tmp_path / "project"
    tmp_path.mkdir()
    authority = StudioAuthorityStore(tmp_path)
    authority.admit_grant(EffectGrant("data-grant", "human:vscode-local-user", ("read", "write", "destructive"),
        ("vault", ".agentic_engineering_os_px/runtime-core", ".agentic_engineering_os_px/resource-lifecycle", ".agentic_engineering_os_px/studios/authority"), "fixture-owner", ("fixture-explicit-approval",), "2099-01-01T00:00:00Z", "admitted"))
    policy = {"schema_version": "px.data-control-policy/1.0", "policy_id": "privacy-fixture",
        "state": "approved", "approved_by": "fixture-owner", "evidence_refs": ["fixture-decision"],
        "expires_utc": "2099-01-01T00:00:00Z", "subject_id": "human-subject-explicit",
        "authorized_requesters": ["human:vscode-local-user"], "owner": "runtime.personal_record_store",
        "allowed_operations": ["personal-create", "personal-access", "personal-export", "personal-erase", "personal-retention", "personal-use", "personal-rectify", "personal-withdraw-consent"],
        "approved_purposes": ["explicit-purpose"], "approved_consent_references": ["explicit-consent"],
        "operation_purposes": {op: ["explicit-purpose" if op in {"personal-create", "personal-use"} else "rights-purpose"] for op in ["personal-create", "personal-access", "personal-export", "personal-erase", "personal-retention", "personal-use", "personal-rectify", "personal-withdraw-consent"]},
        "retention_days": 0, "legal_hold": False,
        "allowed_content_fields": ["name"], "data_class": "personal"}
    locator = CONTROL_ROOT + "/policy.json"
    path = tmp_path / locator
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(authority.sign_receipt(policy)))
    request = {"schema_version": "px.personal-record-request/1.1", "operation": "personal-create",
        "requester_id": "human:vscode-local-user", "subject_id": "human-subject-explicit", "grant_id": "data-grant",
        "policy_locator": locator, "idempotency_key": "create-one", "purpose": "explicit-purpose",
        "record": {"record_id": "record-one", "purpose": "explicit-purpose", "consent_reference": "explicit-consent",
                   "content": {"name": "fixture-private-name"}}}
    return tmp_path, authority, request, policy


def access(request, operation="personal-access"):
    return {key: value for key, value in {**request, "operation": operation, "purpose": "explicit-purpose" if operation == "personal-use" else "rights-purpose"}.items()
            if key not in {"record", "idempotency_key"}}


def test_personal_create_native_consumer_export_and_replay(configured):
    root, authority, request, policy = configured
    response = call(root, request)
    assert response["affected_count"] == 1
    assert response["receipt"]["cleanup_receipt_id"]
    result = call(root, access(request, "personal-export"))
    assert result["records"][0]["content"] == {"name": "fixture-private-name"}
    assert result["coverage_complete"] is False
    with pytest.raises(PermissionError, match="cannot be recreated"):
        call(root, request)
    assert authority.verify_receipt(json.loads((root / STORE).read_text()))["generation"] == 1


def test_native_scope_and_policy_refusals_create_nothing(configured):
    root, authority, request, policy = configured
    with pytest.raises((PermissionError, FileNotFoundError), match="unadmitted|missing"):
        call(root, {**request, "grant_id": "unadmitted"})
    with pytest.raises(PermissionError, match="purpose/consent"):
        call(root, {**request, "record": {**request["record"], "consent_reference": "invented"}})
    with pytest.raises(PermissionError, match="minimization"):
        call(root, {**request, "record": {**request["record"], "content": {"name": "fixture", "extra": "unapproved"}}})
    assert not (root / STORE).exists()


def test_validly_signed_rolled_back_content_is_rejected(configured):
    root, authority, request, policy = configured
    call(root, request)
    old = (root / STORE).read_bytes()
    call(root, {**request, "idempotency_key": "create-two", "record": {**request["record"], "record_id": "record-two"}})
    (root / STORE).write_bytes(old)
    with pytest.raises(PermissionError, match="head differs"):
        call(root, access(request))


@pytest.mark.parametrize("operation", ["personal-erase", "personal-retention"])
def test_actual_native_erasure_retention_and_tombstone_prevent_reconstruction(configured, operation):
    root, authority, request, policy = configured
    call(root, request)
    erase = {**access(request, operation), "idempotency_key": "erase-one"}
    result = call(root, erase)
    assert result["affected_count"] == 1
    assert call(root, access(request))["records"] == []
    state = authority.verify_receipt(json.loads((root / STORE).read_text()))
    assert hashlib.sha256(b"record-one").hexdigest() in state["tombstones"] and state["records"] == {}
    assert b"record-one" not in (root / STORE).read_bytes()
    assert b"fixture-private-name" not in (root / STORE).read_bytes()
    with pytest.raises(PermissionError, match="cannot be recreated"):
        call(root, {**request, "idempotency_key": "recreate-after-erase"})
    assert "historical MemoryVault/T.I.E." in result["residual_surfaces"]


def test_withdrawal_blocks_use_and_recreation_but_preserves_approved_rights(configured):
    root, authority, request, policy = configured
    call(root, request)
    assert call(root, access(request, "personal-use"))["record_count"] == 1
    withdrawal = {**access(request, "personal-withdraw-consent"), "idempotency_key": "withdraw-one",
                  "expected_generation": 1, "consent_reference": "explicit-consent"}
    result = call(root, withdrawal)
    assert result["affected_count"] == 1 and result["content_erased"] is False
    assert "live_payload_retained" in result["withdrawal_semantics"]
    with pytest.raises(PermissionError, match="operational use blocked"):
        call(root, access(request, "personal-use"))
    exported = call(root, access(request, "personal-export"))
    assert exported["records"][0]["consent_status"] == "withdrawn"
    assert exported["records"][0]["content"]["name"] == "fixture-private-name"
    with pytest.raises(PermissionError, match="withdrawn subject/consent"):
        call(root, {**request, "idempotency_key": "different-identity", "record": {**request["record"], "record_id": "different-record"}})
    rectify = {**access(request, "personal-rectify"), "idempotency_key": "rectify-withdrawn",
               "record_id": "record-one", "expected_generation": 2, "replacement_content": {"name": "corrected-private-name"}}
    call(root, rectify)
    assert call(root, access(request))["records"][0]["content"]["name"] == "corrected-private-name"
    assert b"fixture-private-name" not in (root / STORE).read_bytes()
    with pytest.raises(PermissionError, match="operational use blocked"):
        call(root, access(request, "personal-use"))
    call(root, {**access(request, "personal-erase"), "idempotency_key": "erase-withdrawn"})
    assert call(root, access(request))["records"] == []
    with pytest.raises(PermissionError, match="withdrawn subject/consent"):
        call(root, {**request, "idempotency_key": "new-after-erasure", "record": {**request["record"], "record_id": "another-record"}})


def test_current_purpose_policy_and_rectification_generation_are_enforced(configured):
    root, authority, request, policy = configured
    call(root, request)
    rectify = {**access(request, "personal-rectify"), "idempotency_key": "rectify-one",
               "record_id": "record-one", "expected_generation": 0, "replacement_content": {"name": "replacement"}}
    with pytest.raises(PermissionError, match="generation is stale"):
        call(root, rectify)
    with pytest.raises(PermissionError, match="minimization"):
        call(root, {**rectify, "expected_generation": 1, "replacement_content": {"extra": "unapproved"}})
    with pytest.raises(PermissionError, match="operation-purpose"):
        call(root, {**access(request), "purpose": "invented-lawful-basis"})
    policy["approved_consent_references"] = []
    (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    with pytest.raises(PermissionError, match="operational use blocked"):
        call(root, access(request, "personal-use"))
    assert call(root, access(request, "personal-export"))["record_count"] == 1
    policy["approved_consent_references"] = ["explicit-consent"]
    policy["allowed_content_fields"] = ["other-owner-approved-field"]
    (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    with pytest.raises(PermissionError, match="minimization"):
        call(root, access(request, "personal-use"))


def test_withdrawal_rectification_race_requires_a_current_generation(configured):
    from concurrent.futures import ThreadPoolExecutor
    root, authority, request, policy = configured
    call(root, request)
    values = [{**access(request, "personal-withdraw-consent"), "idempotency_key": "withdraw-race",
               "expected_generation": 1, "consent_reference": "explicit-consent"},
              {**access(request, "personal-rectify"), "idempotency_key": "rectify-race", "record_id": "record-one",
               "expected_generation": 1, "replacement_content": {"name": "race-correction"}}]
    approved = [{**value, "approval_capability": approval_proof(root, "data-controls", value["operation"], value)} for value in values]
    def execute(value):
        try:
            return data_control_request(root, value)
        except PermissionError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(execute, approved))
    assert sum(isinstance(value, dict) for value in outcomes) == 1
    failure = next(value for value in outcomes if isinstance(value, PermissionError))
    assert "generation is stale" in str(failure)
    assert call(root, access(request))["generation"] == 2


def test_native_host_actor_proof_replay_denied(configured):
    root, authority, request, policy = configured
    proof = approval_proof(root, "data-controls", request["operation"], request)
    approved = {**request, "approval_capability": proof}
    data_control_request(root, approved)
    with pytest.raises(PermissionError, match="approval replay"):
        data_control_request(root, approved)


def test_normal_stdin_host_entrypoint_reaches_real_store(configured, monkeypatch, capsys):
    import io
    from runtime.data_controls import main
    root, authority, request, policy = configured
    proof = approval_proof(root, "data-controls", request["operation"], request)
    stdin = io.TextIOWrapper(io.BytesIO(json.dumps({**request, "approval_capability": proof}).encode("utf-8")))
    monkeypatch.setattr("sys.stdin", stdin)
    assert main(["--project-root", str(root)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["affected_count"] == 1
    assert call(root, access(request))["records"][0]["content"]["name"] == "fixture-private-name"


def test_revoked_policy_and_uncommissioned_host_fail_closed(configured, tmp_path, monkeypatch):
    root, authority, request, policy = configured
    policy["state"] = "revoked"
    (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    with pytest.raises(PermissionError, match="current approved"):
        call(root, request)
    uncommissioned = tmp_path / "uncommissioned"
    uncommissioned.mkdir()
    missing_keys = tmp_path / "unused-key-root"
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(missing_keys))
    with pytest.raises((PermissionError, FileNotFoundError, ValueError)):
        data_control_request(uncommissioned, {**request, "approval_capability": {}})
    assert not missing_keys.exists()
    assert list(uncommissioned.iterdir()) == []


def test_existing_approval_description_and_global_inventory_remain_truthful(configured):
    from runtime.data_controls import describe_existing_approval, validate_control_descriptor
    from runtime.data_inventory import build_inventory
    root, authority, request, policy = configured
    approval_proof(root, "data-controls", request["operation"], request)
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    descriptor = describe_existing_approval(root)
    assert descriptor["key_id"]
    assert descriptor["project_identity"] == authority.project_identity
    assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert sum(len(row["operations"]) for row in validate_control_descriptor()["owners"].values()) == 12
    coverage = build_inventory(root)["record_control_coverage"]
    assert all(row["global_erasure_proved"] is False for row in coverage)
    assert next(row for row in coverage if row["store_id"] == "canonical-personal-records")["control_owner"] == "runtime.personal_record_store"
    assert all(row["status"] == "canonical_subject_copy_integration_unresolved" for row in coverage if row["store_id"] != "canonical-personal-records")


def test_hold_and_missing_destructive_grant_preserve_live_content(configured):
    root, authority, request, policy = configured
    call(root, request)
    policy["legal_hold"] = True
    (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    erase = {**access(request, "personal-erase"), "idempotency_key": "held-erase"}
    with pytest.raises(PermissionError, match="no-hold"):
        call(root, erase)
    policy["legal_hold"] = False
    (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    authority.admit_grant(EffectGrant("read-write", "human:vscode-local-user", ("read", "write"),
        (".agentic_engineering_os_px/runtime-core", ".agentic_engineering_os_px/resource-lifecycle",
         ".agentic_engineering_os_px/studios/authority"), "fixture-owner", ("fixture-approval",),
        "2099-01-01T00:00:00Z", "admitted"))
    with pytest.raises(PermissionError, match="required effects"):
        call(root, {**erase, "grant_id": "read-write"})
    assert call(root, access(request))["record_count"] == 1


def test_uncertain_postpublication_commit_blocks_future_access(configured, monkeypatch):
    from runtime.effect_intent import EffectIntentLedger
    root, authority, request, policy = configured
    def failure(*args, **kwargs):
        raise OSError("injected durable commit failure")
    monkeypatch.setattr(EffectIntentLedger, "commit", failure)
    with pytest.raises(OSError, match="commit failure"):
        call(root, request)
    with pytest.raises(PermissionError, match="outcome uncertain"):
        call(root, access(request))


def test_concurrent_erase_and_recreation_preserve_tombstone(configured):
    from concurrent.futures import ThreadPoolExecutor
    root, authority, request, policy = configured
    call(root, request)
    erase = {**access(request, "personal-erase"), "idempotency_key": "race-erase"}
    create = {**request, "idempotency_key": "race-recreate"}
    # Prepare both host proofs before racing so only actual native store custody
    # races, not fixture verifier commissioning.
    approved = [{**value, "approval_capability": approval_proof(root, "data-controls", value["operation"], value)}
                for value in (erase, create)]
    def execute(value):
        try:
            return data_control_request(root, value)
        except PermissionError as error:
            return error
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(execute, approved))
    assert outcomes[0]["affected_count"] == 1
    assert isinstance(outcomes[1], PermissionError)
    assert call(root, access(request))["records"] == []
    assert hashlib.sha256(b"record-one").hexdigest() in authority.verify_receipt(json.loads((root / STORE).read_text()))["tombstones"]


def test_vault_explicit_binding_exports_all_revisions_and_refuses_erase(configured):
    root, authority, base, policy = configured
    vault = MemoryVault(root / "vault", workspace_id="wsp", project_id="prj")
    vault.append(record())
    vault.append(record(revision=2, summary="new-private-summary"))
    image = json.loads(json.dumps([asdict(item) for item in vault.records()], default=_json_default))
    policy.update(owner="runtime.memory_vault", allowed_operations=["subject-access", "subject-export", "subject-erase", "subject-retention"])
    (root / base["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    locator = CONTROL_ROOT + "/binding.json"
    binding = {"schema_version": "px.subject-record-binding/1.0", "state": "approved", "approved_by": "fixture-owner",
        "evidence_refs": ["actual-owner-identified-subject"], "expires_utc": "2099-01-01T00:00:00Z",
        "subject_id": base["subject_id"], "owner": "runtime.memory_vault", "policy_id": "privacy-fixture",
        "vault_relative": "vault", "workspace_id": "wsp", "project_id": "prj", "memory_ids": ["mem-one"],
        "record_image_sha256": _digest(image)}
    (root / locator).write_text(json.dumps(authority.sign_receipt(binding)))
    request = {**access(base), "schema_version": "px.subject-record-request/1.0", "operation": "subject-export", "binding_locator": locator}
    request.pop("purpose")
    exported = call(root, request)
    assert len(exported["records"]) == 2
    assert exported["records"][1]["summary"] == "new-private-summary"
    refused = call(root, {**request, "operation": "subject-erase"})
    assert refused["erased_count"] == 0 and refused["status"] == "PRESERVED_SEALED_HISTORY_ERASURE_REFUSED"
    assert len(vault.records()) == 2
    policy["owner"] = "runtime.personal_record_store"
    (root / base["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    with pytest.raises(PermissionError, match="approved policy"):
        call(root, request)
    policy["owner"] = "runtime.memory_vault"
    (root / base["policy_locator"]).write_text(json.dumps(authority.sign_receipt(policy)))
    vault.append(record(revision=3))
    with pytest.raises(PermissionError, match="stale"):
        call(root, request)
