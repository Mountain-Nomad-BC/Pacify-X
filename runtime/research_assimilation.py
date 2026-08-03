"""Citation-bound research assimilation and cross-source canonicalization."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from .contracts import validate_instance


WORD = re.compile(r"[a-z0-9]+")
RESEARCH_CONTRACTS = {
    "research-record": "research-record.schema.json",
    "operationalization-record": "operationalization-record.schema.json",
    "experiment-card": "experiment-card.schema.json",
    "bootstrap-status": "bootstrap-status.schema.json",
    "skill-manifest": "skill-manifest.schema.json",
}


def validate_research_candidate(root: Path, kind: str, record: dict[str, object]) -> dict[str, object]:
    schema_name = RESEARCH_CONTRACTS.get(kind)
    if schema_name is None:
        raise ValueError(f"unknown research candidate kind: {kind}")
    validate_instance(record, root / "contracts/research_ops" / schema_name)
    return {
        "valid": True, "kind": kind, "state": "candidate_only",
        "auto_activate": False, "schema": f"contracts/research_ops/{schema_name}",
    }


def _stable(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class ResearchMechanism:
    source_id: str
    source_sha256: str
    citation: str
    capability_id: str
    claim: str
    mechanism: str
    assumptions: tuple[str, ...]
    evaluation_context: str
    limitations: tuple[str, ...]
    reproduction_requirements: tuple[str, ...]


def canonicalize_research(mechanisms: Iterable[ResearchMechanism]) -> dict[str, object]:
    values = tuple(mechanisms)
    if not values:
        raise ValueError("research assimilation requires at least one mechanism")
    errors = []
    for item in values:
        if not item.source_id or len(item.source_sha256) != 64:
            errors.append(f"invalid_source_identity:{item.source_id or 'unknown'}")
        if not item.citation.strip():
            errors.append(f"citation_missing:{item.source_id}")
        if not all((item.claim.strip(), item.mechanism.strip(), item.evaluation_context.strip())):
            errors.append(f"mechanism_incomplete:{item.source_id}")
        if not item.assumptions or not item.limitations or not item.reproduction_requirements:
            errors.append(f"boundary_evidence_incomplete:{item.source_id}")
    groups: dict[str, list[ResearchMechanism]] = {}
    for item in values:
        groups.setdefault(item.capability_id, []).append(item)
    candidates = []
    for capability_id, items in sorted(groups.items()):
        independent_sources = len({item.citation.casefold().strip() for item in items})
        mechanism_tokens = [set(WORD.findall(item.mechanism.casefold())) for item in items]
        shared = set.intersection(*mechanism_tokens) if mechanism_tokens else set()
        candidates.append({
            "capability_id": capability_id,
            "source_ids": tuple(sorted(item.source_id for item in items)),
            "independent_source_count": independent_sources,
            "recurring_mechanism_terms": tuple(sorted(shared)),
            "convergence": "multi_source" if independent_sources >= 2 else "single_source",
            "assumptions": tuple(sorted({value for item in items for value in item.assumptions})),
            "limitations": tuple(sorted({value for item in items for value in item.limitations})),
            "reproduction_requirements": tuple(sorted({value for item in items for value in item.reproduction_requirements})),
            "state": "candidate_experiment",
            "production_proof": False,
            "auto_activate": False,
        })
    return {
        "state": "blocked" if errors else "candidate",
        "errors": tuple(sorted(set(errors))),
        "sources": tuple(asdict(item) for item in values),
        "candidates": tuple(candidates),
        "bundle_sha256": _stable([asdict(item) for item in values]),
        "production_proof": False,
        "auto_activate": False,
    }


def admission_experiment(candidate: dict[str, object], *, local_tests: Iterable[str], negative_tests: Iterable[str]) -> dict[str, object]:
    positive = tuple(sorted(set(map(str, local_tests))))
    negative = tuple(sorted(set(map(str, negative_tests))))
    reasons = []
    if candidate.get("state") != "candidate_experiment":
        reasons.append("candidate_state_invalid")
    if not positive:
        reasons.append("local_reproduction_tests_missing")
    if not negative:
        reasons.append("negative_boundary_tests_missing")
    return {
        "decision": "ready_for_local_experiment" if not reasons else "blocked",
        "reasons": tuple(reasons), "positive_tests": positive, "negative_tests": negative,
        "activation": "candidate_only", "auto_activate": False,
    }
