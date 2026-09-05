"""Typed, lineage-bound intake from Knowledge Foundry to Skill Studio."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
from typing import Mapping

from .knowledge_foundry import CandidateSkill, FoundryBundle, certify_foundry_bundle


SCHEMA_VERSION = "px.foundry-candidate-skill/1.0"
DRAFT_SCHEMA_VERSION = "px.skill-studio-foundry-draft/1.0"
SHA256 = re.compile(r"^[a-f0-9]{64}$")


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class FoundryCandidateSkill:
    schema_version: str
    bundle_id: str
    skill_id: str
    purpose: str
    source_lineage: tuple[Mapping[str, object], ...]
    mechanisms: tuple[str, ...]
    formulas: tuple[Mapping[str, object], ...]
    uncertainty: Mapping[str, object]
    semantics: Mapping[str, object]
    effects: tuple[str, ...]
    tests: tuple[str, ...]
    unknowns: tuple[str, ...]
    contradictions: tuple[str, ...]
    candidate_sha256: str
    lineage_signature: Mapping[str, str]
    authority_state: str = "foundry_candidate_only"


@dataclass(frozen=True, slots=True)
class SkillStudioDraft:
    schema_version: str
    candidate_sha256: str
    lineage_signature: Mapping[str, str]
    skill_id: str
    studio_decision: str
    decided_by: str
    decision_reason: str
    draft_state: str
    manifest: Mapping[str, object]
    unknowns: tuple[str, ...]
    contradictions: tuple[str, ...]
    canonical_promotion_authorized: bool
    draft_sha256: str


def _candidate_payload(candidate: FoundryCandidateSkill) -> dict[str, object]:
    payload = asdict(candidate)
    payload.pop("candidate_sha256", None)
    payload.pop("lineage_signature", None)
    return payload


def validate_foundry_candidate(candidate: FoundryCandidateSkill) -> None:
    if candidate.schema_version != SCHEMA_VERSION:
        raise ValueError("unsupported Foundry candidate schema")
    if candidate.authority_state != "foundry_candidate_only":
        raise PermissionError("Foundry candidate cannot grant canonical authority")
    if not candidate.skill_id or not candidate.tests or not candidate.source_lineage:
        raise ValueError("Foundry candidate contract is incomplete")
    for source in candidate.source_lineage:
        if not SHA256.fullmatch(str(source.get("sha256", ""))):
            raise ValueError("Foundry candidate source hash is missing or invalid")
        citation = source.get("citation")
        if not isinstance(citation, str) or not citation.strip():
            raise ValueError("Foundry candidate source citation is required")
    expected = _digest(_candidate_payload(candidate))
    if candidate.candidate_sha256 != expected:
        raise PermissionError("Foundry candidate hash mismatch")
    signature = candidate.lineage_signature
    if (
        signature.get("algorithm") != "sha256-domain-v1"
        or signature.get("signed_by") != "runtime.knowledge_foundry"
        or signature.get("value")
        != hashlib.sha256(
            b"px.foundry-candidate/1.0\0" + expected.encode("ascii")
        ).hexdigest()
    ):
        raise PermissionError("Foundry candidate lineage signature mismatch")


def export_foundry_candidate(
    bundle: FoundryBundle, skill_id: str
) -> FoundryCandidateSkill:
    certification = certify_foundry_bundle(bundle)
    if certification["decision"] != "certified_candidate":
        raise ValueError("only a certified Foundry candidate may enter Studio intake")
    matches = [skill for skill in bundle.skills if skill.skill_id == skill_id]
    if len(matches) != 1:
        raise ValueError("exactly one Foundry skill must match the requested identity")
    skill: CandidateSkill = matches[0]
    by_id = {str(source.get("source_id")): source for source in bundle.sources}
    lineage = tuple(by_id[reference] for reference in skill.references if reference in by_id)
    formulas = tuple(
        {
            "calculation_id": item.calculation_id,
            "expression": item.expression,
            "normalized_dimension": dict(item.normalized_dimension),
            "formula_engine_revision": item.formula_engine_revision,
        }
        for item in bundle.calculations
    )
    unsigned = FoundryCandidateSkill(
        SCHEMA_VERSION,
        bundle.bundle_id,
        skill.skill_id,
        skill.purpose,
        lineage,
        tuple(skill.dependencies) or ("source-derived-procedure",),
        formulas,
        {
            "confidence": skill.confidence,
            "failure_cases": skill.failure_cases,
        },
        {
            "inputs": skill.inputs,
            "outputs": skill.outputs,
            "triggers": skill.triggers,
            "examples": skill.examples,
        },
        (),
        skill.tests,
        ("runtime_effects_not_declared",),
        (),
        "",
        {},
    )
    candidate_sha256 = _digest(_candidate_payload(unsigned))
    signature = {
        "algorithm": "sha256-domain-v1",
        "signed_by": "runtime.knowledge_foundry",
        "value": hashlib.sha256(
            b"px.foundry-candidate/1.0\0" + candidate_sha256.encode("ascii")
        ).hexdigest(),
    }
    result = FoundryCandidateSkill(
        **{
            **asdict(unsigned),
            "candidate_sha256": candidate_sha256,
            "lineage_signature": signature,
        }
    )
    validate_foundry_candidate(result)
    return result


def build_skill_studio_draft(
    candidate: FoundryCandidateSkill,
    *,
    studio_decision: str,
    decided_by: str,
    decision_reason: str,
) -> SkillStudioDraft:
    """Accept or reject intake; never confer admission or promotion authority."""
    validate_foundry_candidate(candidate)
    decision = studio_decision.casefold().strip()
    if decision not in {"accept", "reject"}:
        raise ValueError("Skill Studio must explicitly accept or reject the candidate")
    if not decided_by.strip() or not decision_reason.strip():
        raise ValueError("Studio decision identity and reason are required")
    state = "draft" if decision == "accept" else "rejected"
    manifest = {
        "skill_id": candidate.skill_id,
        "purpose": candidate.purpose,
        "mechanisms": candidate.mechanisms,
        "formulas": candidate.formulas,
        "uncertainty": candidate.uncertainty,
        "semantics": candidate.semantics,
        "effects": candidate.effects,
        "tests": candidate.tests,
        "source_lineage": candidate.source_lineage,
        "source_candidate_sha256": candidate.candidate_sha256,
        "lifecycle": state,
    }
    payload = {
        "schema_version": DRAFT_SCHEMA_VERSION,
        "candidate_sha256": candidate.candidate_sha256,
        "lineage_signature": candidate.lineage_signature,
        "skill_id": candidate.skill_id,
        "studio_decision": decision,
        "decided_by": decided_by,
        "decision_reason": decision_reason,
        "draft_state": state,
        "manifest": manifest,
        "unknowns": candidate.unknowns,
        "contradictions": candidate.contradictions,
        "canonical_promotion_authorized": False,
    }
    return SkillStudioDraft(**payload, draft_sha256=_digest(payload))
