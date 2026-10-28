"""Typed evidence independence, sparse critique and dissent; no execution authority."""
from __future__ import annotations

from dataclasses import dataclass, asdict
import math

from .generation_bound_verdict import digest, sha256_text
from .model_execution_group import ModelExecutionGroup

EVIDENCE_KINDS = {"primary", "independent_observation", "derived", "peer_derived"}


def text(value):
    if type(value) is not str or not value.strip() or len(value) > 512 or any(ord(c) < 32 for c in value):
        raise ValueError("bounded nonempty text required")


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    kind: str
    origin_id: str

    def __post_init__(self):
        text(self.evidence_id)
        text(self.origin_id)
        if self.kind not in EVIDENCE_KINDS:
            raise ValueError("unknown evidence classification")


@dataclass(frozen=True)
class BranchObservation:
    model_id: str
    conclusion: str
    artifact_sha256: str | None
    evidence: tuple[EvidenceItem, ...]
    isolation_proven: bool
    containment_proven: bool
    state: str = "completed"

    def __post_init__(self):
        text(self.model_id)
        text(self.conclusion)
        if self.artifact_sha256 is None:
            if self.state == "completed":
                raise ValueError("completed observation requires actual artifact digest")
        else:
            sha256_text(self.artifact_sha256)
        if type(self.evidence) is not tuple or len(self.evidence) > 256 or any(type(e) is not EvidenceItem for e in self.evidence):
            raise ValueError("bounded typed evidence required")
        if type(self.isolation_proven) is not bool or type(self.containment_proven) is not bool:
            raise ValueError("isolation and containment must be explicit booleans")
        if self.state not in {"completed", "failed", "starved", "killed", "not_admitted"}:
            raise ValueError("invalid branch disposition")


def critique_edges(model_ids, fanout=2):
    ids = tuple(model_ids)
    if not 1 <= len(ids) <= 12 or len(set(ids)) != len(ids) or type(fanout) is not int or not 0 <= fanout <= 11:
        raise ValueError("invalid bounded critique graph")
    return tuple((source, ids[(index + offset) % len(ids)]) for index, source in enumerate(ids)
                 for offset in range(1, min(fanout, len(ids) - 1) + 1))


def converge(group: ModelExecutionGroup, observations, *, minimum_independent=2, threshold=0.75):
    if type(group) is not ModelExecutionGroup:
        raise ValueError("canonical group required")
    if type(minimum_independent) is not int or not 1 <= minimum_independent <= group.branch_count:
        raise ValueError("invalid independent quorum")
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0.5 <= threshold <= 1:
        raise ValueError("invalid convergence threshold")
    rows = tuple(observations)
    if len(rows) != group.branch_count or any(type(row) is not BranchObservation for row in rows):
        raise ValueError("every declared branch needs a typed terminal observation")
    by_id = {row.model_id: row for row in rows}
    if len(by_id) != len(rows) or set(by_id) != set(group.model_ids):
        raise ValueError("branch membership does not match canonical group")
    rows = tuple(by_id[mid] for mid in group.model_ids)
    contracts = {branch.model_id: branch for branch in group.branches}
    eligible = [row for row in rows if row.state == "completed" and row.isolation_proven and row.containment_proven
                and contracts[row.model_id].work_contract is not None
                and contracts[row.model_id].independence_contract is not None]
    # Connected overlapping observation origins are one effective independent unit.
    clusters = []
    for row in eligible:
        origins = {e.origin_id for e in row.evidence if e.kind == "independent_observation"}
        if not origins:
            continue
        matches = [c for c in clusters if c[0] & origins]
        members = [row]
        for c in matches:
            origins |= c[0]
            members.extend(c[1])
            clusters.remove(c)
        clusters.append((origins, members))
    votes = {}
    for _, members in clusters:
        conclusions = {row.conclusion for row in members}
        if len(conclusions) == 1:
            conclusion = next(iter(conclusions))
            votes[conclusion] = votes.get(conclusion, 0) + 1
    leading = sorted(votes, key=lambda c: (-votes[c], c))
    conclusion = leading[0] if leading else None
    support = votes.get(conclusion, 0) / len(clusters) if clusters else 0
    sufficient = (group.produces_outputs and len(eligible) >= group.quorum_size()
                  and len(clusters) >= max(minimum_independent, group.quorum_size()) and support >= threshold)
    body = dict(schema_version="px.independent-convergence/1.0", group_id=group.group_id,
                group_sha256=digest(group.digest_input()), status="PASS" if sufficient else "INDETERMINATE",
                conclusion=conclusion if sufficient else None, declared_count=group.branch_count,
                eligible_count=len(eligible), effective_independent_count=len(clusters), support=support,
                observations=[asdict(row) for row in rows],
                dissent=[row.model_id for row in rows if row.conclusion != conclusion],
                not_admitted=[row.model_id for row in rows if row not in eligible],
                critique_edges=[list(e) for e in critique_edges(group.model_ids)], authority_granted=False)
    return {**body, "convergence_sha256": digest(body)}


def converge_committed_group(root, plan, artifacts, attestations, *, resolver,
                             accepted_producers, actor_id, minimum_independent=None,
                             containment_proofs=None):
    """Consume actual committed images and native signed/scoped attestations.

    Missing containment evidence remains NOT_ADMITTED. This consumes external
    evidence; it does not enroll agents or synthesize Gremlin acknowledgments.

    Containment claims must be present in the verified signed branch assessment.
    Optional caller-supplied proof dictionaries are advisory and cannot turn a
    missing signed postcondition into a pass. Native live custody remains an
    additional execution-owner prerequisite.
    """
    from pathlib import Path
    import hashlib
    from .task_execution_plan import task_execution_plan_from_dict, validate_task_execution_plan
    from .model_group_preparation import member_attachment, member_execution_input
    from .model_branch_artifacts import read_branch_artifact
    from .trusted_evidence import TrustedEvidenceResolver, EvidenceScope
    from .generation_bound_verdict import create_verdict
    from .work_disposition import WorkDisposition, settle_boundary

    if isinstance(plan, dict):
        plan = task_execution_plan_from_dict(plan)
    if not validate_task_execution_plan(plan)["valid"] or plan.model_execution_group is None:
        raise ValueError("committed convergence requires intact canonical group plan")
    if type(resolver) is not TrustedEvidenceResolver:
        raise ValueError("native trusted evidence resolver required")
    group = plan.model_execution_group
    if type(artifacts) is not dict or type(attestations) is not dict or set(artifacts) != set(group.model_ids) or set(attestations) != set(group.model_ids):
        raise ValueError("every declared member requires explicit artifact/attestation disposition")
    observations, dispositions, resolved_receipts, evidence_digests = [], [], [], []
    for model in group.model_ids:
        artifact = artifacts[model]
        conclusion, evidence, artifact_sha = "not admitted", (), None
        admitted, reasons = False, []
        try:
            if artifact is None or attestations[model] is None:
                raise ValueError("committed artifact or signed attestation unavailable")
            _, member = member_attachment(plan.as_dict(), model)
            invocation = member_execution_input(plan.as_dict(), member)
            read_branch_artifact(root, artifact, invocation, run_id=artifact["run_id"])
            artifact_sha = artifact["output_sha256"]
            assessment = resolver.resolve(attestations[model], scope=EvidenceScope(
                plan.project_id, "model-branch:" + artifact["artifact_sha256"],
                task_id=plan.plan_id, execution_id=artifact["run_id"], actor_id=actor_id,
                session_id=invocation.agent_generation_id), accepted_producers=accepted_producers,
                required_type="postcondition", max_age_seconds=300)
            if not assessment.verified:
                raise ValueError("signed branch assessment refused: " + ",".join(assessment.reasons))
            result = assessment.record["result"]
            gated = {"branch_isolation", "independence_commit_before_peer_visibility"}
            containment_gated = {"process_tree_monitoring", "network_attribution"}
            for key in gated | containment_gated:
                satisfied = result["postconditions"].get(key) is True
                # Caller-authored proven dictionaries cannot replace signed evidence.
                if not satisfied:
                    raise ValueError("branch isolation/containment/commit conditions not proven")
            conclusion = result["conclusion"]
            text(conclusion)
            rows = result["evidence"]
            if type(rows) is not list or not 1 <= len(rows) <= 256:
                raise ValueError("bounded typed branch evidence required")
            evidence = tuple(EvidenceItem(**row) for row in rows)
            admitted = True
            evidence_digests.extend((artifact["artifact_sha256"], assessment.record["content_sha256"]))
        except (ValueError, TypeError, KeyError, OSError) as error:
            conclusion, evidence = "not admitted", ()
            reasons.append(str(error)[:512])
        observations.append(BranchObservation(model, conclusion, artifact_sha, evidence,
            admitted, admitted, "completed" if admitted else "not_admitted"))
        dispositions.append(WorkDisposition(model, "completed" if admitted else "blocked",
            "committed independent branch verified" if admitted else "; ".join(reasons),
            None if admitted else "signed-current-branch-assessment:" + model))
        resolved_receipts.append({"model_id": model, "admitted": admitted, "reasons": reasons,
                                  "attestation": attestations[model]})
    independent = min(group.branch_count, max(2, group.quorum_size())) if minimum_independent is None else minimum_independent
    convergence = converge(group, observations, minimum_independent=independent)
    boundary = settle_boundary(group.model_ids, dispositions)
    dependencies = {"task_plan": plan.plan_sha256, "model_execution_group": group.group_sha256,
                    "model_contract_set": group.contract_set_sha256}
    if plan.context_generation is not None:
        dependencies["context_generation"] = plan.context_generation.vector_sha256
    verifier_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    verdict = create_verdict(candidate_sha256=plan.plan_sha256, dependencies=dependencies,
        verifier_revision="source-sha256:" + verifier_sha,
        evidence_sha256=tuple(dict.fromkeys([convergence["convergence_sha256"], boundary["boundary_sha256"], *evidence_digests])),
        status=convergence["status"])
    body = {"convergence": convergence, "boundary": boundary, "verdict": verdict,
            "branch_assessments": resolved_receipts, "authority_granted": False}
    return {**body, "assessment_sha256": digest(body)}
