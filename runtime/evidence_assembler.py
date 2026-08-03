"""Pure, deterministic assembly of local evidence into claim support records.

The assembler performs no discovery, file reads, network access, or tool calls.
Callers must provide every claim, evidence record, and relationship explicitly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Iterable


class EvidenceKind(StrEnum):
    TEST = "test"
    INSPECTION = "inspection"
    TOOL_RESULT = "tool_result"
    REPLAY = "replay"
    APPROVAL = "approval"
    HEALTH = "health"
    BENCHMARK = "benchmark"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"


class EvidenceStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    INVALID = "invalid"


class EvidenceRelation(StrEnum):
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    CONTEXT = "context"


def _required(value: str, field: str) -> None:
    if not value.strip():
        raise ValueError(f"{field} must not be empty")


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class Claim:
    claim_id: str
    text: str

    def __post_init__(self) -> None:
        _required(self.claim_id, "claim_id")
        _required(self.text, "text")


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """A typed description of evidence already present in the caller's scope."""

    evidence_id: str
    task_id: str
    kind: EvidenceKind
    source: str
    created_at: datetime
    sensitivity: Sensitivity = Sensitivity.INTERNAL
    status: EvidenceStatus = EvidenceStatus.CURRENT

    def __post_init__(self) -> None:
        _required(self.evidence_id, "evidence_id")
        _required(self.task_id, "task_id")
        _required(self.source, "source")
        object.__setattr__(self, "kind", EvidenceKind(self.kind))
        object.__setattr__(self, "sensitivity", Sensitivity(self.sensitivity))
        object.__setattr__(self, "status", EvidenceStatus(self.status))
        object.__setattr__(self, "created_at", _aware_utc(self.created_at, "created_at"))


@dataclass(frozen=True, slots=True)
class EvidenceLink:
    claim_id: str
    evidence_id: str
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS

    def __post_init__(self) -> None:
        _required(self.claim_id, "claim_id")
        _required(self.evidence_id, "evidence_id")
        object.__setattr__(self, "relation", EvidenceRelation(self.relation))


@dataclass(frozen=True, slots=True)
class EvidenceAttachment:
    record: EvidenceRecord
    relation: EvidenceRelation
    usable_for_support: bool


@dataclass(frozen=True, slots=True)
class EvidenceWarning:
    code: str
    message: str
    claim_id: str | None = None
    evidence_id: str | None = None


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    claim: Claim
    attachments: tuple[EvidenceAttachment, ...]
    supported: bool
    warnings: tuple[EvidenceWarning, ...]


@dataclass(frozen=True, slots=True)
class EvidencePackage:
    task_id: str
    claims: tuple[ClaimEvidence, ...]
    unsupported_claims: tuple[str, ...]
    warnings: tuple[EvidenceWarning, ...]
    assembled_at: datetime


def _warning_key(warning: EvidenceWarning) -> tuple[str, str, str, str]:
    return (
        warning.claim_id or "",
        warning.evidence_id or "",
        warning.code,
        warning.message,
    )


def _unique_by_id(items: Iterable[object], attribute: str, label: str) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for item in items:
        item_id = getattr(item, attribute)
        if item_id in indexed:
            raise ValueError(f"duplicate {label}: {item_id}")
        indexed[item_id] = item
    return indexed


def assemble_evidence(
    task_id: str,
    claims: Iterable[Claim],
    evidence_records: Iterable[EvidenceRecord],
    links: Iterable[EvidenceLink],
    *,
    as_of: datetime,
    max_age: timedelta | None = None,
    strict_task_ownership: bool = True,
) -> EvidencePackage:
    """Build a deterministic claim-to-evidence package from caller-provided data.

    Evidence supports a claim only when it belongs to ``task_id``, has a current
    status, is not future-dated, and is within ``max_age`` when one is supplied.
    Other evidence is retained in the output with explicit warnings.
    """
    _required(task_id, "task_id")
    assembled_at = _aware_utc(as_of, "as_of")
    if max_age is not None and max_age < timedelta(0):
        raise ValueError("max_age must not be negative")

    claim_index = _unique_by_id(claims, "claim_id", "claim_id")
    evidence_index = _unique_by_id(evidence_records, "evidence_id", "evidence_id")

    # Set semantics remove repeated links while sorting makes caller order irrelevant.
    ordered_links = sorted(
        set(links),
        key=lambda link: (link.claim_id, link.evidence_id, link.relation.value),
    )
    links_by_claim: dict[str, list[EvidenceLink]] = {}
    package_warnings: list[EvidenceWarning] = []
    for link in ordered_links:
        if link.claim_id not in claim_index:
            package_warnings.append(
                EvidenceWarning(
                    "unknown_claim",
                    f"link references unknown claim {link.claim_id}",
                    claim_id=link.claim_id,
                    evidence_id=link.evidence_id,
                )
            )
            continue
        links_by_claim.setdefault(link.claim_id, []).append(link)

    assembled_claims: list[ClaimEvidence] = []
    unsupported: list[str] = []
    for claim_id in sorted(claim_index):
        claim = claim_index[claim_id]
        attachments: list[EvidenceAttachment] = []
        claim_warnings: list[EvidenceWarning] = []
        supported = False

        for link in links_by_claim.get(claim_id, []):
            record = evidence_index.get(link.evidence_id)
            if record is None:
                claim_warnings.append(
                    EvidenceWarning(
                        "unresolved_evidence",
                        f"evidence reference {link.evidence_id} does not resolve",
                        claim_id=claim_id,
                        evidence_id=link.evidence_id,
                    )
                )
                continue

            usable = True
            if record.task_id != task_id:
                usable = False
                claim_warnings.append(
                    EvidenceWarning(
                        "task_scope_mismatch",
                        f"evidence belongs to task {record.task_id}, not {task_id}",
                        claim_id=claim_id,
                        evidence_id=record.evidence_id,
                    )
                )
                if strict_task_ownership:
                    continue
            if record.status is not EvidenceStatus.CURRENT:
                usable = False
                claim_warnings.append(
                    EvidenceWarning(
                        f"status_{record.status.value}",
                        f"evidence status is {record.status.value}",
                        claim_id=claim_id,
                        evidence_id=record.evidence_id,
                    )
                )
            if record.created_at > assembled_at:
                usable = False
                claim_warnings.append(
                    EvidenceWarning(
                        "future_dated",
                        "evidence was created after the assembly time",
                        claim_id=claim_id,
                        evidence_id=record.evidence_id,
                    )
                )
            elif max_age is not None and assembled_at - record.created_at > max_age:
                usable = False
                claim_warnings.append(
                    EvidenceWarning(
                        "freshness_expired",
                        f"evidence exceeds the freshness limit of {max_age}",
                        claim_id=claim_id,
                        evidence_id=record.evidence_id,
                    )
                )

            attachments.append(EvidenceAttachment(record, link.relation, usable))
            if link.relation is EvidenceRelation.SUPPORTS and usable:
                supported = True
            elif link.relation is EvidenceRelation.CONTRADICTS and usable:
                claim_warnings.append(
                    EvidenceWarning(
                        "contradictory_evidence",
                        "current evidence contradicts this claim",
                        claim_id=claim_id,
                        evidence_id=record.evidence_id,
                    )
                )

        attachments.sort(key=lambda item: (item.record.evidence_id, item.relation.value))
        claim_warnings.sort(key=_warning_key)
        if not supported:
            unsupported.append(claim_id)
            claim_warnings.append(
                EvidenceWarning(
                    "unsupported_claim",
                    "claim has no usable supporting evidence",
                    claim_id=claim_id,
                )
            )
            claim_warnings.sort(key=_warning_key)

        typed_claim = claim
        assert isinstance(typed_claim, Claim)  # narrowed after generic duplicate checking
        assembled_claims.append(
            ClaimEvidence(typed_claim, tuple(attachments), supported, tuple(claim_warnings))
        )
        package_warnings.extend(claim_warnings)

    package_warnings.sort(key=_warning_key)
    return EvidencePackage(
        task_id=task_id,
        claims=tuple(assembled_claims),
        unsupported_claims=tuple(unsupported),
        warnings=tuple(package_warnings),
        assembled_at=assembled_at,
    )
