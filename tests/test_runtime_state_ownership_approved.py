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
