from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from runtime.foundry_studio_bridge import (
    build_skill_studio_draft,
    export_foundry_candidate,
    validate_foundry_candidate,
)
from runtime.knowledge_foundry import SourceArtifact, compile_foundry_bundle


def _bundle(*, citation: str | None = "Internal design note, revision 1"):
    text = "# Calculation\n- Apply formula units with evidence and validation.\n"
    source = SourceArtifact(
        "design",
        "engineering_note",
        "memory:design",
        hashlib.sha256(text.encode()).hexdigest(),
        text,
        "internal-reference",
        citation,
        "1",
    )
    return compile_foundry_bundle((source,))


def test_accept_preserves_lineage_unknowns_and_never_promotes() -> None:
    bundle = _bundle()
    candidate = export_foundry_candidate(bundle, bundle.skills[0].skill_id)
    draft = build_skill_studio_draft(
        candidate,
        studio_decision="accept",
        decided_by="reviewer:fixture",
        decision_reason="bounded draft review",
    )
    assert draft.draft_state == "draft"
    assert draft.manifest["source_candidate_sha256"] == candidate.candidate_sha256
    assert draft.manifest["source_lineage"] == candidate.source_lineage
    assert draft.unknowns == ("runtime_effects_not_declared",)
    assert draft.manifest["effects"] == ()
    assert draft.canonical_promotion_authorized is False


def test_reject_retains_candidate_lineage() -> None:
    bundle = _bundle()
    candidate = export_foundry_candidate(bundle, bundle.skills[0].skill_id)
    draft = build_skill_studio_draft(
        candidate,
        studio_decision="reject",
        decided_by="reviewer:fixture",
        decision_reason="effects remain unknown",
    )
    assert draft.draft_state == "rejected"
    assert draft.candidate_sha256 == candidate.candidate_sha256
    assert draft.canonical_promotion_authorized is False


def test_missing_citation_and_tampered_hash_fail_closed() -> None:
    bundle = _bundle(citation=None)
    with pytest.raises(ValueError, match="citation"):
        export_foundry_candidate(bundle, bundle.skills[0].skill_id)
    valid_bundle = _bundle()
    candidate = export_foundry_candidate(valid_bundle, valid_bundle.skills[0].skill_id)
    with pytest.raises(PermissionError, match="hash mismatch"):
        validate_foundry_candidate(replace(candidate, purpose="widened"))


def test_studio_decision_is_mandatory_and_foundry_cannot_claim_authority() -> None:
    bundle = _bundle()
    candidate = export_foundry_candidate(bundle, bundle.skills[0].skill_id)
    with pytest.raises(ValueError, match="accept or reject"):
        build_skill_studio_draft(
            candidate,
            studio_decision="promote",
            decided_by="reviewer:fixture",
            decision_reason="attempt direct promotion",
        )
    with pytest.raises(PermissionError, match="cannot grant canonical authority"):
        validate_foundry_candidate(replace(candidate, authority_state="canonical"))
