"""Signed service identity through actual normal preparation and plan decoding."""
from dataclasses import replace
from pathlib import Path
import pytest

from tests.test_remote_model_bridge import configured
from tests.test_model_group_preparation import plan_for
from runtime.remote_model_attachment import build_remote_model_attachment, RemoteModelAttachment
from runtime.model_attachment import model_attachment_from_dict, validate_model_attachment
from runtime.model_execution_group import BranchAssignment, RoleWorkContract, IndependenceContract, ModelExecutionGroup
from runtime.model_group_preparation import context_for_branch, context_sha256, prepare_model_group, member_execution_input
from runtime.semantic_integration_types import FusedQueryResult
from runtime.contracts import validate_instance


def prepare_remote_fixture(configured):
    _, root, _, profile, _ = configured
    attachment = build_remote_model_attachment(root, profile_id=profile['profile_id'], requester_id='human:vscode-local-user')
    branch = BranchAssignment(attachment.model_id, 'proposal', work_contract=RoleWorkContract('answer', 'a' * 64),
                              independence_contract=IndependenceContract(), agent_generation_id='remote-generation')
    retrieval = FusedQueryResult('map source', 'px', (), {}, 0, 'fixture:retrieval', 'b' * 64)
    branch = replace(branch, work_contract=RoleWorkContract('answer', context_sha256(context_for_branch(retrieval, branch))))
    group = ModelExecutionGroup('single', 'execution', 'owner', (branch,))
    prepared = prepare_model_group(group, {attachment.model_id: attachment}, {attachment.model_id: retrieval}, root=root)
    plan = plan_for(group, prepared)
    return attachment, group, prepared, plan


def test_signed_service_identity_reaches_prepared_member_and_plan(configured):
    _, root, _, _, _ = configured
    attachment, _, prepared, plan = prepare_remote_fixture(configured)
    assert type(model_attachment_from_dict(attachment.as_dict())) is RemoteModelAttachment
    assert validate_model_attachment(attachment, root=root)['valid']
    assert not {'artifact_sha256', 'benchmark_revision', 'hardware_requirements', 'local_artifact_path'} & attachment.as_dict().keys()
    invocation = member_execution_input(plan.as_dict(), prepared.as_dict()['members'][0])
    assert invocation.attachment == attachment
    assert invocation.task_plan_sha256 == plan.plan_sha256
    validate_instance(invocation.as_dict(), Path('contracts/models/member-execution-input.schema.json'))


@pytest.mark.parametrize('field,value', [('artifact_sha256', 'a' * 64), ('hardware_requirements', {}),
    ('privacy', 'local'), ('model_revision', 'latest'), ('origin', 'https://127.0.0.1'),
    ('profile_sha256', 'bad'), ('context_tokens', True)])
def test_remote_cannot_claim_local_or_unbound_identity(configured, field, value):
    _, root, _, profile, _ = configured
    value_record = build_remote_model_attachment(root, profile_id=profile['profile_id'], requester_id='human:vscode-local-user').as_dict()
    value_record[field] = value
    with pytest.raises(ValueError):
        model_attachment_from_dict(value_record)


def test_current_signed_profile_drift_is_not_adopted(configured):
    _, root, authority, profile, _ = configured
    attachment = build_remote_model_attachment(root, profile_id=profile['profile_id'], requester_id='human:vscode-local-user')
    from runtime.remote_provider_profiles import CONFIG
    import json
    path = root / CONFIG
    body = authority.verify_receipt(json.loads(path.read_text()))
    body['profiles'][0]['model_revision'] = 'different-owner-declared-revision'
    path.write_text(json.dumps(authority.sign_receipt(body)))
    assert not validate_model_attachment(attachment, root=root)['valid']


def test_native_resolver_refuses_profile_hash_masquerading_as_attachment(configured):
    from runtime.group_provider_adapters import build_group_adapter_resolver
    engine, root, _, profile, _ = configured
    attachment = build_remote_model_attachment(root, profile_id=profile['profile_id'], requester_id='human:vscode-local-user')
    config = {'schema_version': 'px.group-provider-adapters/1.0', 'adapters': {attachment.model_id: {
        'kind': 'remote_provider', 'profile_id': attachment.profile_id, 'adapter_id': attachment.adapter_id,
        'budget_id': attachment.budget_id, 'requester_id': attachment.requester_id, 'attachment_sha256': attachment.attachment_sha256}}}
    with pytest.raises(PermissionError, match='signed remote policy differs'):
        build_group_adapter_resolver(engine, root, config)(attachment.model_id)


def test_exact_native_resolver_is_observational_before_provider_use(configured):
    from runtime.group_provider_adapters import build_group_adapter_resolver, RemoteGroupProviderBinding
    from runtime.provider_gateway import build_provider_execution_policy
    import json
    engine, root, authority, profile, payload = configured
    attachment = build_remote_model_attachment(root, profile_id=profile['profile_id'], requester_id='human:vscode-local-user')
    policy = build_provider_execution_policy(task_plan_sha256=payload['execution_context']['authority_reference_sha256'],
        model={'provider_id': attachment.provider_id, 'adapter_id': attachment.adapter_id, 'model_id': attachment.provider_model_id,
               'model_revision': attachment.model_revision, 'attachment_sha256': attachment.attachment_sha256,
               'privacy': attachment.privacy, 'authority_class': attachment.authority_class},
        authority={'revision': attachment.grant_revision, 'provider_effect': True},
        egress={'mode': 'allowlist', 'allowed_destinations': [attachment.origin]},
        cost={'budget_id': attachment.budget_id, 'max_charge_microunits': 100}, fallbacks=[], exact_receipt_required=True)
    (root / attachment.policy_locator).write_text(json.dumps(authority.sign_receipt(policy)))
    config = {'schema_version': 'px.group-provider-adapters/1.0', 'adapters': {attachment.model_id: {
        'kind': 'remote_provider', 'profile_id': attachment.profile_id, 'adapter_id': attachment.adapter_id,
        'budget_id': attachment.budget_id, 'requester_id': attachment.requester_id, 'attachment_sha256': attachment.attachment_sha256}}}
    before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    binding = build_group_adapter_resolver(engine, root, config)(attachment.model_id)
    assert type(binding) is RemoteGroupProviderBinding and binding.attachment == attachment
    assert binding.policy == policy
    binding.assert_current()
    assert sorted(str(p.relative_to(root)) for p in root.rglob('*')) == before
