"""A local-only group must receive the same provider-custody preflight as a mixed group.

`require_complete_group_provider_custody` guarded its local-identity check behind
`if any(remote member)`, so a group made entirely of local members skipped
custody verification completely. The local shared writer is exactly the resource
that needs the signed native owner check, so the requirement is unconditional
for every local member.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from runtime.execution_placement import _hash
from runtime.model_execution_group import (
    BranchAssignment,
    IndependenceContract,
    ModelExecutionGroup,
    RoleWorkContract,
)
from runtime.model_group_preparation import (
    context_for_branch,
    context_sha256,
    prepare_model_group,
)
from runtime.remote_provider_placement import REMOTE_ATTACHMENT_SCHEMA, require_complete_group_provider_custody
from runtime.semantic_integration_types import FusedQueryResult
from runtime.model_attachment import build_model_attachment
from tests.test_model_group_preparation import plan_for

ROOT = Path(__file__).resolve().parents[2]


def local_plan():
    """A genuine single-local-member plan built through the real owners."""
    result = FusedQueryResult("map source", "px", (), {}, 0, "fixture:retrieval", "b" * 64)
    branch = BranchAssignment(
        "model-0",
        "proposal",
        work_contract=RoleWorkContract("answer", "a" * 64),
        independence_contract=IndependenceContract(),
        agent_generation_id="local-generation",
    )
    branch = replace(
        branch,
        work_contract=RoleWorkContract("answer", context_sha256(context_for_branch(result, branch))),
    )
    group = ModelExecutionGroup("local-fixture", "execution", "owner", (branch,), quorum="majority")
    attached = build_model_attachment(
        ROOT,
        model_id="model-0",
        model_revision="fixture-exact",
        artifact_sha256="c" * 64,
        runtime="provider-gateway",
        context_tokens=4096,
        modalities=("text",),
        supports_tools=False,
        privacy="local",
        authority_class="contained",
        benchmark_revision="d" * 64,
        hardware_requirements={"memory": "1GiB"},
    )
    preparation = prepare_model_group(group, {"model-0": attached}, {"model-0": result}, root=ROOT)
    return plan_for(group, preparation)


def test_local_plan_has_no_remote_member():
    plan = local_plan()
    members = plan.as_dict()["model_group_preparation"]["members"]
    assert members
    assert all(row["attachment"].get("schema_version") != REMOTE_ATTACHMENT_SCHEMA for row in members)


class _Binding:
    """Stand-in for a resolved local group provider binding.

    It carries the exact member identity the native owner requires, because the
    custody check verifies that the binding matches the invocation's artifact;
    a binding that does not match is refused before any provider is touched.
    """

    def __init__(self, current=True, model_id="model-0", artifact_sha256="c" * 64):
        self.policy = {"authority": {"revision": "rev-1"}}
        self.model_id = model_id
        self.artifact_sha256 = artifact_sha256
        self._current = current
        self.checked = 0

    def assert_current(self):
        self.checked += 1
        if not self._current:
            raise PermissionError("stale local provider binding")


def test_local_only_group_verifies_its_bound_adapter():
    """The custody check must reach the binding that will actually execute.

    A local-only group previously skipped this check entirely. Reaching the
    native artifact-binding assertion proves the preflight now runs; a stand-in
    binding is refused there, which is the owner's fail-closed behaviour rather
    than a gap in the test.
    """
    binding = _Binding()
    with pytest.raises(PermissionError, match="current native artifact binding"):
        require_complete_group_provider_custody(
            local_plan(), project_root=ROOT, adapter_for=lambda model_id: binding
        )


def test_local_only_group_without_bound_resolver_defers_to_the_executor():
    """Without a bound resolver the executor owns admission; this must not raise.

    `execute_governed_group` accepts an executor whose caller already resolved
    providers. Demanding host configuration here failed executions that were
    fully bound, so the unbound route defers to the executor's own refusal.
    """
    require_complete_group_provider_custody(local_plan(), project_root=ROOT)


def test_local_only_group_with_unresolved_binding_fails_closed():
    with pytest.raises(PermissionError, match="no admitted provider binding"):
        require_complete_group_provider_custody(
            local_plan(), project_root=ROOT, adapter_for=lambda model_id: None
        )


def test_stale_local_binding_is_refused():
    binding = _Binding(current=False)
    with pytest.raises(PermissionError, match="stale local provider binding"):
        require_complete_group_provider_custody(
            local_plan(), project_root=ROOT, adapter_for=lambda model_id: binding
        )
