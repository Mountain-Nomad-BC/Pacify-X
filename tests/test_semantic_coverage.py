"""SEM-006: the canonical coverage and ambiguity ledger.

The point of these tests is that ambiguity must stay VISIBLE. Every assertion
here checks that a gap is reported with enough detail to act on, rather than
being collapsed into a total that looks like success.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.semantic_coverage import (
    ACCEPTED,
    AMBIGUOUS,
    CONFLICTING,
    COVERAGE_EVIDENCE_RELATIVE,
    COVERAGE_SCHEMA_VERSION,
    DISPOSITIONS,
    ENTITY_INDEX_RELATIVE,
    EXTERNAL,
    HISTORICAL,
    EXCLUDED,
    UNEXPLAINED,
    DECIDED,
    REMAPPABLE,
    INTENTIONALLY_UNCLASSIFIED,
    REMAPPABLE,
    UNRESOLVED,
    CoverageError,
    CoverageLedger,
    Observation,
    ledger_from_observations,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_every_disposition_is_distinguishable_and_named() -> None:
    assert set(DISPOSITIONS) == {
        "accepted", "unresolved", "ambiguous", "conflicting",
        "external", "historical", "intentionally_unclassified", "excluded",
    }
    # EXCLUDED is a decision, not a gap: the corpus owner deliberately did not
    # admit the object. It must not count toward the remap gate.
    assert EXCLUDED in DECIDED
    assert EXCLUDED in REMAPPABLE
    assert EXCLUDED not in UNEXPLAINED


def test_an_accepted_object_must_name_its_owner() -> None:
    """ACCEPTANCE: zero unowned source objects.

    This is the single most important rule in the ledger. An accepted object
    with no owner is precisely the thing that used to vanish silently during a
    rename, so it is refused at construction rather than counted as fine.
    """
    with pytest.raises(CoverageError, match="must name its owner"):
        Observation(object_id="runtime/foo.py", disposition=ACCEPTED)
    ok = Observation(
        object_id="runtime/foo.py", disposition=ACCEPTED, owner="runtime/librarian_semantic_map.py"
    )
    assert ok.explained


def test_an_unknown_disposition_is_refused() -> None:
    with pytest.raises(CoverageError, match="is not a coverage disposition"):
        Observation(object_id="runtime/foo.py", disposition="probably_fine")


def test_ambiguity_is_recorded_with_its_rivals_not_guessed() -> None:
    """ACCEPTANCE: ambiguity remains explicit rather than guessed."""
    ambiguous = Observation(
        object_id="runtime/foo.py",
        disposition=AMBIGUOUS,
        classification="module",
        rivals=("module", "snapshot"),
        risk="high",
    )
    assert ambiguous.rivals == ("module", "snapshot")
    assert ambiguous.blocking, "a high-risk ambiguity must block its migration"

    ledger = ledger_from_observations([ambiguous])
    gate = ledger.remap_gate()
    assert gate["passed"] is False
    assert "runtime/foo.py" in gate["unexplained"]
    assert "runtime/foo.py" in gate["blocking"]


def test_only_an_ambiguous_observation_may_carry_rivals() -> None:
    with pytest.raises(CoverageError, match="only an ambiguous observation"):
        Observation(
            object_id="runtime/foo.py", disposition=UNRESOLVED, rivals=("module",)
        )


def test_low_risk_uncertainty_goes_to_review_instead_of_blocking() -> None:
    """A gate that blocks on cosmetic doubt gets ignored, which protects nothing."""
    ledger = ledger_from_observations([
        Observation(object_id="docs/readme.md", disposition=UNRESOLVED, risk="low"),
        Observation(
            object_id="runtime/foo.py", disposition=ACCEPTED, owner="runtime/paths.py"
        ),
    ])
    gate = ledger.remap_gate()
    assert gate["blocking"] == []
    assert gate["review_count"] == 1
    assert gate["passed"] is False, "an unresolved object still fails the gate"
    assert [item.object_id for item in ledger.review_queue()] == ["docs/readme.md"]


def test_a_fully_decided_corpus_passes_the_remap_gate() -> None:
    ledger = ledger_from_observations([
        Observation(object_id="runtime/foo.py", disposition=ACCEPTED, owner="runtime/paths.py"),
        Observation(object_id="third_party/bar.py", disposition=EXTERNAL, owner="upstream"),
        Observation(object_id="runtime/old.py", disposition=HISTORICAL),
        Observation(object_id="build/tmp", disposition=INTENTIONALLY_UNCLASSIFIED),
    ])
    gate = ledger.remap_gate()
    assert gate["passed"] is True
    assert gate["unexplained_count"] == 0
    assert ledger.blocking() == []


def test_high_risk_gaps_raise_when_the_gate_is_enforced() -> None:
    ledger = ledger_from_observations([
        Observation(
            object_id="runtime/foo.py", disposition=CONFLICTING, risk="high",
            note="two observations assert incompatible owners",
        ),
    ])
    with pytest.raises(CoverageError, match="high-risk semantic assignments"):
        ledger.assert_no_high_risk_gaps()


def test_a_disposition_cannot_be_silently_rewritten() -> None:
    """Changing a verdict must go through review, not a second record() call."""
    ledger = ledger_from_observations([
        Observation(object_id="runtime/foo.py", disposition=UNRESOLVED)
    ])
    with pytest.raises(CoverageError, match="already unresolved"):
        ledger.record(
            Observation(object_id="runtime/foo.py", disposition=ACCEPTED, owner="runtime/paths.py")
        )


def test_projections_separate_remappable_entities_from_gaps() -> None:
    ledger = ledger_from_observations([
        Observation(object_id="runtime/foo.py", disposition=ACCEPTED, owner="runtime/paths.py"),
        Observation(object_id="runtime/bar.py", disposition=UNRESOLVED, risk="high"),
    ])
    index = ledger.entity_index()
    ids = {row["object_id"] for row in index["entities"]}
    assert ids == {"runtime/foo.py"}, (
        "an unresolved object must never appear as a remappable entity"
    )

    evidence = ledger.evidence_document()
    assert {row["object_id"] for row in evidence["observations"]} == {
        "runtime/foo.py", "runtime/bar.py"
    }
    assert evidence["gate"]["unexplained"] == ["runtime/bar.py"]


def test_counts_cover_every_disposition_even_when_empty() -> None:
    """A zero must be a measured zero, not an absent key."""
    counts = CoverageLedger().counts()
    assert set(counts) == set(DISPOSITIONS)
    assert all(value == 0 for value in counts.values())


def test_the_declared_owner_paths_are_the_registered_card_owners() -> None:
    """The ledger must own exactly the paths SEM-006 registered."""
    assert ENTITY_INDEX_RELATIVE == "registry/semantic_entity_index.json"
    assert COVERAGE_EVIDENCE_RELATIVE == "evidence/v1x/semantic-coverage.json"


def test_published_documents_are_internally_consistent_with_the_owner() -> None:
    """The registered owners must exist and satisfy the owner's own invariants.

    This checks shape and self-consistency rather than re-deriving the corpus:
    the published documents describe the real repository, which a synthetic
    fixture cannot reproduce. What matters is that a reader can load them and
    that the index never carries an object the evidence ledger calls a gap.
    """
    index_path = REPO_ROOT / ENTITY_INDEX_RELATIVE
    evidence_path = REPO_ROOT / COVERAGE_EVIDENCE_RELATIVE
    assert index_path.is_file(), f"{ENTITY_INDEX_RELATIVE} is a registered SEM-006 owner"
    assert evidence_path.is_file(), f"{COVERAGE_EVIDENCE_RELATIVE} is a registered SEM-006 owner"

    index = json.loads(index_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    assert index["schema_version"] == COVERAGE_SCHEMA_VERSION
    assert evidence["schema_version"] == COVERAGE_SCHEMA_VERSION
    assert evidence["entity_index"] == ENTITY_INDEX_RELATIVE
    assert index["coverage_evidence"] == COVERAGE_EVIDENCE_RELATIVE

    # Every remappable entity is also an observation, and every counted
    # disposition in the index agrees with the evidence ledger's own counts.
    assert index["counts"] == evidence["counts"]

    unexplained = set(evidence["gate"]["unexplained"])
    for row in index["entities"]:
        assert row["object_id"] not in unexplained, (
            "a remappable entity must not also be an unexplained gap"
        )
        assert row["disposition"] in REMAPPABLE
        assert row["blocking"] is False
        if row["disposition"] == ACCEPTED:
            assert row["owner"], "an accepted entity must name its owner"