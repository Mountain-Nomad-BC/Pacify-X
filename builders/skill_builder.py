"""Proposal-only builder for bounded skill packages (PC-500)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

from .common import (
    BuilderError,
    DuplicateAssetError,
    GapNotProvenError,
    KNOWN_EFFECTS,
    bounded_unique,
    proposal_envelope,
    require_identifier,
)


@dataclass(frozen=True, slots=True)
class SkillRequest:
    capability_id: str
    purpose: str
    provides: tuple[str, ...]
    consumes: tuple[str, ...]
    effects: tuple[str, ...]
    source_references: tuple[str, ...]
    test_requirements: tuple[str, ...]
    validation_evidence: tuple[str, ...]
    restricted_sources: bool = False
    clean_room: bool | None = None
    owner: str = "independent-bootstrap"
    version: str = "0.1.0"


def propose_skill(
    request: SkillRequest,
    registry_records: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    """Create a candidate proposal only when registry metadata proves a gap."""
    capability_id = require_identifier(request.capability_id, "capability_id")
    if not request.purpose.strip():
        raise BuilderError("purpose must not be empty")
    provides = bounded_unique(request.provides, "provides", maximum=16)
    consumes = bounded_unique(request.consumes, "consumes", maximum=16)
    effects = bounded_unique(request.effects, "effects", maximum=8)
    sources = bounded_unique(request.source_references, "source_references", maximum=16)
    tests = bounded_unique(request.test_requirements, "test_requirements", maximum=16)
    evidence = bounded_unique(
        request.validation_evidence, "validation_evidence", maximum=16
    )
    unknown_effects = sorted(set(effects) - KNOWN_EFFECTS)
    if unknown_effects:
        raise BuilderError("unknown effects: " + ", ".join(unknown_effects))
    if request.restricted_sources and request.clean_room is not True:
        raise BuilderError("restricted sources require explicit clean_room status")

    wanted_outputs = set(provides)
    for record in registry_records:
        existing_id = record.get("id")
        if existing_id == capability_id:
            raise DuplicateAssetError(f"capability already exists: {capability_id}")
        existing_outputs = {
            value for value in record.get("provides", ()) if isinstance(value, str)
        }
        if wanted_outputs <= existing_outputs:
            raise GapNotProvenError(
                f"registry capability {existing_id} already provides the requested outputs"
            )

    body = {
        "gap_check": {
            "registry_gap_proven": True,
            "requested_outputs": sorted(provides),
        },
        "skill_template": {
            "id": capability_id,
            "version": request.version,
            "owner": request.owner,
            "status": "candidate",
            "purpose": request.purpose,
            "provenance": {
                "source_references": sorted(sources),
                "restricted_sources": request.restricted_sources,
                "clean_room": request.clean_room is True,
                "copied_implementation": False,
            },
            "io_contract": {
                "consumes": sorted(consumes),
                "provides": sorted(provides),
            },
            "effects": sorted(effects),
            "tests": sorted(tests),
            "validation_evidence": sorted(evidence),
            "bounded": {
                "max_inputs": 16,
                "max_outputs": 16,
                "max_effects": 8,
            },
        },
        "registry_candidate": {
            "id": capability_id,
            "visible_as": "candidate",
            "admit_after": [
                "contract_validation",
                "tests_pass",
                "evidence_current",
                "approval",
            ],
        },
    }
    return proposal_envelope("skill", capability_id, body)
