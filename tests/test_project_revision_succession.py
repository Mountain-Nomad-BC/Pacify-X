from __future__ import annotations
from datetime import datetime, timezone
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import pytest
from runtime.project_revision_succession import (
    AUTH_SCHEMA,
    POLICY_SCHEMA,
    STATE_SCHEMA,
    SuccessionLedger,
    verify_owner_authorization,
    SuccessionProposalBlocked,
    prepare_successor_event,
    validate_history,
    validate_owner_policy,
    validate_successor_proposal,
)

NOW = datetime(2026, 10, 11, 1, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize('name', ['active-revision', 'authorization', 'owner-policy', 'state'])
def test_succession_contract_is_admitted_by_native_dialect_and_ownership_builder(name):
    from pathlib import Path
    from runtime.contracts import build_minimal_instance, validate_instance
    from scripts.build_contract_ownership_registry import build
    root = Path(__file__).resolve().parents[1]
    path = root / 'contracts/project_revision_succession' / f'{name}.schema.json'
    validate_instance(build_minimal_instance(path), path)
    row = next(row for row in build(root)['records'] if row['path'] == path.relative_to(root).as_posix())
    assert row['owner'] == 'runtime/project_revision_succession.py'
    assert 'runtime/project_revision_succession.py' in row['consumers']
    assert 'runtime/revision_campaign_lifecycle.py' in row['producers']

PREDECESSOR = {
    "schema_version": "px.repair-campaign/1.0",
    "project_id": "prj_pacify_x_previous",
    "campaign_id": "pacify-x-architecture-remediation-20260909",
    "phase": "installed_operational",
    "intake_open": False,
    "unresolved": [],
}
PREDECESSOR_BYTES = json.dumps(PREDECESSOR, sort_keys=True).encode("utf-8")
PREDECESSOR_SHA = hashlib.sha256(PREDECESSOR_BYTES).hexdigest()
SUCCESSOR_CAMPAIGN_RAW_SHA = PREDECESSOR_SHA
SOURCE_SHA = "a" * 64
PROPOSAL = {
    "successor_project_id": "prj_pacify_x_successor_20261011",
    "successor_campaign_id": "pacify-x-successor-repair-20261011",
    "predecessor_campaign_id": PREDECESSOR["campaign_id"],
    "predecessor_raw_sha256": PREDECESSOR_SHA,
    "source_tree_sha256": SOURCE_SHA,
    "owner_policy_id": "OWNER-REVISION-SUCCESSION-001",
}
AUTHORIZATION = {
    "schema_version": AUTH_SCHEMA,
    "decision": "approved",
    "authorization_id": "owner-approval-20261011-001",
    "issuer": "owner-test-issuer",
    "owner_policy_id": "OWNER-REVISION-SUCCESSION-001",
    **PROPOSAL,
    "issued_at": "2026-10-11T00:00:00Z",
    "expires_at": "2026-12-12T00:00:00Z",
    "effect_boundary": {"local_revision_activation": True, "production_activation": False, "package": False, "install": False, "publication": False},
    "intake_findings": ["seed"],
    "revocation_status": "not_revoked",
    "source_identity": {"kind": "source_tree", "source_sha256": SOURCE_SHA},
    "revoked": False,
}


def validate(authorization=AUTHORIZATION, verifier=None, **overrides):
    if verifier is None:
        verifier = lambda record: record is authorization
    return validate_successor_proposal(
        predecessor_campaign=overrides.pop("predecessor_campaign", PREDECESSOR),
        predecessor_raw_sha256=overrides.pop("predecessor_raw_sha256", PREDECESSOR_SHA),
        proposal=overrides.pop("proposal", PROPOSAL),
        owner_authorization=authorization,
        verify_owner_authorization=verifier,
        now=overrides.pop("now", NOW),
    )


def test_valid_proposal_is_hash_bound_and_does_not_activate():
    result = validate()
    assert result["valid"] is True
    assert result["activated"] is False
    assert result["binding"]["predecessor_raw_sha256"] == PREDECESSOR_SHA
    assert len(result["binding_sha256"]) == 64
@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"authorization": None, "verifier": None}, "verifier and record are required"),
        ({"verifier": lambda _record: False}, "was not verified"),
        ({"verifier": lambda _record: 1}, "was not verified"),
        ({"authorization": {**AUTHORIZATION, "revocation_status": "revoked"}}, "revoked"),
        ({"authorization": {**AUTHORIZATION, "expires_at": "2026-10-11T00:59:00Z"}}, "not currently valid"),
        ({"authorization": {**AUTHORIZATION, "successor_campaign_id": "another-campaign"}}, "not bound"),
    ],
)
def test_missing_untrusted_expired_or_mismatched_authority_fails_closed(kwargs, message):
    with pytest.raises(SuccessionProposalBlocked, match=message):
        validate(**kwargs)


def test_nonterminal_or_unresolved_predecessor_is_rejected():
    with pytest.raises(SuccessionProposalBlocked, match="terminal campaign"):
        validate(predecessor_campaign={**PREDECESSOR, "unresolved": ["finding"]})


def test_predecessor_bytes_must_match_proposal_link():
    with pytest.raises(SuccessionProposalBlocked, match="exact predecessor bytes"):
        validate(proposal={**PROPOSAL, "predecessor_raw_sha256": "b" * 64})


def test_successor_ids_must_be_new():
    with pytest.raises(SuccessionProposalBlocked, match="must differ"):
        validate(proposal={**PROPOSAL, "successor_campaign_id": PREDECESSOR["campaign_id"]})


def test_authorization_window_is_inclusive_start_exclusive_expiry():
    with pytest.raises(SuccessionProposalBlocked, match="not currently valid"):
        validate(now=datetime(2026, 12, 12, 0, 0, tzinfo=timezone.utc))


def test_source_identity_is_bound_to_owner_approval():
    with pytest.raises(SuccessionProposalBlocked, match="not bound"):
        validate(proposal={**PROPOSAL, "source_tree_sha256": "c" * 64})


def test_append_candidate_is_hash_chained_and_does_not_activate():
    result = prepare_successor_event(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
    )
    assert result["valid"] is True and result["activated"] is False
    event = result["event"]
    assert event["sequence"] == 1
    assert event["previous_event_sha256"] == "0" * 64
    assert event["event_status"] == "proposed"
    assert event["authorization"] == AUTHORIZATION
    assert event["binding"]["authorization_sha256"] == hashlib.sha256(
        json.dumps(AUTHORIZATION, sort_keys=True, separators=(',', ':')).encode("utf-8")
    ).hexdigest()
    assert event["event_sha256"] == hashlib.sha256(
        json.dumps(
            {key: value for key, value in event.items() if key != "event_sha256"},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def test_unactivated_proposal_does_not_claim_predecessor_or_block_a_later_attempt():
    first = prepare_successor_event(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
    )["event"]
    assert first["event_status"] == "proposed"
    second_proposal = {
        **PROPOSAL,
        "successor_project_id": "prj_pacify_x_successor_retry",
        "successor_campaign_id": "pacify-x-successor-retry",
    }
    second_authorization = {
        **AUTHORIZATION,
        **second_proposal,
        "authorization_id": "owner-approval-20261011-retry",
    }
    second = prepare_successor_event(
        history=[first], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=second_proposal,
        owner_authorization=second_authorization,
        verify_owner_authorization=lambda record: record is second_authorization, now=NOW,
    )["event"]
    assert second["event_status"] == "proposed"
    assert second["binding"]["predecessor_campaign_id"] == PREDECESSOR["campaign_id"]


def test_proposed_history_allows_distinct_retry_without_activation():
    first = planned_event()
    retry_proposal = {**PROPOSAL, "successor_project_id": "prj_pacify_x_retry", "successor_campaign_id": "pacify-x-retry"}
    retry_authorization = {**AUTHORIZATION, **retry_proposal, "authorization_id": "owner-approval-20261011-retry"}
    retry = prepare_successor_event(
        history=[first], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=retry_proposal,
        owner_authorization=retry_authorization,
        verify_owner_authorization=lambda record: record is retry_authorization, now=NOW,
    )["event"]
    assert retry["sequence"] == 2
    assert retry["event_status"] == "proposed"
    assert retry["binding"]["predecessor_campaign_id"] == PREDECESSOR["campaign_id"]


def test_unactivated_proposals_do_not_claim_predecessor_exclusivity():
    first = planned_event()
    second_proposal = {**PROPOSAL, "successor_project_id": "prj_other", "successor_campaign_id": "campaign-other"}
    second_auth = {**AUTHORIZATION, **second_proposal, "authorization_id": "owner-approval-other"}
    second = prepare_successor_event(
        history=[first], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=second_proposal,
        owner_authorization=second_auth,
        verify_owner_authorization=lambda record: record is second_auth, now=NOW,
    )["event"]
    assert first["event_status"] == second["event_status"] == "proposed"
    assert first["binding"]["predecessor_campaign_id"] == second["binding"]["predecessor_campaign_id"]


def test_append_candidate_rejects_replayed_campaign_or_authorization():
    event = prepare_successor_event(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
    )["event"]
    with pytest.raises(SuccessionProposalBlocked, match="replays or forks"):
        prepare_successor_event(
            history=[event], predecessor_campaign=PREDECESSOR,
            predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
            owner_authorization=AUTHORIZATION,
            verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
        )


def test_append_candidate_rejects_corrupt_history():
    event = prepare_successor_event(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
    )["event"]
    corrupt = {**event, "previous_event_sha256": "f" * 64}
    with pytest.raises(SuccessionProposalBlocked, match="hash chain is corrupt"):
        prepare_successor_event(
            history=[corrupt], predecessor_campaign=PREDECESSOR,
            predecessor_raw_sha256=PREDECESSOR_SHA,
            proposal={**PROPOSAL, "successor_project_id": "prj_next"},
            owner_authorization={**AUTHORIZATION, "successor_project_id": "prj_next"},
            verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
        )


def test_history_rejects_competing_activated_successor_of_same_predecessor():
    event = prepare_successor_event(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
    )["event"]
    event["event_status"] = "activated"
    from runtime.project_revision_succession import _digest
    event["event_sha256"] = _digest({key: value for key, value in event.items() if key != "event_sha256"})
    with pytest.raises(SuccessionProposalBlocked, match="activated predecessor fork|replays or forks|latest activated campaign"):
        prepare_successor_event(
            history=[event], predecessor_campaign=PREDECESSOR,
            predecessor_raw_sha256=PREDECESSOR_SHA,
            proposal={**PROPOSAL, "successor_project_id": "prj_next", "successor_campaign_id": "campaign_next", "owner_policy_id": "OWNER-NEXT"},
            owner_authorization={**AUTHORIZATION, "successor_project_id": "prj_next", "successor_campaign_id": "campaign_next", "owner_policy_id": "OWNER-NEXT", "authorization_id": "approval-next", "issuer": "owner-next"},
            verify_owner_authorization=lambda record: record == AUTHORIZATION, now=NOW,
        )


def _activated_event(event):
    from runtime.project_revision_succession import _digest
    activated = {**event, "event_status": "activated"}
    activated["event_sha256"] = _digest({key: value for key, value in activated.items() if key != "event_sha256"})
    return activated

def _bind_successor_campaign(event):
    from runtime.project_revision_succession import _digest
    campaign = _successor_campaign(event)
    campaign.pop("succession_event_sha256", None)
    state_digest = _digest(campaign)
    proposal = {
        **PROPOSAL,
        "successor_project_id": event["binding"]["successor_project_id"],
        "successor_campaign_id": event["binding"]["successor_campaign_id"],
        "predecessor_campaign_id": event["binding"]["predecessor_campaign_id"],
        "predecessor_raw_sha256": event["binding"]["predecessor_raw_sha256"],
        "predecessor_campaign_state_sha256": state_digest,
    }
    authorization = {
        **AUTHORIZATION,
        **proposal,
        "authorization_id": event["binding"]["authorization_id"],
    }
    event["binding"] = {
        **event["binding"],
        "predecessor_campaign_state_sha256": state_digest,
        "authorization_sha256": _digest(authorization),
    }
    event["authorization"] = authorization
    event["binding_sha256"] = _digest(event["binding"])
    event["event_sha256"] = _digest({key: value for key, value in event.items() if key != "event_sha256"})
    campaign["succession_event_sha256"] = event["event_sha256"]
    return campaign

def _successor_campaign(event):
    binding = event["binding"]
    return {
        "schema_version": "px.repair-campaign/1.0",
        "project_id": binding["successor_project_id"],
        "campaign_id": binding["successor_campaign_id"],
        "phase": "installed_operational", "intake_open": False, "unresolved": [],
        "revision_parent_campaign_id": binding["predecessor_campaign_id"],
        "revision_parent_sha256": binding["predecessor_raw_sha256"],
        "succession_event_sha256": event["event_sha256"],
    }



def test_second_generation_rejects_stale_a_to_c_and_competing_b_to_c_fork():
    from runtime.project_revision_succession import _digest
    event_a_b = _activated_event(planned_event())
    campaign_b = _successor_campaign(event_a_b)
    campaign_b.pop("succession_event_sha256", None)
    state_b = _digest(campaign_b)
    campaign_b["succession_event_sha256"] = event_a_b["event_sha256"]
    raw_b = json.dumps(campaign_b, sort_keys=True, separators=(',', ':')).encode()
    proposal_b_c = {
        "successor_project_id": "prj_revision_c", "successor_campaign_id": "campaign_revision_c",
        "predecessor_campaign_id": campaign_b["campaign_id"],
        "predecessor_raw_sha256": hashlib.sha256(raw_b).hexdigest(),
        "predecessor_campaign_state_sha256": state_b, "source_tree_sha256": SOURCE_SHA,
        "owner_policy_id": "OWNER-REVISION-SUCCESSION-001",
    }
    authorization_b_c = {
        **AUTHORIZATION, **proposal_b_c, "authorization_id": "approval-revision-c",
        "source_identity": {"kind": "source_tree", "source_sha256": SOURCE_SHA},
    }
    next_event = prepare_successor_event(
        history=[event_a_b], predecessor_campaign=campaign_b,
        predecessor_raw_sha256=proposal_b_c["predecessor_raw_sha256"], proposal=proposal_b_c,
        owner_authorization=authorization_b_c,
        verify_owner_authorization=lambda record: record is authorization_b_c, now=NOW,
    )["event"]
    assert validate_history([event_a_b, next_event])["event_count"] == 2
    for stale_campaign, stale_sha, stale_parent in (
        (PREDECESSOR, PREDECESSOR_SHA, PREDECESSOR["campaign_id"]),
        ({**campaign_b, "phase": "repair"}, hashlib.sha256(json.dumps({**campaign_b, "phase": "repair"}, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), campaign_b["campaign_id"]),
    ):
        stale_proposal = {
            **proposal_b_c, "successor_project_id": "prj_stale_c", "successor_campaign_id": "campaign_stale_c",
            "predecessor_campaign_id": stale_parent, "predecessor_raw_sha256": stale_sha,
        }
        stale_authorization = {
            **AUTHORIZATION, **stale_proposal, "authorization_id": "approval-stale-c",
            "source_identity": {"kind": "source_tree", "source_sha256": SOURCE_SHA},
        }
        with pytest.raises(SuccessionProposalBlocked, match="latest activated campaign|state differs|terminal campaign"):
            prepare_successor_event(
                history=[event_a_b], predecessor_campaign=stale_campaign,
                predecessor_raw_sha256=stale_sha, proposal=stale_proposal,
                owner_authorization=stale_authorization,
                verify_owner_authorization=lambda record: record is stale_authorization, now=NOW,
            )
    forked_campaign_b = {**campaign_b, "campaign_id": "campaign_competing_b"}
    with pytest.raises(SuccessionProposalBlocked, match="state differs|latest activated campaign"):
        prepare_successor_event(
            history=[event_a_b], predecessor_campaign=forked_campaign_b,
            predecessor_raw_sha256=hashlib.sha256(json.dumps(forked_campaign_b, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            proposal=proposal_b_c, owner_authorization=authorization_b_c,
            verify_owner_authorization=lambda record: record is authorization_b_c, now=NOW,
        )



def test_nonproduction_simulation_never_persists_or_activates(tmp_path):
    ledger = SuccessionLedger(tmp_path)
    result = ledger.simulate(
        history=[], predecessor_campaign=PREDECESSOR,
        predecessor_raw_sha256=PREDECESSOR_SHA, proposal=PROPOSAL,
        owner_authorization=AUTHORIZATION,
        verify_authorization=lambda record: record is AUTHORIZATION,
    )
    assert result["simulated"] is True
    assert result["activated"] is False
    assert not ledger.state_path.exists()


def test_owner_policy_requires_exact_shape_and_verified_key_binding():
    malformed = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": "OWNER-REVISION-SUCCESSION-001",
        "status": "active",
        "authorization_schema": AUTH_SCHEMA,
        "trusted_authorities": [{
            "identity": "owner", "fingerprint": "SHA256:" + "A" * 43,
            "public_key": "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB22mMmNZMvrlkcwaXapA1YFqQrsv7n5VmFaqGvNv1oJ",
            "publisher": "project-owner", "status": "active",
        }],
        "revoked_authorizations": [],
        "revision_scope": ["*"],
    }
    with pytest.raises(SuccessionProposalBlocked, match="does not match public key"):
        validate_owner_policy(malformed)


def test_second_generation_history_binds_successor_state_without_rewriting_authorization():
    from runtime.project_revision_succession import _digest
    event_a_b = planned_event()
    event_a_b["event_status"] = "activated"
    campaign_b = {
        "schema_version": "px.repair-campaign/1.0", "project_id": PROPOSAL["successor_project_id"],
        "campaign_id": PROPOSAL["successor_campaign_id"], "phase": "installed_operational",
        "intake_open": False, "unresolved": [],
        "revision_parent_campaign_id": PREDECESSOR["campaign_id"],
        "revision_parent_sha256": PREDECESSOR_SHA,
    }
    state_digest = _digest(campaign_b)
    authorization_b = {
        **AUTHORIZATION,
        "successor_campaign_id": campaign_b["campaign_id"],
        "predecessor_campaign_state_sha256": state_digest,
    }
    event_a_b["binding"] = {
        **event_a_b["binding"],
        "predecessor_campaign_state_sha256": state_digest,
        "authorization_sha256": _digest(authorization_b),
    }
    event_a_b["authorization"] = authorization_b
    event_a_b["binding_sha256"] = _digest(event_a_b["binding"])
    event_a_b["event_sha256"] = _digest({key: value for key, value in event_a_b.items() if key != "event_sha256"})
    campaign_b["succession_event_sha256"] = event_a_b["event_sha256"]
    raw_b = json.dumps(campaign_b, sort_keys=True, separators=(',', ':')).encode()
    proposal_b_c = {
        "successor_project_id": "prj_revision_c", "successor_campaign_id": "campaign_revision_c",
        "predecessor_campaign_id": campaign_b["campaign_id"],
        "predecessor_raw_sha256": hashlib.sha256(raw_b).hexdigest(),
        "predecessor_campaign_state_sha256": state_digest,
        "source_tree_sha256": SOURCE_SHA, "owner_policy_id": "OWNER-REVISION-SUCCESSION-001",
    }
    authorization_b_c = {
        **AUTHORIZATION, **proposal_b_c, "authorization_id": "owner-approval-revision-c",
        "source_identity": {"kind": "source_tree", "source_sha256": SOURCE_SHA},
    }
    next_event = prepare_successor_event(
        history=[event_a_b], predecessor_campaign=campaign_b,
        predecessor_raw_sha256=proposal_b_c["predecessor_raw_sha256"], proposal=proposal_b_c,
        owner_authorization=authorization_b_c,
        verify_owner_authorization=lambda record: record is authorization_b_c, now=NOW,
    )["event"]
    assert validate_history([event_a_b, next_event])["event_count"] == 2

def test_owner_policy_evidence_verification_fails_closed_without_signed_provenance(tmp_path):
    public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB22mMmNZMvrlkcwaXapA1YFqQrsv7n5VmFaqGvNv1oJ"
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(base64.b64decode(public_key.split()[1])).digest()
    ).decode("ascii").rstrip("=")
    policy = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": "OWNER-REVISION-SUCCESSION-001",
        "status": "active", "authorization_schema": AUTH_SCHEMA,
        "trusted_authorities": [{
            "identity": "owner", "fingerprint": fingerprint,
            "public_key": public_key,
            "publisher": "project-owner", "status": "active",
        }],
        "revoked_authorizations": [], "revision_scope": ["*"],
    }
    policy_path = tmp_path / "policy.json"
    signature_path = tmp_path / "policy.sig"
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    signature_path.write_bytes(b"not a signature")
    with pytest.raises(SuccessionProposalBlocked, match="verification failed|signed provenance evidence|provenance"):
        verify_owner_authorization(
            AUTHORIZATION, policy_path=policy_path, signature_path=signature_path,
            policy_evidence_reference="evidence:nonexistent-owner-policy-proof",
            evidence_store=tmp_path, evidence_trust_policy_path=tmp_path / "unconfigured-trust.json",
            project_id="prj_pacify_x_previous", now=NOW,
        )


def test_repair_campaign_schema_state_constants_are_stable():
    assert STATE_SCHEMA == "px.project-revision-succession-state/1.0"
    assert AUTH_SCHEMA == "px.project-revision-succession-authorization/1.0"


def planned_event(proposal=PROPOSAL, authorization=AUTHORIZATION, *, history=None, predecessor=PREDECESSOR, predecessor_raw_sha256=PREDECESSOR_SHA):
    return prepare_successor_event(
        history=[] if history is None else history,
        predecessor_campaign=predecessor,
        predecessor_raw_sha256=predecessor_raw_sha256, proposal=proposal,
        owner_authorization=authorization,
        verify_owner_authorization=lambda record: record is authorization, now=NOW,
    )["event"]


def test_wal_persists_candidate_append_only_and_status_validates_chain(tmp_path):
    ledger = SuccessionLedger(tmp_path)
    event = planned_event()
    committed = ledger._append_candidate(event)
    assert committed["activated"] is False
    assert ledger.status()["event_count"] == 1
    assert ledger._read()["events"] == [event]
    with pytest.raises(SuccessionProposalBlocked, match="already been used|replay|fork"):
        ledger._append_candidate(event)
    assert ledger.status()["event_count"] == 1

def test_concurrent_wal_append_serializes_and_rejects_predecessor_fork(tmp_path):
    ledger = SuccessionLedger(tmp_path)
    first = planned_event()
    second_proposal = {
        **PROPOSAL,
        "successor_project_id": "prj_pacify_x_other_successor",
        "successor_campaign_id": "pacify-x-other-successor-campaign",
    }
    second_auth = {
        **AUTHORIZATION,
        **second_proposal,
        "authorization_id": "owner-approval-20261011-002",
    }
    second = planned_event(second_proposal, second_auth)
    def append(event):
        try:
            return ledger._append_candidate(event)["valid"]
        except (SuccessionProposalBlocked, ValueError):
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(append, (first, second)))
    assert sum(outcomes) == 1
    assert ledger.status()["event_count"] == 1

def test_wal_interrupted_publication_is_visible_and_recovers_forward(tmp_path):
    ledger = SuccessionLedger(tmp_path)
    event = planned_event()
    def interrupt(boundary):
        if boundary == "target:0:published":
            raise RuntimeError("injected interruption")
    with pytest.raises(RuntimeError, match="injected interruption"):
        ledger._append_candidate(event, fault_injector=interrupt)
    status = ledger.status()
    assert status["requires_recovery"] is True
    result = ledger.wal.recover()
    assert result["completed"]
    assert ledger.status()["event_count"] == 1

def test_wal_integrity_rejects_postcommit_history_tampering(tmp_path):
    ledger = SuccessionLedger(tmp_path)
    ledger._append_candidate(planned_event())
    value = ledger._read()
    value["events"][0]["binding"]["source_tree_sha256"] = "b" * 64
    ledger.state_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(SuccessionProposalBlocked, match="chain or binding is corrupt"):
        ledger.status()


def test_second_generation_history_uses_immutable_state_binding_without_rewriting_signed_history():
    from runtime.project_revision_succession import _digest
    event_a_b = _activated_event(planned_event())
    campaign_b = _successor_campaign(event_a_b)
    campaign_b.pop("succession_event_sha256", None)
    state_b = _digest(campaign_b)
    campaign_b["succession_event_sha256"] = event_a_b["event_sha256"]
    raw_b = json.dumps(campaign_b, sort_keys=True, separators=(',', ':')).encode()
    proposal_b_c = {
        "successor_project_id": "prj_revision_c", "successor_campaign_id": "campaign_revision_c",
        "predecessor_campaign_id": campaign_b["campaign_id"],
        "predecessor_raw_sha256": hashlib.sha256(raw_b).hexdigest(),
        "predecessor_campaign_state_sha256": state_b, "source_tree_sha256": SOURCE_SHA,
        "owner_policy_id": "OWNER-REVISION-SUCCESSION-001",
    }
    authorization_b_c = {
        **AUTHORIZATION, **proposal_b_c, "authorization_id": "approval-revision-c",
        "source_identity": {"kind": "source_tree", "source_sha256": SOURCE_SHA},
    }
    next_event = prepare_successor_event(
        history=[event_a_b], predecessor_campaign=campaign_b,
        predecessor_raw_sha256=proposal_b_c["predecessor_raw_sha256"], proposal=proposal_b_c,
        owner_authorization=authorization_b_c,
        verify_owner_authorization=lambda record: record is authorization_b_c, now=NOW,
    )["event"]
    assert validate_history([event_a_b, next_event])["event_count"] == 2

def test_legacy_project_campaign_selection_is_unchanged_without_revision_pointer(tmp_path):
    from runtime.project_revision_succession import current_revision_root, current_campaign_path
    assert current_revision_root(tmp_path) is None
    assert current_campaign_path(tmp_path).as_posix().endswith(".agentic_engineering_os_px/processing-order/repair-campaign.json")


def test_signed_trusted_evidence_policy_provenance_succeeds_in_isolated_fixture(tmp_path):
    from runtime.release_signing import public_key_fingerprint
    from runtime.trusted_evidence import sign_evidence_record
    from runtime.project_revision_succession import verify_owner_policy_evidence
    import shutil
    from tests.test_trust_boundaries import _authority
    owner_root = tmp_path / "owner"
    keygen = shutil.which("ssh-keygen")
    if keygen is None:
        pytest.skip("ssh-keygen is required for disposable signed-policy fixtures")
    key, _, identity, publisher = _authority(owner_root)
    policy = {
        "schema_version": POLICY_SCHEMA,
        "policy_id": "OWNER-SUCCESSION-TEST-001",
        "status": "active",
        "authorization_schema": AUTH_SCHEMA,
        "trusted_authorities": [{
            "identity": "succession-owner", "fingerprint": public_key_fingerprint(key.with_suffix(".pub")),
            "public_key": key.with_suffix(".pub").read_text(encoding="utf-8").strip(),
            "publisher": publisher, "status": "active",
        }],
        "revoked_authorizations": [], "revision_scope": ["*"],
    }
    policy["revocation_registry"] = {
        "schema_version": "px.authorization-revocation-registry/1.0",
        "checked_at": NOW.isoformat(), "revoked": [], "superseded": {},
    }
    # Test policy publication is an isolated fixture; no production trust record is changed.
    store = tmp_path / "evidence-store"
    store.mkdir()
    policy_path = store / "owner-policy.json"
    policy_path.write_text(json.dumps(policy, sort_keys=True), encoding="utf-8")
    trust = owner_root / "policies/effect-grant-trust.json"
    value = json.loads(trust.read_text(encoding="utf-8"))
    value["trusted_signers"][0]["evidence_producers"] = {
        "project-revision-succession-policy": ["provenance"]
    }
    trust.write_text(json.dumps(value), encoding="utf-8")
    record = {
        "schema_version": "1.0", "evidence_id": "succession-policy-proof",
        "evidence_type": "provenance", "producer": "project-revision-succession-policy",
        "project_id": "prj_test", "subject_id": policy["policy_id"],
        "created_at": NOW.isoformat(), "result": {"verified": True},
        "artifact": {"path": "owner-policy.json", "sha256": hashlib.sha256(policy_path.read_bytes()).hexdigest()},
    }
    evidence_path = store / "succession-policy-proof.json"
    signed = sign_evidence_record(record, private_key=key,
        signature_path=evidence_path.with_suffix(".json.sig"), identity=identity, publisher=publisher)
    evidence_path.write_text(json.dumps(signed), encoding="utf-8")
    result = verify_owner_policy_evidence(
        policy, policy_path=policy_path, evidence_reference="evidence:succession-policy-proof",
        evidence_store=store, trust_policy_path=trust, project_id="prj_test", now=NOW,
    )
    assert result["valid"] is True
    assert result["policy_sha256"] == hashlib.sha256(policy_path.read_bytes()).hexdigest()
    # Exercise the actual signed authorization boundary, not a callback that
    # asserts success. Both schema envelopes must accept exactly these bytes.
    from runtime.project_revision_succession import OWNER_AUTH_KEYS, AUTH_NAMESPACE
    from runtime.release_signing import canonical_bytes
    import subprocess
    import jsonschema
    from pathlib import Path
    auth = {k: v for k, v in AUTHORIZATION.items() if k in OWNER_AUTH_KEYS}
    auth.update(owner_policy_id=policy['policy_id'], issuer='succession-owner',
                validation_policy={'campaign_id': PROPOSAL['successor_campaign_id'],
                                   'authority': 'OWNER-FRESH-VALIDATION-001'},
                replay_status='unused', signature={
                    'algorithm': 'ssh-ed25519', 'namespace': AUTH_NAMESPACE,
                    'identity': 'succession-owner',
                    'fingerprint': public_key_fingerprint(key.with_suffix('.pub'))})
    auth['content_sha256'] = hashlib.sha256(canonical_bytes({
        k: v for k, v in auth.items() if k not in {'signature', 'content_sha256'}
    })).hexdigest()
    schema_root = Path(__file__).resolve().parents[1] / 'contracts/project_revision_succession'
    for name, value in [('owner-policy', policy), ('authorization', auth)]:
        jsonschema.validate(value, json.loads((schema_root / f'{name}.schema.json').read_text()))
    auth_path = tmp_path / 'authorization.json'
    auth_path.write_bytes(canonical_bytes(auth))
    subprocess.run([keygen, '-Y', 'sign', '-f', str(key), '-n', AUTH_NAMESPACE,
                    str(auth_path)], check=True, capture_output=True)
    kwargs = dict(policy_path=policy_path, signature_path=auth_path.with_suffix('.json.sig'),
                  policy_evidence_reference='evidence:succession-policy-proof',
                  evidence_store=store, evidence_trust_policy_path=trust,
                  project_id='prj_test', now=NOW)
    assert verify_owner_authorization(auth, **kwargs)['valid'] is True
    with pytest.raises(SuccessionProposalBlocked, match='digest mismatch'):
        verify_owner_authorization({**auth, 'source_tree_sha256': 'b' * 64}, **kwargs)


def test_active_revision_selector_rejects_tampered_campaign(tmp_path):
    from runtime.project_revision_succession import ACTIVE_REVISION_PATH, SUCCESSION_STATE_PATH, STATE_SCHEMA, current_revision_root
    event = {**planned_event(), "event_status": "activated"}
    event_body = {key: value for key, value in event.items() if key != "event_sha256"}
    from runtime.project_revision_succession import _digest
    event["event_sha256"] = _digest(event_body)
    revision = tmp_path / ".agentic_engineering_os_px/project-revisions" / PROPOSAL["successor_project_id"]
    revision.mkdir(parents=True)
    from runtime.project_revision_succession import _digest
    campaign={"schema_version":"px.repair-campaign/1.0","project_id":PROPOSAL["successor_project_id"],"campaign_id":PROPOSAL["successor_campaign_id"],"phase":"intake","intake_open":True,"unresolved":["seed"],"revision_parent_campaign_id":PREDECESSOR["campaign_id"],"revision_parent_sha256":PREDECESSOR_SHA,"succession_event_sha256":event["event_sha256"]}
    predecessor_record={"project_id":PREDECESSOR["project_id"],"name":"predecessor","state":"active","repositories":[],"classification":"internal"}
    predecessor_policy={"campaign_id":PREDECESSOR["campaign_id"],"basis":"current_implementation"}
    predecessor_root=tmp_path/'evidence/project-revision-succession'/PREDECESSOR["campaign_id"]/PREDECESSOR_SHA
    predecessor_root.mkdir(parents=True)
    (predecessor_root/'repair-campaign.json').write_bytes(PREDECESSOR_BYTES)
    (predecessor_root/'project-record.json').write_bytes(__import__('runtime.release_signing',fromlist=['canonical_bytes']).canonical_bytes(predecessor_record))
    (predecessor_root/'validation-policy.json').write_bytes(__import__('runtime.release_signing',fromlist=['canonical_bytes']).canonical_bytes(predecessor_policy))
    validation={"schema_version":"px.validation-basis/1.0","basis":"current_implementation","authority":"OWNER-FRESH-VALIDATION-001","campaign_id":PROPOSAL["successor_campaign_id"],"revision_succession":{"event_sha256":event["event_sha256"],"predecessor_campaign_id":PREDECESSOR["campaign_id"],"predecessor_raw_sha256":PREDECESSOR_SHA,"campaign_state_sha256":hashlib.sha256(__import__('runtime.release_signing',fromlist=['canonical_bytes']).canonical_bytes(campaign)).hexdigest()}}
    record={"project_id":PROPOSAL["successor_project_id"],"name":"fixture","state":"active","repositories":[],"classification":"internal"}
    for name,value in (("repair-campaign.json",campaign),("validation-policy.json",validation),("project-record.json",record)):
        (revision/name).write_bytes(__import__('runtime.release_signing',fromlist=['canonical_bytes']).canonical_bytes(value))
    state={"schema_version":STATE_SCHEMA,"events":[event]}
    (tmp_path/SUCCESSION_STATE_PATH).parent.mkdir(parents=True,exist_ok=True)
    (tmp_path/SUCCESSION_STATE_PATH).write_text(json.dumps(state),encoding="utf-8")
    pointer={"schema_version":"px.active-project-revision/1.0","project_id":PROPOSAL["successor_project_id"],"revision_root":revision.relative_to(tmp_path).as_posix(),"event_sha256":event["event_sha256"],"campaign_sha256":hashlib.sha256((revision/"repair-campaign.json").read_bytes()).hexdigest(),"policy_sha256":hashlib.sha256((revision/"validation-policy.json").read_bytes()).hexdigest(),"project_record_sha256":hashlib.sha256((revision/"project-record.json").read_bytes()).hexdigest()}
    pointer_path=tmp_path/ACTIVE_REVISION_PATH
    pointer_path.parent.mkdir(parents=True,exist_ok=True)
    pointer_path.write_text(json.dumps(pointer),encoding="utf-8")
    (revision/"repair-campaign.json").write_text(json.dumps({**campaign,"campaign_id":"tampered"}),encoding="utf-8")
    with pytest.raises(SuccessionProposalBlocked, match="digest mismatch|active revision state is corrupt"):
        current_revision_root(tmp_path)


def test_activation_requires_non_placeholder_intake_denominator(tmp_path):
    from runtime.project_revision_succession import SuccessionLedger
    # Production activation is unreachable in a fresh fixture without configured trust evidence.
    from runtime.project_revision_succession import ACTIVE_REVISION_PATH
    ledger = SuccessionLedger(tmp_path)
    with pytest.raises((SuccessionProposalBlocked, FileNotFoundError, ValueError)):
        ledger.activate_revision(
            predecessor_campaign=PREDECESSOR, predecessor_raw_sha256=PREDECESSOR_SHA,
            proposal=PROPOSAL, owner_authorization=AUTHORIZATION,
            policy_path=tmp_path / "missing-policy.json", signature_path=tmp_path / "missing.sig",
            policy_evidence_reference="evidence:missing-policy-proof", evidence_store=tmp_path,
            evidence_trust_policy_path=tmp_path / "missing-trust.json", project_id="prj_test",
            admission_event_id="not-a-current-admission",
        )
    assert not ledger.state_path.exists()
