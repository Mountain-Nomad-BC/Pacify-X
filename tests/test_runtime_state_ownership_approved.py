"""Approved runtime-state ownership records.

The custodian model fixes the deadlock in B7: every candidate owner was a writer inside
its own resource group, so registering it would have made a writer the accountable
authority for state it writes. An approved record therefore requires an owner that is
NOT a member of the group, plus an explicit approval event.

Authorization is unchanged: an approved owner still holds no standing write privilege.
"""
from __future__ import annotations

import copy

from runtime.runtime_state_ownership import (
    validate_approved_resource_record,
    validate_resource_candidate,
)

GROUP = (
    "runtime/session_store.py",
    "runtime/workspace_broker.py",
    "runtime/run_state.py",
)
CUSTODIAN = "runtime/resource_lifecycle.py"

AUTHORIZATION = {
    "per_run_governed_authorization_required": True,
    "existing_controls": ["effect_grant", "scope_lease", "effect_intent"],
    "standing_write_privilege": False,
    "registry_confers_write_authority": False,
    "registry_confers_deletion_authority": False,
}

RECORD = {
    "resource_id": "RES-01",
    "scope": "registry/session-state",
    "resource_class": "authoritative_durable",
    "accountable_owner": CUSTODIAN,
    "owner_approval_event_id": "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036534",
    "provenance": ["docs/repair/evidence/px-os-1067-runtime-state-ownership-matrix.json"],
    "retention": "retained until the run's evidence is archived",
    "lifecycle": "created on first admit, reconciled on close",
    "concurrency": "single-writer lease per run",
    "reclamation": "reclaimed only by the retirement owner after archive",
    "recovery": "rebuilt from the append-only journal",
    "authorization": AUTHORIZATION,
}


def test_a_custodian_outside_the_group_is_a_valid_owner() -> None:
    assert validate_approved_resource_record(RECORD, group_members=GROUP) == []


def test_a_writer_may_not_be_the_accountable_owner_of_its_own_group() -> None:
    record = copy.deepcopy(RECORD)
    record["accountable_owner"] = GROUP[0]
    errors = validate_approved_resource_record(record, group_members=GROUP)
    assert "accountable owner may not be a producer of the resource it would own" in errors


def test_owner_comparison_normalises_path_spellings() -> None:
    record = copy.deepcopy(RECORD)
    record["accountable_owner"] = "runtime\\session_store.py"
    errors = validate_approved_resource_record(record, group_members=GROUP)
    assert "accountable owner may not be a producer of the resource it would own" in errors


def test_approval_requires_an_event_id() -> None:
    record = copy.deepcopy(RECORD)
    record["owner_approval_event_id"] = None
    errors = validate_approved_resource_record(record, group_members=GROUP)
    assert "an approved record must cite the approval event" in errors


def test_approval_requires_a_named_owner() -> None:
    record = copy.deepcopy(RECORD)
    record["accountable_owner"] = None
    errors = validate_approved_resource_record(record, group_members=GROUP)
    assert "an approved record must name an accountable owner" in errors


def test_approval_never_confers_standing_write_or_deletion_authority() -> None:
    for field in (
        "standing_write_privilege",
        "registry_confers_write_authority",
        "registry_confers_deletion_authority",
    ):
        record = copy.deepcopy(RECORD)
        record["authorization"][field] = True
        errors = validate_approved_resource_record(record, group_members=GROUP)
        assert f"{field} must be false" in errors


def test_approved_records_still_require_existing_controls_only() -> None:
    record = copy.deepcopy(RECORD)
    record["authorization"]["existing_controls"] = ["approved_owner_override"]
    errors = validate_approved_resource_record(record, group_members=GROUP)
    assert "existing_controls must name unique existing controls" in errors


def test_candidate_records_still_forbid_owner_assignment() -> None:
    candidate = copy.deepcopy(RECORD)
    candidate["accountable_owner"] = None
    candidate["owner_approval_event_id"] = None
    assert validate_resource_candidate(candidate) == []
    promoted = copy.deepcopy(RECORD)
    errors = validate_resource_candidate(promoted)
    assert "candidate record may not assign an accountable owner" in errors


# --- Approval-event provenance enforcement -----------------------------------
#
# `owner_approval_event_id` used to be checked only for being non-empty text, so
# any string satisfied it. These tests prove the resolver-backed check rejects
# references that do not actually record an owner decision.


def _annotation_without_decision():
    return {
        "event_id": "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036534",
        "event_type": "card_annotated",
        "actor": "codex-host",
        "payload": {"card": "gap-0008", "result": "recorded"},
    }


def _annotation_with_owner_decision():
    return {
        "event_id": "gap-event:PX-OPERATIONAL-GAPS-20260816:000000036534",
        "event_type": "card_annotated",
        "actor": "codex-host",
        "payload": {
            "note": "OWNER DECISION (Ben, repository owner, 2026-11-03): approved.",
        },
    }


def test_a_bare_annotation_cannot_authorize_custody() -> None:
    from runtime.runtime_state_ownership import validate_approval_event

    errors = validate_approval_event(
        RECORD["owner_approval_event_id"], lambda _event_id: _annotation_without_decision()
    )
    assert errors == ["approval event records no owner decision and cannot authorize custody"]


def test_an_annotation_carrying_an_owner_decision_is_accepted() -> None:
    from runtime.runtime_state_ownership import validate_approval_event

    assert (
        validate_approval_event(
            RECORD["owner_approval_event_id"], lambda _event_id: _annotation_with_owner_decision()
        )
        == []
    )


def test_an_unresolvable_approval_event_fails_closed() -> None:
    from runtime.runtime_state_ownership import validate_approval_event

    errors = validate_approval_event(RECORD["owner_approval_event_id"], lambda _event_id: None)
    assert errors and "not present in the live ledger" in errors[0]


def test_a_raising_resolver_never_crashes_validation() -> None:
    from runtime.runtime_state_ownership import validate_approval_event

    def explode(_event_id):
        raise OSError("ledger unreadable")

    errors = validate_approval_event(RECORD["owner_approval_event_id"], explode)
    assert errors and "could not be resolved" in errors[0]


def test_enforcement_is_opt_in_so_existing_calls_are_unchanged() -> None:
    """Without a resolver the historical text-only contract must still hold."""
    assert validate_approved_resource_record(RECORD, group_members=GROUP) == []


def test_enforcement_applies_through_the_record_validator() -> None:
    errors = validate_approved_resource_record(
        RECORD, group_members=GROUP,
        approval_resolver=lambda _event_id: _annotation_without_decision(),
    )
    assert "approval event records no owner decision and cannot authorize custody" in errors


# --- Classifier enforcement: a registered entry must satisfy the contract -----
#
# The classifier previously read only state/registration_state/accountable_owner,
# so a record stripped to {resource_id, accountable_owner} still conferred
# "exempt". These tests pin the closed behaviour.


def _registry_document(record: dict, members: list[str]) -> dict:
    return {
        "state": "approved_custodian_registrations",
        "resources": [{
            "registration_state": "registered",
            "group_members": members,
            "record": record,
        }],
    }


def test_classifier_rejects_a_registered_entry_that_fails_the_contract(tmp_path) -> None:
    import json
    from runtime.mutating_producer_registry import _registry_owned_verdict

    (tmp_path / "registry").mkdir()
    members = ["runtime/session_store.py"]
    hollow = {"resource_id": "RES-01", "accountable_owner": "runtime/resource_lifecycle.py"}
    (tmp_path / "registry/runtime_state_ownership.json").write_text(
        json.dumps(_registry_document(hollow, members)), encoding="utf-8")

    assert _registry_owned_verdict(tmp_path, members[0]) is None


def test_classifier_accepts_a_registered_entry_that_satisfies_the_contract(tmp_path) -> None:
    import json
    from runtime.mutating_producer_registry import _registry_owned_verdict

    (tmp_path / "registry").mkdir()
    members = list(GROUP)
    (tmp_path / "registry/runtime_state_ownership.json").write_text(
        json.dumps(_registry_document(copy.deepcopy(RECORD), members)), encoding="utf-8")

    verdict = _registry_owned_verdict(tmp_path, members[0])
    assert verdict == {"classification": "exempt", "reason": "owned_durable_resource"}


def test_classifier_still_refuses_an_owner_inside_its_own_group(tmp_path) -> None:
    import json
    from runtime.mutating_producer_registry import _registry_owned_verdict

    (tmp_path / "registry").mkdir()
    members = list(GROUP)
    self_owned = copy.deepcopy(RECORD)
    self_owned["accountable_owner"] = members[0]
    (tmp_path / "registry/runtime_state_ownership.json").write_text(
        json.dumps(_registry_document(self_owned, members)), encoding="utf-8")

    assert _registry_owned_verdict(tmp_path, members[0]) is None
