from dataclasses import asdict
import copy
import json
import pytest
from runtime.workflow_group_config import validate_prepared_group_node_config, agent_spec_from_group_config
from tests.test_agent_runtime import fixtures


def config():
    spec, _, _ = fixtures("bounded instructions")
    return {"execution_mode": "prepared-model-group",
            "prepared_group_reference": {"schema_version": "px.prepared-group-reference/1.0", "plan_id": "task-plan-" + "a" * 24, "plan_sha256": "b" * 64},
            "agent_spec": json.loads(json.dumps(asdict(spec))),
            "placements": {"member": {"model_id": "member", "placement_sha256": "c" * 64}}}


def test_native_agent_contract_roundtrips_without_authority():
    value = config()
    normalized = validate_prepared_group_node_config(value)
    assert normalized == value
    assert agent_spec_from_group_config(normalized["agent_spec"]) == fixtures("bounded instructions")[0]
    assert normalized is not value


@pytest.mark.parametrize("mutation", ["raw-path", "caller-approval", "extra-agent", "duplicate-binding", "wrong-member", "empty-members", "too-many-members", "nonfinite", "oversized"])
def test_untrusted_group_declarations_fail_closed(mutation):
    value = copy.deepcopy(config())
    if mutation == "raw-path":
        value["prepared_group_reference"] = {"path": "../../plan.json"}
    elif mutation == "caller-approval":
        value["approved_by"] = "human:vscode-local-user"
    elif mutation == "extra-agent":
        value["agent_spec"]["authority_granted"] = True
    elif mutation == "duplicate-binding":
        value["agent_spec"]["capability_binding_ids"] *= 2
    elif mutation == "wrong-member":
        value["placements"]["member"]["model_id"] = "different"
    elif mutation == "empty-members":
        value["placements"] = {}
    elif mutation == "too-many-members":
        value["placements"] = {str(i): {"model_id": str(i)} for i in range(13)}
    elif mutation == "nonfinite":
        value["placements"]["member"]["cost"] = float("nan")
    else:
        value["placements"]["member"]["payload"] = "x" * 262144
    with pytest.raises((ValueError, TypeError)):
        validate_prepared_group_node_config(value)


def test_workflow_declaration_uses_native_group_parser_and_stays_unadmitted(tmp_path, monkeypatch):
    from dataclasses import replace
    from runtime.workflow_studio import WorkflowStudio
    from tests.test_workflow_studio import fixture
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "keys"))
    definition, bindings, grants = fixture()
    node = replace(definition.nodes[0], approval_required=True, config=config())
    definition = replace(definition, nodes=(node,), edges=())
    root = tmp_path / "project"
    root.mkdir()
    studio = WorkflowStudio(root)
    studio.save_revision(definition)
    studio.register_authority(bindings[:1], grants, {bindings[0].binding_id: "increment"})
    receipt = studio.validate_and_admit(definition)
    assert receipt["runnable_state"] == "not_runnable"
    assert any("prepared_group_executor_not_integrated" in reason for reason in receipt["reasons"])
    tampered = config()
    tampered["placements"]["member"]["model_id"] = "wrong"
    with pytest.raises(ValueError, match="placement identity"):
        replace(node, config=tampered)


@pytest.mark.parametrize("mutation", [None, "project", "missing-member", "stale-plan", "attachment", "context", "digest"])
def test_actual_persisted_group_placement_binding(tmp_path, mutation):
    from dataclasses import replace
    from tests.test_model_group_preparation import prepared, plan_for
    from runtime.task_execution_plan import persist_task_execution_plan
    from runtime.execution_placement import _hash
    from runtime.workflow_group_config import resolve_workflow_group_plan
    group, _, _, preparation = prepared(3, tmp_path)
    plan = plan_for(group, preparation)
    persist_task_execution_plan(tmp_path, plan)
    value = config()
    value["agent_spec"] = json.loads(json.dumps(asdict(replace(fixtures("bounded instructions")[0], project_id=plan.project_id))))
    value["prepared_group_reference"] = {"schema_version": "px.prepared-group-reference/1.0", "plan_id": plan.plan_id, "plan_sha256": plan.plan_sha256}
    from runtime.model_group_preparation import member_attachment
    value["placements"] = {}
    for model in group.model_ids:
        attachment, member = member_attachment(plan.as_dict(), model)
        placement = {"model_id": model, "task_plan_sha256": plan.plan_sha256, "model_attachment_sha256": attachment["attachment_sha256"], "context_sha256": member["context_sha256"], "selected_device": "cpu"}
        placement["placement_sha256"] = _hash(placement)
        value["placements"][model] = placement
    model = group.model_ids[0]
    if mutation == "project":
        value["agent_spec"]["project_id"] = "another-project"
    elif mutation == "missing-member":
        value["placements"].pop(model)
    elif mutation:
        field = {"stale-plan": "task_plan_sha256", "attachment": "model_attachment_sha256", "context": "context_sha256", "digest": "placement_sha256"}[mutation]
        value["placements"][model][field] = "0" * 64
        if mutation != "digest":
            value["placements"][model]["placement_sha256"] = _hash({k:v for k,v in value["placements"][model].items() if k != "placement_sha256"})
    if mutation is None:
        assert resolve_workflow_group_plan(tmp_path, value).plan_sha256 == plan.plan_sha256
    else:
        with pytest.raises(PermissionError):
            resolve_workflow_group_plan(tmp_path, value)
