"""Canonical PACIFY-X certification stage contract.

This module is deliberately dependency-light.  It is the one source of truth for
release-candidate ordering, release-stage ordering, processing phases, and the
receipt identity field used by the parameterized stage owner.

Do not duplicate these tables in runners, owners, config builders, or scanners.
Those components may add behavior, but stage identity and ordering come from here.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StageContract:
    ordinal: int
    step: str
    owner_kind: str
    phase_before: str | None
    phase_after: str | None
    release_stage: str | None
    receipt_schema: str | None
    receipt_candidate_field: str | None
    owner_command_count: int
    one_shot: bool = True


_CONTRACTS = (
    StageContract(
        1,
        "archive_clear",
        "stage_owner",
        "repair_frozen",
        "repair_frozen",
        None,
        "px.release-successor-receipt/1.0",
        "candidate_id",
        1,
    ),
    StageContract(
        2,
        "reconcile",
        "stage_owner",
        "repair_frozen",
        "revision_reconciled",
        None,
        "px.revision-reconciliation-receipt/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        3,
        "identity",
        "stage_owner",
        "revision_reconciled",
        "revision_reconciled",
        None,
        "px.single-identity-transition-receipt/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        4,
        "sections",
        "stage_owner",
        "revision_reconciled",
        "sections_current",
        "sections",
        "px.governed-sections-complete-denominator/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        5,
        "full_profile",
        "stage_owner",
        "sections_current",
        "full_profile_passed",
        "full_profile",
        "px.full-profile-receipt/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        6,
        "validate",
        "stage_owner",
        "full_profile_passed",
        "validated",
        "validate",
        "px.validation-receipt/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        7,
        "package",
        "stage_owner",
        "validated",
        "packaged",
        "package",
        "px.release-stage-evidence/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        8,
        "install",
        "stage_owner",
        "packaged",
        "installed",
        "install",
        "px.install-audit-denominator/1.0",
        "campaign_id",
        1,
    ),
    StageContract(
        9,
        "installed_operational",
        "installed_operational_owner",
        "installed",
        "installed_operational",
        "installed_operational",
        "px.installed-operational-run-summary/1.1",
        "campaign_id",
        1,
    ),
    StageContract(
        10,
        "card_reconcile",
        "ordered_card_reconcile",
        "installed_operational",
        "installed_operational",
        None,
        None,
        None,
        4,
    ),
    StageContract(
        11,
        "preflight",
        "runtime_cli",
        "installed_operational",
        "installed_operational",
        "certify",
        None,
        None,
        1,
    ),
    StageContract(
        12,
        "finalize",
        "runtime_cli",
        "installed_operational",
        "certified",
        "certify",
        None,
        None,
        1,
    ),
)

CONTRACTS: tuple[StageContract, ...] = _CONTRACTS
CONTRACT_BY_STEP: Mapping[str, StageContract] = MappingProxyType(
    {item.step: item for item in CONTRACTS}
)

STEP_ORDER = tuple(item.step for item in CONTRACTS)
STAGE_OWNER_STEPS = tuple(
    item.step for item in CONTRACTS if item.owner_kind == "stage_owner"
)

PHASE_ORDER = (
    "repair_frozen",
    "revision_reconciled",
    "sections_current",
    "full_profile_passed",
    "validated",
    "packaged",
    "installed",
    "installed_operational",
    "certified",
)

STAGE_OWNER_PHASES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        item.step: (item.phase_before, item.phase_after)
        for item in CONTRACTS
        if item.owner_kind == "stage_owner"
        and item.phase_before is not None
        and item.phase_after is not None
    }
)

PHASE_AFTER: Mapping[str, str] = MappingProxyType(
    {
        item.step: item.phase_after
        for item in CONTRACTS
        if item.phase_after is not None and item.phase_after != item.phase_before
    }
)

RELEASE_STAGES = (
    "sections",
    "full_profile",
    "validate",
    "package",
    "install",
    "installed_operational",
    "certify",
)

RELEASE_STAGE_PHASES: Mapping[str, str] = MappingProxyType(
    {
        "sections": "revision_reconciled",
        "full_profile": "sections_current",
        "validate": "full_profile_passed",
        "package": "validated",
        "install": "packaged",
        "installed_operational": "installed",
        "certify": "installed_operational",
    }
)

STAGE_AFTER: Mapping[str, str] = MappingProxyType(
    {
        item.step: item.release_stage
        for item in CONTRACTS
        if item.release_stage is not None
    }
)

STAGE_RECEIPT_SCHEMAS: Mapping[str, str] = MappingProxyType(
    {
        item.step: item.receipt_schema
        for item in CONTRACTS
        if item.owner_kind == "stage_owner" and item.receipt_schema is not None
    }
)

STAGE_RECEIPT_CANDIDATE_FIELDS: Mapping[str, str] = MappingProxyType(
    {
        item.step: item.receipt_candidate_field
        for item in CONTRACTS
        if item.owner_kind == "stage_owner"
        and item.receipt_candidate_field is not None
    }
)


def validate_contract() -> None:
    """Raise ``ValueError`` if the in-source contract is internally inconsistent."""

    if tuple(range(1, len(CONTRACTS) + 1)) != tuple(item.ordinal for item in CONTRACTS):
        raise ValueError("certification stage ordinals are not contiguous")
    if len(STEP_ORDER) != len(set(STEP_ORDER)):
        raise ValueError("certification stage names are not unique")
    if tuple(STAGE_OWNER_PHASES) != STAGE_OWNER_STEPS:
        raise ValueError("stage-owner phase contract is out of order")
    if set(RELEASE_STAGE_PHASES) != set(RELEASE_STAGES):
        raise ValueError("release-stage phase contract is incomplete")
    if tuple(RELEASE_STAGE_PHASES) != RELEASE_STAGES:
        raise ValueError("release-stage phase contract is out of order")
    if any(
        item.phase_before is not None and item.phase_before not in PHASE_ORDER
        for item in CONTRACTS
    ):
        raise ValueError("stage contract contains an unknown phase_before")
    if any(
        item.phase_after is not None and item.phase_after not in PHASE_ORDER
        for item in CONTRACTS
    ):
        raise ValueError("stage contract contains an unknown phase_after")
    if any(item.owner_command_count < 1 for item in CONTRACTS):
        raise ValueError("stage contract contains an invalid command count")
    if set(STAGE_RECEIPT_SCHEMAS) != set(STAGE_OWNER_STEPS):
        raise ValueError("stage-owner receipt schema contract is incomplete")
    if set(STAGE_RECEIPT_CANDIDATE_FIELDS) != set(STAGE_OWNER_STEPS):
        raise ValueError("stage-owner receipt candidate-field contract is incomplete")


validate_contract()
