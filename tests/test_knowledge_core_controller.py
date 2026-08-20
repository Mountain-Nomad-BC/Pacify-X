from __future__ import annotations

import hashlib
import json

import pytest

import runtime.knowledge_core_controller as knowledge_module
from runtime.knowledge_core_controller import KnowledgeCoreController
from runtime.studio_api import studio_operation
from tests.studio_approval_testkit import authorized_payload


def _project(tmp_path):
    source = tmp_path / "knowledge" / "source.md"
    source.parent.mkdir(parents=True)
    source.write_text("bounded source evidence\n", encoding="utf-8")
    registry = tmp_path / "registry" / "knowledge_sources.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "schema_version": "2.0",
                "knowledge_sources": [
                    {
                        "id": "source:one",
                        "status": "active",
                        "kind": "local_file",
                        "location": "knowledge/source.md",
                        "visibility": ["local"],
                        "uses": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    policy = tmp_path / "policies" / "learning-promotion.json"
    policy.parent.mkdir(parents=True)
    policy.write_text(
        json.dumps(
            {
                "schema_version": "px.learning-promotion-policy/1.0",
                "lifecycle": [
                    "experience",
                    "evidence",
                    "pattern",
                    "hypothesis",
                    "validation",
                    "learned-candidate",
                    "measured-reuse",
                    "promotion-or-decay",
                ],
                "identity_hashes_separate_from_evidence_hashes": True,
                "aggregation_identity": "hashless-live-state",
                "required_gates": [
                    "confidence",
                    "a-b",
                    "independent-research",
                    "final-validation",
                    "dependency-current",
                ],
                "minimum_trials_per_confidence_gate": 6,
                "maximum_trials_per_confidence_gate": 200,
                "maximum_retained_pipeline_history_bytes": 33554432,
                "learning_direct_canonical_write": False,
                "loser_retention_required": True,
                "partial_promotion_allowed": True,
                "rollback_required": True,
                "automatic_destructive_retirement": False,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


def _candidate(**updates):
    value = {
        "id": "knowledge:demo",
        "kind": "fact",
        "content": {"statement": "bounded fact", "confidence": 0.9},
    }
    value.update(updates)
    return value


def _evidence(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def _authorized(root, operation, payload):
    return authorized_payload(root, "knowledge", operation, payload)


def _tree_snapshot(root):
    if not root.exists():
        return []
    return [
        (
            path.relative_to(root).as_posix(),
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in sorted(root.rglob("*"))
        if path.is_file()
    ]


def test_studio_knowledge_browse_is_empty_and_non_mutating_before_initialization(
    tmp_path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    key_root = tmp_path / "host-authority"
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(key_root))
    before_project = _tree_snapshot(project)
    before_host = _tree_snapshot(key_root)

    result = studio_operation(project, "knowledge", "browse", {"query": "", "limit": 20})

    assert result["schema_version"] == "px.knowledge-core-control/1.0"
    assert result["proposals"] == result["canonical"] == []
    assert _tree_snapshot(project) == before_project
    assert _tree_snapshot(key_root) == before_host
    assert not (project / ".engineering-bootstrap").exists()
    assert not key_root.exists()


def _approved_proposal(controller, candidate=None):
    proposal = controller.propose(
        candidate or _candidate(),
        source_ids=["source:one"],
        evidence_refs=[_evidence("test")],
        approved=True,
        proposed_by="human:owner",
    )
    verified = controller.verify(
        proposal["proposal_id"], approved=True, verified_by="reviewer:one"
    )
    assert verified["state"] == "verified"
    approved = controller.approve(
        proposal["proposal_id"], approved=True, approved_by="human:owner"
    )
    return approved


def test_knowledge_proposal_validation_approval_promotion_and_audit_browser(
    tmp_path,
) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    with pytest.raises(PermissionError, match="explicit host approval"):
        controller.propose(
            _candidate(),
            source_ids=["source:one"],
            evidence_refs=[_evidence("test")],
            approved=False,
            proposed_by="human:owner",
        )
    approved = _approved_proposal(controller)
    with pytest.raises(PermissionError, match="explicit host approval"):
        controller.promote(
            approved["proposal_id"], approved=False, promoted_by="human:owner"
        )
    promoted = controller.promote(
        approved["proposal_id"], approved=True, promoted_by="human:owner"
    )
    assert promoted["state"] == "promoted"
    assert promoted["canonical_writes_performed"] is True
    browser = controller.browse(query="knowledge:demo")
    assert len(browser["proposals"]) == len(browser["canonical"]) == 1
    assert browser["invalid_sources"] == []
    assert browser["actions"]["promote"]["route"] == "studio knowledge promote"
    events = list(
        (
            next(
                (
                    tmp_path
                    / ".engineering-bootstrap/studios/knowledge/proposals"
                ).glob("*/head.json")
            ).parent
            / "events"
        ).glob("*.json")
    )
    assert len(events) == 4


def test_knowledge_conflict_blocks_and_optimistic_supersession_can_rollback(
    tmp_path,
) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    first = _approved_proposal(controller)
    promoted_first = controller.promote(
        first["proposal_id"], approved=True, promoted_by="human:owner"
    )
    first_sha = promoted_first["candidate_sha256"]

    conflict = controller.propose(
        _candidate(content={"statement": "changed without base"}),
        source_ids=["source:one"],
        evidence_refs=[_evidence("conflict")],
        approved=True,
        proposed_by="human:owner",
    )
    blocked = controller.verify(
        conflict["proposal_id"], approved=True, verified_by="reviewer:one"
    )
    assert blocked["state"] == "blocked"
    assert "canonical_revision_conflict" in blocked["blocked_reasons"]

    update = _approved_proposal(
        controller,
        _candidate(
            content={"statement": "changed with exact base"},
            supersedes_sha256=first_sha,
        ),
    )
    promoted_update = controller.promote(
        update["proposal_id"], approved=True, promoted_by="human:owner"
    )
    assert promoted_update["candidate_sha256"] != first_sha
    rollback = controller.rollback(
        "knowledge:demo",
        first_sha,
        approved=True,
        approved_by="human:owner",
        evidence_refs=[_evidence("rollback")],
        expected_head_sha256=promoted_update["candidate_sha256"],
    )
    assert rollback["to_sha256"] == first_sha and rollback["hard_delete"] is False


def test_partial_knowledge_promotion_is_recoverable_without_new_authority(
    tmp_path, monkeypatch
) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    approved = _approved_proposal(controller)
    original_publish = controller._publish

    def interrupt(*args, **kwargs):
        raise RuntimeError("simulated interruption after canonical publish")

    monkeypatch.setattr(controller, "_publish", interrupt)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        controller.promote(
            approved["proposal_id"], approved=True, promoted_by="human:owner"
        )
    monkeypatch.setattr(controller, "_publish", original_publish)
    recovery = controller.recover(approved=True, recovered_by="human:owner")
    assert recovery["recovered"] == 1
    assert controller.browse()["proposals"][0]["state"] == "promoted"


def test_knowledge_controller_is_discoverable_through_bounded_studio_routes(
    tmp_path,
) -> None:
    _project(tmp_path)
    propose_payload = {
        "candidate": _candidate(),
        "source_ids": ["source:one"],
        "evidence_refs": [_evidence("api")],
    }
    proposed = studio_operation(
        tmp_path,
        "knowledge",
        "propose",
        _authorized(tmp_path, "propose", propose_payload),
    )
    verify_payload = {"proposal_id": proposed["proposal_id"]}
    verified = studio_operation(
        tmp_path,
        "knowledge",
        "verify",
        _authorized(tmp_path, "verify", verify_payload),
    )
    assert verified["state"] == "verified"
    browser = studio_operation(tmp_path, "knowledge", "browse", {"limit": 10})
    assert browser["proposals"][0]["proposal_id"] == proposed["proposal_id"]


def test_two_siblings_verified_from_one_head_cannot_both_promote(tmp_path) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    proposals = []
    for statement in ("first sibling", "second sibling"):
        proposed = controller.propose(
            _candidate(content={"statement": statement}),
            source_ids=["source:one"],
            evidence_refs=[_evidence(statement)],
            approved=True,
            proposed_by="human:owner",
        )
        controller.verify(proposed["proposal_id"], approved=True, verified_by="reviewer:one")
        proposals.append(
            controller.approve(proposed["proposal_id"], approved=True, approved_by="human:owner")
        )
    controller.promote(proposals[0]["proposal_id"], approved=True, promoted_by="human:owner")
    with pytest.raises(PermissionError, match="head changed after verification"):
        controller.promote(proposals[1]["proposal_id"], approved=True, promoted_by="human:owner")


def test_source_mutation_reference_only_and_unresolved_evidence_fail_closed(tmp_path) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    approved = _approved_proposal(controller)
    (tmp_path / "knowledge/source.md").write_text("mutated after verification\n", encoding="utf-8")
    with pytest.raises(PermissionError, match="identity changed"):
        controller.promote(approved["proposal_id"], approved=True, promoted_by="human:owner")

    registry_path = tmp_path / "registry/knowledge_sources.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["knowledge_sources"][0]["status"] = "reference_only"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    ineligible = controller.propose(
        _candidate(id="knowledge:reference-only"),
        source_ids=["source:one"],
        evidence_refs=[_evidence("reference")],
        approved=True,
        proposed_by="human:owner",
    )
    blocked = controller.verify(ineligible["proposal_id"], approved=True, verified_by="reviewer:one")
    assert blocked["state"] == "blocked"
    assert any(reason.startswith("source_not_eligible") for reason in blocked["blocked_reasons"])

    registry["knowledge_sources"][0]["status"] = "active"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    unresolved = controller.propose(
        _candidate(id="knowledge:unresolved-evidence"),
        source_ids=["source:one"],
        evidence_refs=["evidence:not-bound"],
        approved=True,
        proposed_by="human:owner",
    )
    blocked = controller.verify(unresolved["proposal_id"], approved=True, verified_by="reviewer:one")
    assert blocked["state"] == "blocked"
    assert any(reason.startswith("evidence_unresolved") for reason in blocked["blocked_reasons"])


def test_authenticated_trailing_proposal_event_is_recovered(tmp_path, monkeypatch) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    proposal = controller.propose(
        _candidate(), source_ids=["source:one"], evidence_refs=[_evidence("crash")],
        approved=True, proposed_by="human:owner",
    )
    original_write = knowledge_module.write_json_atomic
    armed = {"value": True}

    def interrupted_write(path, value):
        if armed["value"] and path.name == "head.json" and "proposals" in path.parts:
            armed["value"] = False
            raise RuntimeError("simulated event/head interruption")
        return original_write(path, value)

    monkeypatch.setattr(knowledge_module, "write_json_atomic", interrupted_write)
    with pytest.raises(RuntimeError, match="event/head interruption"):
        controller.verify(proposal["proposal_id"], approved=True, verified_by="reviewer:one")
    monkeypatch.setattr(knowledge_module, "write_json_atomic", original_write)
    with pytest.raises(PermissionError, match="history is incomplete"):
        controller._read(proposal["proposal_id"])
    recovery = controller.recover(approved=True, recovered_by="human:owner")
    assert recovery["projections_repaired"] == 1
    assert controller._read(proposal["proposal_id"])["state"] == "verified"


def test_learning_hash_roles_remain_bound_through_admission_and_measured_reuse(
    tmp_path,
) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    pipeline = controller.observe_experience(
        pipeline_id=None,
        operation_id="parser-lifecycle",
        task_class="repair",
        outcome="passed",
        measurements={"quality": 1.0},
        capability_ids=["px-debug-repair"],
        environment_sha256=hashlib.sha256(b"environment").hexdigest(),
        source_ids=["source:one"],
        evidence_refs=[_evidence("parser-lifecycle")],
        approved=True,
        observed_by="human:owner",
    )
    pipeline_id = pipeline["pipeline_id"]
    controller.extract_learning_pattern(
        pipeline_id,
        metric="quality",
        higher_is_better=True,
        interpretation="The challenger consistently preserves repair quality.",
        applicability=["repair"],
        approved=True,
        extracted_by="human:owner",
    )
    controller.form_learning_hypothesis(
        pipeline_id,
        unit_id="route.parser",
        kind="skill",
        claim="The bounded parser route is preferable.",
        incumbent_artifact={
            "id": "route.parser",
            "kind": "skill",
            "steps": ["parse", "trust"],
        },
        challenger_artifact={
            "id": "route.parser",
            "kind": "skill",
            "steps": ["parse", "recompute", "bind"],
        },
        dependency_sha256={},
        approved=True,
        formed_by="human:owner",
    )
    for index in range(6):
        controller.record_learning_trial(
            pipeline_id,
            winner="challenger",
            evidence_ref=_evidence(f"parser-trial-{index}"),
            approved=True,
            recorded_by="human:owner",
        )
    controller.validate_learning_research(
        pipeline_id,
        question="Does an independent check support the typed parser route?",
        references=[
            {
                "uri": "evidence:independent-parser-review",
                "evidence_ref": _evidence("parser-research"),
                "independent": True,
            }
        ],
        better_alternative_found=False,
        conclusion="No stronger bounded alternative was found.",
        secondary_artifact=None,
        approved=True,
        validated_by="reviewer:one",
    )
    validated = controller.final_validate_learning(
        pipeline_id,
        validation_evidence_ref=_evidence("parser-final"),
        partial_units=["typed-parser"],
        approved=True,
        validated_by="reviewer:one",
    )
    revision = validated["selected_revision"]
    decision = validated["promotion_decision"]
    assert len(
        {
            validated["pipeline_revision_sha256"],
            revision["artifact_sha256"],
            revision["revision_sha256"],
            decision["record_sha256"],
            decision["canonical_corpus_sha256"],
        }
    ) == 5
    admitted = controller.admit_learning_candidate(
        pipeline_id, approved=True, admitted_by="human:owner"
    )
    proposal_id = admitted["knowledge_proposal_id"]
    controller.verify(proposal_id, approved=True, verified_by="reviewer:one")
    controller.approve(proposal_id, approved=True, approved_by="human:owner")
    controller.promote(proposal_id, approved=True, promoted_by="human:owner")
    measured = controller.measure_learning_reuse(
        pipeline_id,
        uses=12,
        successes=12,
        regressions=0,
        approved=True,
        measured_by="human:owner",
    )
    assert measured["state"] == "canonical"
    assert (
        measured["reuse_measurements"][-1]["promotion_sha256"]
        == measured["promotion_decision"]["record_sha256"]
    )
    assert controller._read_learning(pipeline_id) == measured


def test_learning_read_and_recovery_reject_resigned_nested_hash_role_corruption(
    tmp_path,
) -> None:
    controller = KnowledgeCoreController(_project(tmp_path))
    pipeline = controller.observe_experience(
        pipeline_id=None,
        operation_id="parser-corruption",
        task_class="repair",
        outcome="passed",
        measurements={"quality": 1.0},
        capability_ids=["px-debug-repair"],
        environment_sha256=hashlib.sha256(b"environment").hexdigest(),
        source_ids=["source:one"],
        evidence_refs=[_evidence("parser-corruption")],
        approved=True,
        observed_by="human:owner",
    )
    root = controller._learning_root(pipeline["pipeline_id"])
    event_path = root / "events" / "00000001.json"
    event = controller._verify_signed(event_path)
    state = dict(event["state"])
    records = [dict(item) for item in state["operation_evidence"]]
    records[0]["record_sha256"] = "b" * 64
    state["operation_evidence"] = records
    revision_payload = {
        key: value
        for key, value in state.items()
        if key
        not in {
            "pipeline_revision_sha256",
            "last_event_sha256",
            "updated_utc",
        }
    }
    state["pipeline_revision_sha256"] = knowledge_module._hash(revision_payload)
    unsigned_event = {
        **{key: value for key, value in event.items() if key != "event_sha256"},
        "state": state,
    }
    corrupted_event = {
        **unsigned_event,
        "event_sha256": knowledge_module._hash(unsigned_event),
    }
    corrupted_head = {
        **state,
        "last_event_sha256": corrupted_event["event_sha256"],
    }
    knowledge_module.write_json_atomic(
        event_path, controller.authority.sign_receipt(corrupted_event)
    )
    knowledge_module.write_json_atomic(
        root / "head.json", controller.authority.sign_receipt(corrupted_head)
    )

    with pytest.raises(PermissionError, match="typed hash graph"):
        controller._read_learning(pipeline["pipeline_id"])

    (root / "head.json").unlink()
    with pytest.raises(PermissionError, match="typed hash graph"):
        controller.recover(approved=True, recovered_by="human:owner")
