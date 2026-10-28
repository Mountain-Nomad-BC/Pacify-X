from dataclasses import replace
import pytest
from tests.test_remote_profile_catalog import profile_config
from tests.test_remote_attachment_identity import attachment
from tests.test_model_group_preparation import plan_for
from runtime.model_execution_group import BranchAssignment, RoleWorkContract, IndependenceContract, ModelExecutionGroup
from runtime.model_group_preparation import context_for_branch, context_sha256, prepare_model_group
from runtime.semantic_integration_types import FusedQueryResult
from runtime.remote_provider_placement import route_remote_provider, validate_remote_provider_placement, require_complete_group_provider_custody
from runtime.execution_placement import _hash


def remote_plan(profile_config):
    root, *_ = profile_config
    attached = attachment(profile_config)
    result = FusedQueryResult("map source", "px", (), {}, 0, "fixture:retrieval", "b" * 64)
    branch = BranchAssignment(attached.model_id, "proposal", work_contract=RoleWorkContract("answer", "a" * 64), independence_contract=IndependenceContract(), agent_generation_id="remote-generation")
    branch = replace(branch, work_contract=RoleWorkContract("answer", context_sha256(context_for_branch(result, branch))))
    group = ModelExecutionGroup("remote-fixture", "execution", "owner", (branch,), quorum="majority")
    preparation = prepare_model_group(group, {attached.model_id: attached}, {attached.model_id: result}, root=root)
    return plan_for(group, preparation), attached


def test_remote_placement_binds_actual_signed_service_and_native_grant(profile_config):
    root, *_ = profile_config
    plan, attached = remote_plan(profile_config)
    placement = route_remote_provider(plan.as_dict(), project_root=root, model_id=attached.model_id)
    assert validate_remote_provider_placement(placement, plan.as_dict(), project_root=root) == placement
    assert placement["reservation_owner"] == "runtime.provider_gateway"
    assert "selected_device" not in placement
    require_complete_group_provider_custody(plan, project_root=root)


@pytest.mark.parametrize("field", ["provider_id", "origin", "task_plan_sha256", "context_sha256"])
def test_rehashed_remote_placement_cannot_change_service_or_plan(profile_config, field):
    root, *_ = profile_config
    plan, attached = remote_plan(profile_config)
    placement = route_remote_provider(plan.as_dict(), project_root=root, model_id=attached.model_id)
    placement[field] = "substitution"
    placement["placement_sha256"] = _hash({k:v for k,v in placement.items() if k != "placement_sha256"})
    with pytest.raises(ValueError):
        validate_remote_provider_placement(placement, plan.as_dict(), project_root=root)


def test_remote_placement_refuses_stale_current_profile(profile_config):
    import json
    root, authority, row, body, path = profile_config
    plan, attached = remote_plan(profile_config)
    row["model_revision"] = "changed-revision"
    path.write_text(json.dumps(authority.sign_receipt(body)), encoding="utf-8")
    with pytest.raises(ValueError):
        route_remote_provider(plan.as_dict(), project_root=root, model_id=attached.model_id)
