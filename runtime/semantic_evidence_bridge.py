"""Bind semantic query results into PX evidence records without claiming source authority."""
from __future__ import annotations

from datetime import datetime, timezone

from .evidence_assembler import Claim, EvidenceKind, EvidenceLink, EvidenceRecord, EvidenceRelation, Sensitivity, assemble_evidence
from .semantic_code_types import stable_id
from .semantic_integration_limits import SemanticIntegrationLimits
from .semantic_integration_types import SemanticEvidence


def bind_semantic_evidence(
    task_id: str,
    claim_text: str,
    evidence: tuple[SemanticEvidence, ...],
    *,
    as_of: datetime | None = None,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
):
    if type(evidence) is not tuple:
        raise TypeError("evidence must be a tuple")
    if len(evidence) > limits.max_evidence_items:
        raise ValueError("semantic evidence item budget exceeded")
    moment = as_of or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    claim_id = stable_id("claim", task_id, claim_text)
    claim = Claim(claim_id, claim_text)
    records = []
    links = []
    seen_sources: set[tuple[str, str | None]] = set()
    for item in evidence:
        identity = (item.source_id, item.revision)
        if identity in seen_sources:
            raise ValueError("duplicate semantic evidence source/revision")
        seen_sources.add(identity)
        evidence_id = stable_id("evidence", task_id, item.source_id, item.revision or "")
        records.append(
            EvidenceRecord(
                evidence_id,
                task_id,
                EvidenceKind.TOOL_RESULT,
                f"{item.lineage}:{item.locator}",
                moment,
                Sensitivity.INTERNAL,
            )
        )
        links.append(EvidenceLink(claim_id, evidence_id, EvidenceRelation.SUPPORTS))
    return assemble_evidence(
        task_id,
        (claim,),
        tuple(records),
        tuple(links),
        as_of=moment,
    )
