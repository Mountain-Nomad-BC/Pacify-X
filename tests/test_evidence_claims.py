from __future__ import annotations

from pathlib import Path

from runtime.evidence_claims import (
    evidence_type_compatible,
    evaluate_feature_acceptance,
    feature_acceptance_for_card,
    validate_feature_acceptance,
    validate_feature_acceptance_requirements,
)


REVISION = "a" * 64
ROOT = Path(__file__).resolve().parents[1]


def test_evidence_type_policy_rejects_incompatible_claim_class() -> None:
    assert evidence_type_compatible(ROOT, "runtime_effect", "feature.runtime_effect")
    assert not evidence_type_compatible(ROOT, "ui_interaction", "feature.runtime_effect")


def requirements(*, authority: str = "contained", allow_na: bool = False) -> dict[str, object]:
    return {
        "schema_version": "px.feature-acceptance-requirements/1.0",
        "source_revision": REVISION,
        "dependency_revisions": {"runtime.owner": "b" * 64},
        "criteria": [
            {
                "criterion_id": "runtime-behavior",
                "required_evidence_classes": ["runtime_effect", "persistence"],
                "required_authority_class": authority,
                "required_tests": ["test_runtime_behavior"],
                "allow_not_applicable": allow_na,
            }
        ],
    }


def acceptance(*, authority: str = "contained", source: str = REVISION) -> dict[str, object]:
    return {
        "schema_version": "px.feature-acceptance/1.0",
        "source_revision": source,
        "dependency_revisions": {"runtime.owner": "b" * 64},
        "criteria": [
            {
                "criterion_id": "runtime-behavior",
                "status": "verified",
                "evidence_classes": ["runtime_effect", "persistence"],
                "authority_class": authority,
                "tests_run": ["test_runtime_behavior"],
                "evidence": [
                    {"reference": "sha256:" + "c" * 64, "claim": "Runtime behavior passed."}
                ],
            }
        ],
    }


def test_feature_acceptance_requires_current_exact_semantic_evidence() -> None:
    assert validate_feature_acceptance_requirements(requirements())["source_revision"] == REVISION
    assert validate_feature_acceptance(acceptance())["source_revision"] == REVISION
    assert evaluate_feature_acceptance(requirements(), acceptance()).verified is True

    stale = evaluate_feature_acceptance(requirements(), acceptance(source="d" * 64))
    assert stale.verified is False
    assert stale.status == "stale"
    assert "feature_acceptance_source_revision_stale" in stale.reasons


def test_external_claim_rejects_contained_evidence() -> None:
    result = evaluate_feature_acceptance(
        requirements(authority="external_authority"), acceptance(authority="contained")
    )
    assert result.verified is False
    assert "feature_acceptance_authority_mismatch:runtime-behavior" in result.reasons


def test_feature_level_not_applicable_requires_explicit_contract_and_evidence() -> None:
    value = acceptance()
    value["criteria"][0].update(
        {
            "status": "not_applicable",
            "evidence_classes": ["feature_non_applicability"],
        }
    )
    assert evaluate_feature_acceptance(requirements(allow_na=True), value).verified is True
    denied = evaluate_feature_acceptance(requirements(allow_na=False), value)
    assert denied.verified is False
    assert "feature_acceptance_not_applicable_forbidden:runtime-behavior" in denied.reasons


def test_declared_runtime_feature_without_typed_acceptance_fails_closed() -> None:
    result = feature_acceptance_for_card(
        {"required_runtime_features": ["memory-broker"]}
    )
    assert result.verified is False
    assert result.reasons == (
        "feature_acceptance_requirements_missing_for_runtime_features",
    )
