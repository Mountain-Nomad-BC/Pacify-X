import pytest
from runtime.context_generation import context_vector, read_context_vector, COMPONENTS


def test_extended_generation_vector_roundtrip_and_legacy_digest_stability():
    import hashlib
    from runtime.json_io import bounded_canonical_json_bytes
    components = dict.fromkeys(COMPONENTS, "revision")
    legacy = context_vector("px", "scope", components)
    body = legacy.as_mapping()
    body.pop("vector_sha256")
    assert legacy.vector_sha256 == hashlib.sha256(bounded_canonical_json_bytes(body, max_bytes=32768)).hexdigest()
    extended = context_vector("px", "scope", {**components, "model_execution_group_revision": "a" * 64})
    assert extended.as_mapping()["schema_version"] == "px.context-generation-vector/2.0"
    assert read_context_vector(extended.as_mapping()) == extended
    assert extended.vector_sha256 != legacy.vector_sha256


def test_network_policy_and_contract_drift_block_execution_projection():
    from runtime.projection_gate import evaluate_projection
    components = {**dict.fromkeys(COMPONENTS, "revision"), "model_execution_group_revision": "a" * 64,
                  "model_contract_set_revision": "b" * 64, "network_policy_revision": "c" * 64,
                  "workflow_adapter_revision": "d" * 64, "gremlin_revision": "observed-external-revision"}
    before = context_vector("px", "scope", components)
    after = context_vector("px", "scope", {**components, "network_policy_revision": "e" * 64})
    result = evaluate_projection("mesh", before, after, purpose="execute")
    assert not result.serve_allowed and "network_policy_revision" in result.stale_dependencies


def test_deferred_gremlin_generation_cannot_be_invented_as_current():
    from runtime.projection_gate import evaluate_projection
    components = {**dict.fromkeys(COMPONENTS, "revision"), "model_execution_group_revision": "a" * 64}
    vector = context_vector("px", "scope", components)
    result = evaluate_projection("mesh", vector, vector, purpose="execute")
    assert not result.serve_allowed
    assert "gremlin_revision" in result.stale_dependencies


def test_normal_plan_request_requires_exact_current_generation():
    from runtime.capability_routing import route_task, compile_route_plan
    from runtime.skill_navigator import CapabilitySummary
    from runtime.model_execution_group import build_execution_group
    from runtime.execution_contract import execution_request_from_plan
    from runtime.task_execution_plan import task_execution_plan_from_dict
    from runtime.contracts import validate_instance
    from pathlib import Path
    group = build_execution_group("mesh", "execution", "owner", proposal_models=("m1",))
    components = {**dict.fromkeys(COMPONENTS, "revision"), "source_revision": "source",
                  "model_execution_group_revision": group.group_sha256,
                  "model_contract_set_revision": group.contract_set_sha256,
                  "gremlin_revision": "test-fixture-only", "network_policy_revision": "network-1",
                  "workflow_adapter_revision": "adapter-1"}
    vector = context_vector("px", "scope", components)
    route = route_task("map repository", {"skills": [CapabilitySummary(
        "skill:map", "map repository source", capability_tags=("repository", "map"),
        triggers=("map repository",))]})
    plan = compile_route_plan(route, project_id="px", source_revision="source",
        projection_revisions={"semantic": "revision"}, effect_budget=("read_local",),
        authority_bindings=("owner",), model_execution_group=group, context_generation=vector,
        created_utc="2026-10-04T00:00:00Z")
    validate_instance(plan.as_dict(), Path("contracts/task_execution_plan.schema.json"))
    recovered = task_execution_plan_from_dict(plan.as_dict())
    request = execution_request_from_plan(recovered, current_context_generation=vector)
    assert request.model_execution_group_sha256 == group.group_sha256
    assert request.context_generation_sha256 == vector.vector_sha256
    with pytest.raises(ValueError, match="current observed"):
        execution_request_from_plan(recovered)
    changed = context_vector("px", "scope", {**components, "network_policy_revision": "network-2"})
    with pytest.raises(ValueError, match="blocked"):
        execution_request_from_plan(recovered, current_context_generation=changed)
