from __future__ import annotations

from pathlib import Path

from runtime.capability_maturity import (
    evaluate_capability_maturity,
    load_maturity_policy,
    validate_maturity_policy,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = "a" * 64
DEPENDENCIES = {"semantic": "b" * 64}


def _evidence(
    evidence_type: str,
    index: int,
    *,
    authority: str = "contained",
    source: str = SOURCE,
) -> dict[str, object]:
    return {
        "evidence_id": f"evidence-{index}",
        "evidence_type": evidence_type,
        "authority_class": authority,
        "source_revision": source,
        "dependency_revisions": DEPENDENCIES,
        "valid": True,
    }


def _rows() -> list[dict[str, object]]:
    return [
        _evidence("knowledge_artifact", 0),
        _evidence("contract", 1),
        _evidence("reference", 2),
        _evidence("executable", 3),
        _evidence("behavioral_validation", 4),
        _evidence("operational_verification", 5, authority="installed_host"),
        _evidence("external_certification", 6, authority="external_authority"),
    ]


def _evaluate(rows: list[dict[str, object]]) -> dict[str, object]:
    return evaluate_capability_maturity(
        {"capability_id": "skill:test", "claimed_level": "L6", "evidence": rows},
        current_source_revision=SOURCE,
        current_dependency_revisions=DEPENDENCIES,
        policy=load_maturity_policy(ROOT),
    )


def test_live_policy_is_monotonic_and_complete() -> None:
    report = validate_maturity_policy(load_maturity_policy(ROOT))
    assert report["valid"], report["errors"]
    assert report["level_count"] == 7


def test_all_current_evidence_reaches_l6() -> None:
    decision = _evaluate(_rows())
    assert decision["level"] == "L6"
    assert decision["complete"] is True


def test_name_or_claim_cannot_create_maturity() -> None:
    decision = _evaluate([])
    assert decision["level"] is None
    assert decision["verified"] is False


def test_missing_lower_level_cannot_be_skipped() -> None:
    rows = _rows()
    del rows[1]
    decision = _evaluate(rows)
    assert decision["level"] == "L0"
    assert decision["missing_evidence"] == ["contract"]


def test_stale_l4_evidence_caps_maturity_at_l3() -> None:
    rows = _rows()
    rows[4] = _evidence("behavioral_validation", 4, source="c" * 64)
    decision = _evaluate(rows)
    assert decision["level"] == "L3"
    assert "stale_evidence:behavioral_validation" in decision["reasons"]


def test_contained_evidence_cannot_yield_l6() -> None:
    rows = _rows()
    rows[6] = _evidence("external_certification", 6)
    decision = _evaluate(rows)
    assert decision["level"] == "L5"
    assert "external_certification_requires_external_authority" in decision["reasons"]
