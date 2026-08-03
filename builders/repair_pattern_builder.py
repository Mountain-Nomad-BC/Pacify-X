"""Structured diagnostic and repair pattern proposals (PC-503)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re

from .common import BuilderError, bounded_unique, proposal_envelope, require_identifier, sanitize_text


_UNSAFE_CODE = re.compile(
    r"(?i)(?:\beval\s*\(|\bexec\s*\(|os\.system|subprocess\.|child_process|rm\s+-rf|remove-item.+-recurse)"
)


@dataclass(frozen=True, slots=True)
class RepairVariant:
    language: str
    instructions: tuple[str, ...]
    justification: str
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class RepairPatternRequest:
    pattern_id: str
    symptoms: tuple[str, ...]
    root_cause: str
    failed_approaches: tuple[str, ...]
    repair_strategy: tuple[str, ...]
    tests: tuple[str, ...]
    rollback: tuple[str, ...]
    evidence: tuple[str, ...]
    source_lineage: tuple[str, ...]
    variants: tuple[RepairVariant, ...] = ()


def propose_repair_pattern(request: RepairPatternRequest) -> dict[str, object]:
    pattern_id = require_identifier(request.pattern_id, "pattern_id")
    symptoms = bounded_unique(request.symptoms, "symptoms", maximum=16)
    if not request.root_cause.strip():
        raise BuilderError("root_cause must not be empty")
    failed = bounded_unique(request.failed_approaches, "failed_approaches", maximum=16)
    strategy = bounded_unique(request.repair_strategy, "repair_strategy", maximum=16)
    tests = bounded_unique(request.tests, "tests", maximum=16)
    rollback = bounded_unique(request.rollback, "rollback", maximum=16)
    evidence = bounded_unique(request.evidence, "evidence", maximum=16)
    lineage = bounded_unique(request.source_lineage, "source_lineage", maximum=16)
    variants = bounded_unique(request.variants, "variants", maximum=2, required=False)

    variant_payloads: list[dict[str, object]] = []
    languages: set[str] = set()
    for variant in variants:
        if variant.language not in {"python", "typescript"}:
            raise BuilderError("repair variants are limited to python and typescript")
        if variant.language in languages:
            raise BuilderError(f"duplicate repair variant: {variant.language}")
        languages.add(variant.language)
        instructions = bounded_unique(
            variant.instructions, f"{variant.language}.instructions", maximum=12
        )
        if not variant.justification.strip():
            raise BuilderError(f"{variant.language} variant requires justification")
        unsafe = bool(_UNSAFE_CODE.search(variant.snippet))
        payload: dict[str, object] = {
            "language": variant.language,
            "justification": variant.justification,
            "instructions": list(instructions),
            "status": "quarantined" if unsafe else "candidate",
            "activation_allowed": False,
            "unsafe_snippet_detected": unsafe,
        }
        if variant.snippet:
            payload["snippet_sha256"] = hashlib.sha256(variant.snippet.encode()).hexdigest()
            payload["snippet"] = "[QUARANTINED UNSAFE SNIPPET]" if unsafe else sanitize_text(variant.snippet)
        variant_payloads.append(payload)

    body = {
        "pattern": {
            "id": pattern_id,
            "status": "candidate",
            "purpose": "diagnosis-and-validated-repair",
            "symptoms": sorted(symptoms),
            "root_cause": request.root_cause,
            "failed_approaches": sorted(failed),
            "repair_strategy": list(strategy),
            "validation_tests": sorted(tests),
            "rollback": list(rollback),
            "evidence": sorted(evidence),
            "source_lineage": sorted(lineage),
            "variants": sorted(variant_payloads, key=lambda item: str(item["language"])),
            "blind_copying_allowed": False,
            "diagnosis_required_before_repair": True,
        }
    }
    return proposal_envelope("repair-pattern", pattern_id, body)
