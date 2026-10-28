"""Actual native approved personal-use consumer; disposable records only."""
import json
import pytest
from tests.test_data_subject_records import configured, call, access
from tests.studio_approval_testkit import approval_proof
from runtime.chat_context import retrieve_chat_context
from runtime.personal_record_store import personal_record_request
from runtime.data_subject_records import CONTROL_ROOT

def signed(root, request):
    return {**request, "approval_capability": approval_proof(root, "data-controls", request["operation"], request)}

def test_actual_personal_context_source_provenance_and_replay(configured):
    root, authority, request, policy = configured
    call(root, request)
    use = signed(root, access(request, "personal-use"))
    result = retrieve_chat_context(root, root, {"query": "explicit", "personal_use_request": use})
    refs = [row for row in result["refs"] if row["kind"] == "personal-use-context"]
    assert len(refs) == 1 and result["authority_granted"] is False
    body = json.loads(refs[0]["content"])
    assert body["source_generation"] == 1 and len(body["source_image_sha256"]) == 64
    assert body["subject_id"] == request["subject_id"] and body["purpose"] == "explicit-purpose"
    assert body["content"] == {"name": "fixture-private-name"}
    assert body["requires_current_native_use_before_provider_dispatch"] is True
    with pytest.raises(PermissionError):
        retrieve_chat_context(root, root, {"query": "explicit", "personal_use_request": use})

def test_withdrawn_personal_context_fails_without_cached_fallback(configured):
    root, authority, request, policy = configured
    call(root, request)
    call(root, {**access(request, "personal-withdraw-consent"), "idempotency_key": "withdraw-context", "expected_generation": 1, "consent_reference": "explicit-consent"})
    with pytest.raises(PermissionError, match="operational use blocked"):
        retrieve_chat_context(root, root, {"query": "explicit", "personal_use_request": signed(root, access(request, "personal-use"))})
    assert call(root, access(request, "personal-export"))["record_count"] == 1

def test_current_policy_rechecked_after_internal_materialization(configured):
    root, authority, request, policy = configured
    call(root, request)
    def changed(snapshot):
        revised = {**policy, "approved_consent_references": []}
        (root / request["policy_locator"]).write_text(json.dumps(authority.sign_receipt(revised)))
        return "must-not-return"
    with pytest.raises(PermissionError, match="changed at effect boundary"):
        personal_record_request(root, signed(root, access(request, "personal-use")), materialize_use=changed)

def test_ordinary_context_does_not_initialize_personal_authority(tmp_path):
    before = list(tmp_path.iterdir())
    result = retrieve_chat_context(tmp_path, tmp_path, {"query": "ordinary"})
    assert result["authority_granted"] is False
    assert list(tmp_path.iterdir()) == before


def test_personal_context_rejects_rights_request_and_missing_host_proof(configured):
    root, authority, request, policy = configured
    call(root, request)
    with pytest.raises(ValueError, match="personal-use request"):
        retrieve_chat_context(root, root, {"query": "explicit", "personal_use_request": signed(root, access(request, "personal-export"))})
    with pytest.raises(ValueError, match="closed bounded"):
        retrieve_chat_context(root, root, {"query": "explicit", "personal_use_request": access(request, "personal-use")})
