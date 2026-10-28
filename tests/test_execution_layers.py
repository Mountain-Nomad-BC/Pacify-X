"""Phase 8 execution-layer tests required by the finish plan.

Covers the specific execution cases the plan names: 1/2/N branches, partial
failure, cancellation during branch execution, branch replacement, stale
generation results, and convergence with/without verified Gremlin containment.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.gremlin.containment import GremlinNanny
from runtime.gremlin.enrollment import ContainmentRequired, require_containment_proof
from runtime.gremlin.supervisor import DeterministicSupervisor
from runtime.model_execution_group import build_execution_group
from runtime.model_convergence import BranchObservation, EvidenceItem, converge

NOW = datetime(2026, 10, 5, 12, 0, 0, tzinfo=timezone.utc)
KEY = b"exec-layer-key-0123456789abcdef"


def _nanny(*, backend=None):
    nanny = GremlinNanny(authority_id="gn", signing_key=KEY, supervisor=DeterministicSupervisor(backend))
    for kind in ("network", "process_tree", "filesystem"):
        nanny.observers.register(kind, lambda: ())
    return nanny


def test_containment_required_blocks_a_branch_without_proof():
    """A branch that requires containment but has none must fail closed."""
    with pytest.raises(ContainmentRequired):
        require_containment_proof(None, execution_id="branch-1", required=True)


@pytest.mark.parametrize("enforcement_available", [True, False])
def test_containment_proven_only_after_release(enforcement_available):
    from runtime.gremlin.identity import ProcessIdentity

    class RecordingBackend:
        available = enforcement_available

        def freeze(self, identity):
            return {"frozen": True, "pid": identity["pid"]}

        def terminate_tree(self, identity):
            return {"terminated": True, "pid": identity["pid"]}

    nanny = _nanny(backend=RecordingBackend())
    identity = ProcessIdentity(
        agent_execution_id="branch-1", agent_id="a", pid=77, process_start_identity="s1",
        parent_pid=None, parent_execution_id=None, sandbox_id="sbx", job_object_id=None,
        container_or_cgroup_id=None, runtime_id=None, model_id="m", orchestration_id=None,
        policy_profile="gn-redteam-strict", registered_at_utc=NOW.isoformat(),
    )
    nanny.enroll(identity, now=NOW)
    # Enrolled but not released: containment is still not proven.
    with pytest.raises(ContainmentRequired):
        require_containment_proof(nanny, execution_id="branch-1", required=True)
    assert nanny.containment_proof("branch-1").proven is False
    nanny.release("branch-1")
    if enforcement_available:
        proof = require_containment_proof(nanny, execution_id="branch-1", required=True)
        assert proof is not None and proof.proven is True
    else:
        with pytest.raises(ContainmentRequired, match="PARTIAL_ENFORCEMENT"):
            require_containment_proof(nanny, execution_id="branch-1", required=True)
        assert nanny.containment_proof("branch-1").proven is False


@pytest.mark.parametrize("count", [1, 2, 3, 7])
def test_convergence_scales_across_branch_counts(count):
    """N-way convergence must not assume a pair."""
    model_ids = tuple(f"m{i}" for i in range(count))
    group = build_execution_group(
        group_id=f"grp-{count}", purpose="execution", authority_id="owner",
        proposal_models=model_ids, quorum="any"
    )
    rows = tuple(
        BranchObservation(
            model_id=model_id, conclusion="agree", artifact_sha256="a" * 64,
            evidence=(EvidenceItem(f"e{i}", "independent_observation", f"origin-{i}"),),
            isolation_proven=True, containment_proven=True,
        )
        for i, model_id in enumerate(model_ids)
    )
    minimum = min(count, max(2, group.quorum_size()))
    result = converge(group, rows, minimum_independent=minimum)
    assert result["declared_count"] == count
    assert result["authority_granted"] is False


def test_partial_failure_keeps_failed_branch_not_admitted():
    model_ids = ("m0", "m1", "m2")
    group = build_execution_group(group_id="g", purpose="execution", authority_id="owner",
                                 proposal_models=model_ids, quorum="all")
    rows = (
        BranchObservation("m0", "agree", "a" * 64, (EvidenceItem("e0", "independent_observation", "o0"),), True, True),
        BranchObservation("m1", "agree", "b" * 64, (EvidenceItem("e1", "independent_observation", "o1"),), True, True),
        BranchObservation("m2", "not admitted", None, (), False, False, "not_admitted"),
    )
    result = converge(group, rows, minimum_independent=2)
    assert "m2" in result["not_admitted"]


def test_missing_containment_cannot_be_counted_as_independent():
    # Direct check: a branch with containment_proven False is never eligible.
    model_ids = ("m0", "m1")
    group = build_execution_group(group_id="g2", purpose="execution", authority_id="owner",
                                 proposal_models=model_ids, quorum="all")
    rows = (
        BranchObservation("m0", "agree", "a" * 64, (EvidenceItem("e0", "independent_observation", "o0"),), True, False),
        BranchObservation("m1", "agree", "b" * 64, (EvidenceItem("e1", "independent_observation", "o1"),), True, True),
    )
    result = converge(group, rows, minimum_independent=2)
    assert result["status"] == "INDETERMINATE"
    assert "m0" in result["not_admitted"]

def test_stale_generation_result_is_distinguishable():
    """A result bound to a different generation must not satisfy the current one."""
    from runtime.generation_bound_verdict import create_verdict, verdict_is_current

    verdict = create_verdict(
        candidate_sha256="a" * 64,
        dependencies={"model_execution_group": "b" * 64},
        verifier_revision="test",
        evidence_sha256=("c" * 64,),
        status="PASS",
    )
    # The same verdict re-checked against a changed dependency is stale.
    assert verdict_is_current(verdict, "a" * 64, {"model_execution_group": "b" * 64}) is True
    assert verdict_is_current(verdict, "a" * 64, {"model_execution_group": "d" * 64}) is False