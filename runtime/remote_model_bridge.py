"""Existing-host remote profile/catalog/dispatch; production admission stays explicit."""
import argparse
import json
from pathlib import Path
import sys

from .json_io import bounded_canonical_json_bytes
from .provider_gateway import load_provider_registry, load_provider_protocols
from .remote_provider_profiles import load_profiles, digest
from .remote_service_protocols import service_protocol


def list_models(engine_root, project_root):
    _, profiles = load_profiles(project_root)
    registry = load_provider_registry(Path(engine_root))
    protocol = load_provider_protocols(Path(engine_root))
    def ready(r):
        adapter = next((a for a in registry['adapters'] if a['adapter_id'] == r['adapter_id']), {})
        capability = next((a for a in protocol['adapters'] if a['adapter_id'] == r['adapter_id']), {})
        return (adapter.get('admitted') is True and adapter.get('status') == 'ready'
                and adapter.get('provider_id') == r['provider_id'] and adapter.get('mode') == 'remote'
                and adapter.get('billing_state') == 'unknown' and capability.get('implemented') is True
                and capability.get('streaming') is True
                and capability.get('surfaces') == [service_protocol(r['adapter_id'], r['provider_id'])['surface']])
    return {'schema_version': 'px.vscode-model-list/1.0', 'authority_granted': False, 'models': [
        {**{k: r[k] for k in ('profile_id', 'provider_id', 'adapter_id', 'model_id', 'context_tokens',
                             'max_output_tokens', 'capabilities', 'locality', 'cost_class')},
         'profile_sha256': digest(r), 'lane': 'remote', 'bridge_kind': 'remote',
         'available': False, 'adapter_ready': ready(r),
         'unavailable_reason': 'remote-host-custody-not-commissioned' if ready(r) else 'remote-adapter-not-admitted',
         'production_host_custody_proved': False} for r in profiles]}


def chat(engine_root, project_root, payload):
    """Consume a signed selection of an immutable prepared owner; never a prompt bypass."""
    from .studio_authority import StudioAuthorityStore
    from .prepared_group_transport import resolve_prepared_group
    from .remote_model_attachment import remote_branch_id, remote_model_attachment_from_dict, build_remote_model_attachment
    from .model_group_preparation import member_attachment, member_execution_input
    from .workflow_studio import WorkflowStudio
    from .studio_models import digest as receipt_digest
    from .json_io import load_json_object, decode_json_value
    from .input_files import contained_file
    from .model_branch_artifacts import read_branch_artifact
    fields = {'prepared_group_reference', 'profile_id', 'profile_sha256', 'provider_id'}
    if type(payload) is not dict or set(payload) not in (fields, fields | {'approval_capability'}):
        raise ValueError('closed remote prepared-group request required')
    bounded_canonical_json_bytes(payload, max_bytes=256 * 1024)
    selected = {k: payload[k] for k in fields}
    reference = selected['prepared_group_reference']
    _, profiles = load_profiles(project_root)
    rows = [r for r in profiles if r['profile_id'] == selected['profile_id']]
    if (len(rows) != 1 or digest(rows[0]) != selected['profile_sha256']
            or rows[0]['provider_id'] != selected['provider_id']):
        raise PermissionError('current remote profile/service binding differs')
    proof = payload.get('approval_capability')
    if type(proof) is not dict:
        raise PermissionError('payload-bound signed remote approval required')
    root = Path(project_root).resolve(strict=True)
    authority = StudioAuthorityStore.open_existing(root)
    branch = remote_branch_id(selected['provider_id'], selected['profile_id'])
    plan = resolve_prepared_group(root, reference)
    attachment_value, prepared = member_attachment(plan.as_dict(), branch)
    attachment = remote_model_attachment_from_dict(attachment_value)
    def current():
        if (attachment.profile_sha256 != selected['profile_sha256']
                or attachment.provider_model_id != rows[0]['model_id']
                or attachment != build_remote_model_attachment(root, profile_id=selected['profile_id'],
                                                               requester_id=attachment.requester_id)):
            raise PermissionError('prepared remote member is not the current selected profile')
        if resolve_prepared_group(root, reference).plan_sha256 != plan.plan_sha256:
            raise PermissionError('prepared remote plan changed')
    current()
    studio = WorkflowStudio(root)
    owner = studio.resolve_prepared_group_owner(reference)
    signed = studio.execute_prepared_group_node(reference, approval_capability=proof,
                                               selection=selected, assert_current=current)
    workflow = authority.verify_receipt(signed)
    state = studio.run_control.read_snapshot(workflow['run_id'])
    results = state['checkpoint']['results']
    output = results[owner['node_id']]
    if (workflow.get('status') != 'succeeded' or state.get('state') != 'succeeded'
            or workflow.get('workflow_id') != owner['workflow_id'] or workflow.get('version') != owner['version']
            or state.get('subject_id') != owner['workflow_id'] or state.get('version') != owner['version']
            or workflow.get('output_sha256') != receipt_digest(results)
            or output.get('control_state') != 'succeeded'):
        raise PermissionError('remote prepared workflow did not commit successfully')
    group_sha = output['group_run_sha256']
    if type(group_sha) is not str or len(group_sha) != 64 or any(c not in '0123456789abcdef' for c in group_sha):
        raise ValueError('canonical remote group receipt digest required')
    from .agent_runtime import AgentRuntimeController
    group = AgentRuntimeController(root).read_governed_group_run(group_sha)
    node = next(r for r in state['checkpoint']['node_receipts'] if r['node_id'] == owner['node_id'])
    attempt = node['attempts'][-1]
    bindings = group.get('workflow_effect_bindings', [])
    if not bindings:
        raise PermissionError('remote group has no native workflow effect bindings')
    committed = attempt['committed_effect_intents']
    if (group.get('group_run_sha256') != group_sha
            or receipt_digest({k:v for k,v in group.items() if k != 'group_run_sha256'}) != group_sha
            or group.get('control_state') != 'succeeded' or group.get('member_failures')
            or group.get('task_plan_sha256') != plan.plan_sha256
            or group.get('group_sha256') != plan.model_execution_group.group_sha256
            or group.get('workflow_execution_context') != attempt['execution_context']
            or [{k:v for k,v in row.items() if k != 'result_sha256'} for row in committed] != bindings):
        raise PermissionError('remote group receipt is not the committed workflow member result')
    from .effect_intent import EffectIntentLedger
    ledger = EffectIntentLedger(root)
    remote = {row['idempotency_key']:row['result_sha256'] for row in group.get('workflow_remote_effect_outcomes', [])}
    for row in committed:
        expected = group_sha if (row['effect'], row['scopes']) == ('execute', ['runtime']) else remote.get(row['idempotency_key'])
        observed = ledger.fence(row['idempotency_key'])
        if (expected is None or observed['disposition'] != 'committed' or row['result_sha256'] != expected
                or any(observed.get(k) != row[k] for k in ('execution_id','effect','scopes','result_sha256'))):
            raise PermissionError('remote native effect settlement changed')
    current()
    member = group['member_receipts'][branch]
    invocation = member_execution_input(plan.as_dict(), prepared)
    raw = read_branch_artifact(root, member['outcome']['branch_artifact'], invocation, run_id=member['run_id'])
    current()
    return {'schema_version':'px.remote-prepared-result/1.0', 'profile_id':selected['profile_id'],
            'provider_id':selected['provider_id'], 'model_id':branch, 'provider_model_id':attachment.provider_model_id,
            'value':decode_json_value(raw, max_bytes=524288), 'group_run_sha256':group_sha,
            'workflow_receipt':signed, 'branch_artifact':member['outcome']['branch_artifact'], 'authority_granted':False}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('list', 'chat'))
    parser.add_argument('--engine-root', required=True, type=Path)
    parser.add_argument('--project-root', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.operation == 'list':
            result = list_models(args.engine_root, args.project_root)
        else:
            raw = sys.stdin.buffer.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError('remote request exceeds bound')
            result = chat(args.engine_root, args.project_root, json.loads(raw))
        print(bounded_canonical_json_bytes(result, max_bytes=4 * 1024 * 1024).decode())
    except (OSError, ValueError, PermissionError, KeyError, TypeError) as error:
        print(json.dumps({'schema_version': 'px.remote-model-client-failure/1.0',
                          'failure_type': type(error).__name__, 'reason': 'remote request rejected'}))
        return 1
    return 0



if __name__ == '__main__':
    raise SystemExit(main())
