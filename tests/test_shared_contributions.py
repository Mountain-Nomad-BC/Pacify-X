from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import pytest

from runtime.shared_contributions import (
    ContributionGraph, make_contribution, make_verification_record,
    validate_contribution, validate_verification, verification_summary,
)
from runtime.learning_promotion import (
    content_hash, confidence_gate, compare_revisions, freeze_evaluation_contract,
    freeze_revision, promote_revision_with_shared_evidence, research_validation,
    assert_holdout_clean,
)
from runtime.memory_fabric import MemoryRecord, link_shared_contribution
from runtime.memory_broker import materialize_shared_contribution_context
from runtime.process_memory import process_outcome_contribution_evidence

H = "a" * 64
ROOT = Path(__file__).parents[1]


def contribution(kind="result", publisher="agent-a", **kw):
    return make_contribution(
        project_id="project", publisher_id=publisher, contribution_type=kind,
        description="bounded shared result", evidence_sha256=[H] if kind in {"result","negative_result","correction"} else [],
        created_at="2026-09-20T12:00:00+00:00", **kw,
    )


def verification(target, verifier="agent-b", verdict="confirmed"):
    return make_verification_record(
        target_sha256=target, verifier_id=verifier, evaluator_sha256="b"*64,
        reproduction_sha256="c"*64, verdict=verdict, evidence_sha256=["d"*64],
        verified_at="2026-09-20T12:01:00+00:00",
    )


def test_contribution_and_verification_are_content_addressed_and_authority_neutral():
    row = contribution(); validate_contribution(row)
    check = verification(row["record_sha256"]); validate_verification(check)
    assert row["authority_granted"] is False
    assert check["authority_granted"] is False
    tampered = dict(row); tampered["description"] = "changed"
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_contribution(tampered)


def test_graph_requires_complete_same_project_acyclic_lineage_and_retains_negative_results():
    root = contribution("insight")
    negative = contribution("negative_result", parent_sha256=[root["record_sha256"]])
    graph = ContributionGraph([root, negative])
    assert graph.negative_results() == (negative["record_sha256"],)
    orphan = contribution("insight", parent_sha256=["f"*64])
    with pytest.raises(ValueError, match="missing contribution parent"):
        ContributionGraph([orphan])


def test_independent_verification_excludes_self_and_failed_verdict_blocks_gate():
    row = contribution(publisher="agent-a")
    self_v = verification(row["record_sha256"], verifier="agent-a")
    good = verification(row["record_sha256"], verifier="agent-b")
    summary = verification_summary(row, [self_v, good])
    assert summary["passed"] is True and summary["independent_verifier_count"] == 1
    failed = verification(row["record_sha256"], verifier="agent-c", verdict="failed")
    assert verification_summary(row, [good, failed])["passed"] is False


def test_evaluation_freeze_rejects_holdout_feedback_and_binds_shared_promotion():
    freeze = freeze_evaluation_contract(
        experiment_id="exp", unit_id="unit", kind="skill", evaluator_sha256="1"*64,
        acceptance_policy_sha256="2"*64, development_case_ids=["dev"], holdout_case_ids=["hold"],
        environment_sha256="3"*64, harness_sha256="4"*64, toolset_sha256="5"*64,
        capability_metrics={"quality":{"minimum":1}}, efficiency_metrics={"latency":"lower"},
        backend_id="local", seed_policy="fixed", budget_policy={"max_trials":20},
    )
    assert_holdout_clean(freeze, [{"case_id":"dev","use":"revision"}])
    with pytest.raises(PermissionError, match="holdout"):
        assert_holdout_clean(freeze, [{"case_id":"hold","use":"debug"}])

    incumbent = freeze_revision(unit_id="unit", kind="skill", artifact={"v":1}, evidence_sha256=[H])
    challenger = freeze_revision(unit_id="unit", kind="skill", artifact={"v":2}, evidence_sha256=[H], parent_revision_sha256=incumbent["revision_sha256"], tier=2)
    trials = [{"winner":"challenger", "evidence_sha256":content_hash({"i":i})} for i in range(18)] + [{"winner":"incumbent", "evidence_sha256":content_hash({"i":i})} for i in range(18,20)]
    comparison = compare_revisions(incumbent=incumbent, challenger=challenger, trials=trials)
    research = research_validation(question="better?", references=[{"uri":"evidence:x","evidence_sha256":H}], better_alternative_found=False, conclusion="bounded")
    row = contribution(); summary = verification_summary(row, [verification(row["record_sha256"])])
    decision = promote_revision_with_shared_evidence(
        revision=challenger, confidence=confidence_gate(wins=18, losses=2), comparison=comparison,
        research=research, final_validation_sha256=H, current_dependencies={}, evaluation_freeze=freeze,
        evidence_case_roles=[{"case_id":"dev","use":"revision"}], contribution=row,
        verification_records=[verification(row["record_sha256"])], negative_result_sha256=["e"*64],
    )
    assert decision["passed"] is True
    assert decision["holdout_feedback_allowed"] is False
    assert decision["learning_direct_write_allowed"] is False


def _memory():
    now = datetime(2026,9,20,tzinfo=timezone.utc)
    return MemoryRecord(
        memory_id="mem", workspace_id="workspace", project_id="project", owner_id="agent-a",
        session_id="session", lease_id="lease", title="memory", memory_type="decision",
        summary="bounded", source_artifact="source", source_sha256=H, evidence_locator="evd",
        epistemic_status="observation", confidence=.9, confidence_method="direct", classification="internal",
        acl=("project",), observed_at=now, effective_at=now, certification_status="trusted",
        retrieval_enabled=True,
    )


def test_memory_link_and_context_do_not_conflate_publication_with_memory_visibility():
    row = contribution(memory_refs=["mem"]); summary = verification_summary(row, [verification(row["record_sha256"])])
    link = link_shared_contribution(_memory(), contribution=row, verification_sha256=summary["verification_sha256"], contribution_visibility="public-candidate", publication_state="published")
    assert link["publication_changes_memory_visibility"] is False
    context = materialize_shared_contribution_context([row], [verification(row["record_sha256"])], project_id="project")
    assert context["item_count"] == 1 and context["authority_granted"] is False


def test_process_outcomes_emit_candidate_contributions_not_promotions():
    process = {
        "schema_version":"1.0", "goal":"Audit repository", "outcome":"Evidence reconciled",
        "decisions":[{"decision":"compose validators","reason":"bounded","alternatives":["manual"]}],
        "tools":[{"tool":"pytest","reason":"checks","effects":["read_local"]}],
        "steps":["discover", "validate"],
        "failures":[{"failure":"stale", "recovery":"rebuild", "verified":True}],
        "verification":{"outcome_met":True,"checks":["tests"]},
        "reusable_pattern":"validate with evidence", "evidence":["receipt"],
    }
    result = process_outcome_contribution_evidence(ROOT, process, project_id="project", publisher_id="agent", outcome="failed", outcome_evidence_sha256="9"*64, failed_branch="validation")
    assert result["contribution"]["contribution_type"] == "negative_result"
    assert result["promotion_allowed"] is False

def test_memory_link_rejects_cross_project_contribution():
    foreign = make_contribution(project_id="other", publisher_id="agent", contribution_type="result", description="foreign", evidence_sha256=[H], created_at="2026-09-20T12:00:00+00:00")
    with pytest.raises(ValueError, match="project"):
        link_shared_contribution(_memory(), contribution=foreign, verification_sha256=[], contribution_visibility="project", publication_state="unpublished")


def test_same_verifier_same_timestamp_with_different_verdict_is_ambiguous():
    row = contribution()
    one = verification(row["record_sha256"], verifier="agent-b", verdict="confirmed")
    two = verification(row["record_sha256"], verifier="agent-b", verdict="failed")
    # helper fixes the same timestamp, so two different records would otherwise be input-order dependent.
    with pytest.raises(ValueError, match="ambiguous"):
        verification_summary(row, [one, two])

def test_negative_result_cannot_be_used_as_affirmative_promotion_basis():
    freeze = freeze_evaluation_contract(experiment_id="exp-n", unit_id="unit-n", kind="skill", evaluator_sha256="1"*64, acceptance_policy_sha256="2"*64, development_case_ids=["dev"], holdout_case_ids=["hold"], environment_sha256="3"*64, harness_sha256="4"*64, toolset_sha256="5"*64, capability_metrics={"q":{"minimum":1}}, efficiency_metrics={"latency":"lower"}, backend_id="local", seed_policy="fixed", budget_policy={"max":1})
    incumbent=freeze_revision(unit_id="unit-n",kind="skill",artifact={"v":1},evidence_sha256=[H])
    challenger=freeze_revision(unit_id="unit-n",kind="skill",artifact={"v":2},evidence_sha256=[H],parent_revision_sha256=incumbent["revision_sha256"],tier=2)
    trials=[{"winner":"challenger","evidence_sha256":content_hash({"n":i})} for i in range(20)]
    comparison=compare_revisions(incumbent=incumbent,challenger=challenger,trials=trials)
    research=research_validation(question="q",references=[{"uri":"evidence:q","evidence_sha256":H}],better_alternative_found=False,conclusion="c")
    negative=contribution("negative_result")
    with pytest.raises(PermissionError, match="affirmative"):
        promote_revision_with_shared_evidence(revision=challenger,confidence=comparison["gate"],comparison=comparison,research=research,final_validation_sha256=H,current_dependencies={},evaluation_freeze=freeze,evidence_case_roles=[],contribution=negative,verification_records=[verification(negative["record_sha256"])],negative_result_sha256=[negative["record_sha256"]])
