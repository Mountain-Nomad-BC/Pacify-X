"""Canonical, source-backed semantic profiles for routable capabilities."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Mapping, Sequence


SCHEMA_VERSION = "px.capability-semantic-profile/1.0"
MATURITY_LEVELS = frozenset({"L0", "L1", "L2", "L3", "L4", "L5", "L6"})
_WORDS = re.compile(r"[a-z0-9]+")


def _values(*groups: object) -> tuple[str, ...]:
    values: set[str] = set()
    for group in groups:
        if isinstance(group, str):
            group = (group,)
        if isinstance(group, Sequence):
            values.update(
                " ".join(_WORDS.findall(str(item).casefold()))
                for item in group
                if str(item).strip()
            )
    return tuple(sorted(value for value in values if value))


@dataclass(frozen=True, slots=True)
class CapabilitySemanticProfile:
    schema_version: str
    capability_id: str
    canonical_owner: str
    positive_intents: tuple[str, ...]
    negative_intents: tuple[str, ...]
    domains: tuple[str, ...]
    mechanisms: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    effects: tuple[str, ...]
    exclusions: tuple[str, ...]
    synonyms: tuple[str, ...]
    ambiguous_synonyms: tuple[str, ...]
    ambiguity_guards: tuple[tuple[str, str], ...]
    failure_modes: tuple[str, ...]
    maturity: str | None
    evidence_sources: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "capability_id": self.capability_id,
            "canonical_owner": self.canonical_owner,
            "positive_intents": list(self.positive_intents),
            "negative_intents": list(self.negative_intents),
            "domains": list(self.domains),
            "mechanisms": list(self.mechanisms),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "effects": list(self.effects),
            "exclusions": list(self.exclusions),
            "synonyms": list(self.synonyms),
            "ambiguous_synonyms": list(self.ambiguous_synonyms),
            "ambiguity_guards": [
                {"term": term, "disambiguate_by": guard}
                for term, guard in self.ambiguity_guards
            ],
            "failure_modes": list(self.failure_modes),
            "maturity": self.maturity,
            "evidence_sources": list(self.evidence_sources),
        }


def build_capability_semantic_profile(
    metadata: Mapping[str, object],
    contract: Mapping[str, object],
    *,
    maturity: str | None = None,
) -> CapabilitySemanticProfile:
    """Normalize declared metadata and contracts without model inference."""
    capability_id = str(metadata.get("id") or contract.get("id") or "").strip()
    semantic = metadata.get("semantic")
    semantic = semantic if isinstance(semantic, Mapping) else {}
    aliases = metadata.get("aliases", ())
    triggers = metadata.get("triggers", ())
    provides = contract.get("provides", ())
    positive = _values(
        semantic.get("positive_intents", ()),
        provides,
        triggers,
        (capability_id.replace("-", " "),),
    )
    guards_value = semantic.get("ambiguity_guards", ())
    guards: list[tuple[str, str]] = []
    if isinstance(guards_value, Sequence) and not isinstance(guards_value, (str, bytes)):
        for item in guards_value:
            if isinstance(item, Mapping):
                term = _values(str(item.get("term") or ""))
                guard = str(item.get("disambiguate_by") or "").strip()
                if term and guard:
                    guards.append((term[0], guard))
    profile = CapabilitySemanticProfile(
        SCHEMA_VERSION,
        capability_id,
        str(
            contract.get("owner")
            or metadata.get("owner")
            or metadata.get("admission_record")
            or ""
        ).strip(),
        positive,
        _values(semantic.get("negative_intents", ()), metadata.get("negative_matches", ())),
        _values(semantic.get("domains", ()), metadata.get("tags", ())),
        _values(semantic.get("mechanisms", ()), contract.get("resources", ())),
        _values(contract.get("consumes", ()), semantic.get("inputs", ())),
        _values(provides, semantic.get("outputs", ())),
        _values(contract.get("effects", ())),
        _values(semantic.get("exclusions", ()), contract.get("conflicts", ())),
        _values(semantic.get("synonyms", ()), aliases, (capability_id.replace("-", " "),)),
        _values(semantic.get("ambiguous_synonyms", ())),
        tuple(sorted(set(guards))),
        _values(
            semantic.get("failure_modes", ()),
            ("missing required input", "effect not authorized"),
        ),
        maturity,
        tuple(
            sorted(
                {
                    str(metadata.get("body") or "catalog metadata"),
                    str(metadata.get("contract") or "capability contract"),
                }
            )
        ),
    )
    report = validate_capability_semantic_profile(profile)
    if not report["valid"]:
        raise ValueError("invalid capability semantic profile: " + "; ".join(report["errors"]))
    return profile


def validate_capability_semantic_profile(
    profile: CapabilitySemanticProfile | Mapping[str, object],
) -> dict[str, object]:
    value = profile.as_dict() if isinstance(profile, CapabilitySemanticProfile) else dict(profile)
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if not value.get("capability_id"):
        errors.append("capability_id is required")
    if not value.get("canonical_owner"):
        errors.append("canonical owner is required")
    positive = set(map(str, value.get("positive_intents", ())))
    negative = set(map(str, value.get("negative_intents", ())))
    if not positive:
        errors.append("at least one positive intent is required")
    overlap = sorted(positive & negative)
    if overlap:
        errors.append(f"positive and negative intents overlap: {overlap}")
    maturity = value.get("maturity")
    if maturity is not None and maturity not in MATURITY_LEVELS:
        errors.append(f"unsupported maturity claim: {maturity}")
    guards = value.get("ambiguity_guards", ())
    guarded = {
        str(item.get("term"))
        for item in guards
        if isinstance(item, Mapping) and item.get("disambiguate_by")
    }
    ambiguous = set(map(str, value.get("ambiguous_synonyms", ())))
    missing_guards = sorted(ambiguous - guarded)
    if missing_guards:
        errors.append(f"ambiguous synonyms lack guards: {missing_guards}")
    for field in (
        "positive_intents",
        "negative_intents",
        "domains",
        "mechanisms",
        "inputs",
        "outputs",
        "effects",
        "exclusions",
        "synonyms",
        "failure_modes",
        "evidence_sources",
    ):
        items = value.get(field)
        if not isinstance(items, (list, tuple)) or any(not str(item).strip() for item in items):
            errors.append(f"{field} must be a non-empty-string array")
        elif list(items) != sorted(set(map(str, items))):
            errors.append(f"{field} must be sorted and unique")
    return {
        "schema_version": SCHEMA_VERSION,
        "valid": not errors,
        "capability_id": value.get("capability_id"),
        "errors": errors,
    }
