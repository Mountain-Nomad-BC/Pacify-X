"""Distinct signed profiles must never collapse to a vendor's wire model name."""
from dataclasses import replace
import json
import pytest
from tests.test_remote_model_bridge import configured
from tests.test_model_group_preparation import plan_for
from runtime.remote_model_attachment import build_remote_model_attachment
from runtime.remote_provider_profiles import CONFIG, ROOT
from runtime.studio_models import EffectGrant
from runtime.model_execution_group import BranchAssignment, RoleWorkContract, IndependenceContract, ModelExecutionGroup
from runtime.model_group_preparation import context_for_branch, context_sha256, prepare_model_group, member_execution_input
from runtime.semantic_integration_types import FusedQueryResult


def qualified_fixture(configured, second_provider):
    _, root, authority, profile, _ = configured
    config = authority.verify_receipt(json.loads((root / CONFIG).read_text()))
    second = {**profile, 'profile_id': 'second-qualified-profile', 'policy_locator': ROOT + '/second-policy.json'}
    if second_provider == 'openai':
        second.update(provider_id='openai', adapter_id='openai-responses', origin='https://api.openai.com', grant_id='second-remote-grant')
        authority.admit_grant(EffectGrant(second['grant_id'], 'human:vscode-local-user', ('read', 'write', 'network'),
            (ROOT, second['origin']), 'fixture-owner', ('unit-explicit-remote-permission',), '2099-01-01T00:00:00Z', 'admitted'))
    config['profiles'].append(second)
    (root / CONFIG).write_text(json.dumps(authority.sign_receipt(config)))
    attachments = [build_remote_model_attachment(root, profile_id=row['profile_id'], requester_id='human:vscode-local-user')
                   for row in (profile, second)]
    return root, attachments


def prepare_qualified_fixture(configured, second_provider='custom'):
    root, attachments = qualified_fixture(configured, second_provider)
    branches, retrievals = [], {}
    for index, attachment in enumerate(attachments):
        branch = BranchAssignment(attachment.model_id, 'proposal', work_contract=RoleWorkContract('answer', 'a' * 64),
            independence_contract=IndependenceContract(), agent_generation_id='qualified-generation-' + str(index))
        retrieval = FusedQueryResult('map source', 'px', (), {}, 0, 'unit:retrieval', 'b' * 64)
        branch = replace(branch, work_contract=RoleWorkContract('answer', context_sha256(context_for_branch(retrieval, branch))))
        branches.append(branch)
        retrievals[attachment.model_id] = retrieval
    group = ModelExecutionGroup('mesh', 'execution', 'owner', tuple(branches))
    prepared = prepare_model_group(group, {row.model_id: row for row in attachments}, retrievals, root=root)
    plan = plan_for(group, prepared)
    return attachments[0], group, prepared, plan


@pytest.mark.parametrize('second_provider', ['custom', 'openai'])
def test_same_wire_model_reaches_two_distinct_canonical_prepared_members(configured, second_provider):
    attachment, group, prepared, plan = prepare_qualified_fixture(configured, second_provider)
    assert len(set(group.model_ids)) == 2
    assert all(row['attachment']['provider_model_id'] == attachment.provider_model_id for row in prepared.as_dict()['members'])
    invocations = [member_execution_input(plan.as_dict(), row) for row in prepared.as_dict()['members']]
    assert {row.model_id for row in invocations} == set(group.model_ids)
    assert len({row.context_sha256 for row in invocations}) == 2


def test_two_qualified_members_use_actual_native_provider_owner(configured, monkeypatch):
    from tests.test_remote_group_effect_owner import remote_group_fixture
    from tests.test_remote_member_effect_owner import run
    f = remote_group_fixture(configured, monkeypatch, prepare=prepare_qualified_fixture)
    receipt = run(f)
    assert receipt['control_state'] == 'succeeded', receipt['member_failures']
    assert len(receipt['member_receipts']) == 2
    assert len(f['transport'].calls) == 2


def test_preparation_resolves_installed_framework_contracts(configured, monkeypatch, tmp_path):
    import shutil
    import runtime.paths as paths
    import runtime.model_group_preparation as owner
    source = paths.framework_root()
    share = tmp_path / 'install/share/agentic-engineering-os-px'
    for relative in ('bootstrap/startup.toml', 'contracts/model_attachment.schema.json',
                     'contracts/remote_model_attachment.schema.json',
                     'contracts/operations/remote-provider-profile.schema.json',
                     'contracts/models/model-group-preparation.schema.json',
                     'contracts/models/member-execution-input.schema.json'):
        target = share / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, target)
    package = tmp_path / 'site-packages/runtime'
    monkeypatch.setattr(paths, '__file__', str(package / 'paths.py'))
    monkeypatch.setattr(owner, '__file__', str(package / 'model_group_preparation.py'))
    monkeypatch.setattr(paths.sysconfig, 'get_path', lambda name: str(tmp_path / 'install'))
    _, _, prepared, plan = prepare_qualified_fixture(configured)
    assert paths.framework_root() == share
    for row in prepared.as_dict()['members']:
        assert member_execution_input(plan.as_dict(), row).model_id == row['model_id']


def test_stale_remote_preparation_is_not_silently_rewritten(configured):
    from runtime.model_attachment import model_attachment_from_dict
    _, attachments = qualified_fixture(configured, 'custom')
    payload = attachments[0].as_dict()
    payload['schema_version'] = 'px.remote-model-attachment/1.0'
    with pytest.raises(ValueError, match='fresh qualified preparation'):
        model_attachment_from_dict(payload)
