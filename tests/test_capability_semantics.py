from __future__ import annotations

from dataclasses import replace

from runtime.capability_semantics import (
    build_capability_semantic_profile,
    validate_capability_semantic_profile,
)


def _profile():
    metadata = {
        "id": "route-specialists",
        "body": ".px/skills/route-specialists/SKILL.md",
        "contract": "contracts/skills/route-specialists.json",
        "tags": ["routing", "agents"],
        "triggers": ["choose a specialist"],
        "aliases": ["agent routing"],
        "semantic": {
            "negative_intents": ["choose a model"],
            "ambiguous_synonyms": ["routing"],
            "ambiguity_guards": [
                {"term": "routing", "disambiguate_by": "requires an agent role"}
            ],
        },
    }
    contract = {
        "id": "route-specialists",
        "owner": "runtime/agent_provider.py:route_agents",
        "provides": ["specialist selection"],
        "consumes": ["task envelope"],
        "effects": ["read local"],
        "resources": ["registry/agency_agent_registry.json"],
        "conflicts": ["direct provider execution"],
    }
    return build_capability_semantic_profile(metadata, contract, maturity="L3")


def test_profile_normalizes_every_required_semantic_dimension() -> None:
    profile = _profile()
    report = validate_capability_semantic_profile(profile)
    assert report["valid"], report["errors"]
    assert "choose a specialist" in profile.positive_intents
    assert "choose a model" in profile.negative_intents
    assert profile.inputs == ("task envelope",)
    assert profile.effects == ("read local",)


def test_positive_negative_overlap_fails_closed() -> None:
    profile = _profile()
    report = validate_capability_semantic_profile(
        replace(profile, negative_intents=profile.positive_intents)
    )
    assert not report["valid"]
    assert any("overlap" in error for error in report["errors"])


def test_owner_and_maturity_are_not_inferred_from_names() -> None:
    profile = _profile()
    assert not validate_capability_semantic_profile(
        replace(profile, canonical_owner="")
    )["valid"]
    assert not validate_capability_semantic_profile(
        replace(profile, maturity="production")
    )["valid"]


def test_ambiguous_synonym_requires_exact_guard() -> None:
    profile = _profile()
    report = validate_capability_semantic_profile(
        replace(profile, ambiguity_guards=())
    )
    assert not report["valid"]
    assert any("lack guards" in error for error in report["errors"])


def test_minimal_active_metadata_still_has_source_backed_intent() -> None:
    profile = build_capability_semantic_profile(
        {"id": "verify-output", "body": "SKILL.md", "contract": "contract.json"},
        {"id": "verify-output", "owner": "runtime/verifier.py"},
    )
    assert profile.positive_intents == ("verify output",)
    assert profile.maturity is None
