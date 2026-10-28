"""Zero-token scenarios through canonical plan, branch, convergence and verdict owners.

Scripted output is testbed evidence only; this module neither calls providers nor
manufactures production containment acknowledgments.
"""
from .generation_bound_verdict import create_verdict, digest
from .model_convergence import BranchObservation, EvidenceItem, converge
from .model_branch_contracts import canonical_digest
from .task_execution_plan import validate_task_execution_plan
from .work_disposition import WorkDisposition, settle_boundary


def run_control_plane_scenario(plan, outputs, *, containment_by_model, states=None, origin_by_model=None,
                               minimum_independent=2):
    if not validate_task_execution_plan(plan)["valid"] or plan.model_execution_group is None:
        raise ValueError("current canonical mesh task plan required")
    group = plan.model_execution_group
    if type(outputs) is not dict or set(outputs) != set(group.model_ids):
        raise ValueError("all declared branches must be scripted explicitly")
    if type(containment_by_model) is not dict or set(containment_by_model) != set(group.model_ids):
        raise ValueError("all declared containment outcomes must be explicit")
    states = {} if states is None else states
    origin_by_model = {} if origin_by_model is None else origin_by_model
    if type(states) is not dict or type(origin_by_model) is not dict or (set(states) | set(origin_by_model)) - set(group.model_ids):
        raise ValueError("scenario references unknown branch")
    observations = []
    dispositions = []
    for member in group.branches:
        output = outputs[member.model_id]
        if type(output) is not str or not output.strip():
            raise ValueError("bounded nonempty scenario output required")
        state = states.get(member.model_id, "completed")
        contracted = member.work_contract is not None and member.independence_contract is not None
        budget = member.work_contract.max_output_bytes if contracted else 524288
        if len(output.encode("utf-8")) > budget:
            raise ValueError("branch output exceeds role contract")
        if not contracted or containment_by_model[member.model_id] is not True:
            state = "not_admitted"
        observations.append(BranchObservation(member.model_id, output, canonical_digest(output),
            (EvidenceItem("stub:" + member.model_id, "independent_observation",
                          origin_by_model.get(member.model_id, "stub:" + member.model_id)),),
            contracted, containment_by_model[member.model_id], state))
        dispositions.append(WorkDisposition(member.model_id, "completed" if state == "completed" else "blocked",
                                            "deterministic testbed: " + state,
                                            None if state == "completed" else "branch:" + state))
    convergence = converge(group, observations, minimum_independent=minimum_independent)
    boundary = settle_boundary(group.model_ids, dispositions)
    verdict = create_verdict(candidate_sha256=plan.plan_sha256,
        dependencies={"task_plan": plan.plan_sha256, "model_execution_group": group.group_sha256},
        verifier_revision="px.deterministic-control-plane/1.0",
        evidence_sha256=(convergence["convergence_sha256"], boundary["boundary_sha256"]), status=convergence["status"])
    body = dict(testbed_only=True, authority_granted=False, plan_sha256=plan.plan_sha256,
                convergence=convergence, boundary=boundary, verdict=verdict)
    return {**body, "scenario_sha256": digest(body)}
