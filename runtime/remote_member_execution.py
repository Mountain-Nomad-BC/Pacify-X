"""Native remote member effects under the canonical signed workflow owner."""
from pathlib import Path
import json
import os
from datetime import datetime, timezone

from .remote_provider_profiles import ROOT, digest
from .remote_model_attachment import RemoteModelAttachment
from .effect_intent import EffectIntentLedger
from .execution_context import ExecutionContext, execution_context_from_dict
from .provider_gateway import ProviderInvocationGateway, ProviderRequest, execute_provider_request
from .model_protocol import CanonicalModelRequest


def _claims(attachment):
    return {('network', attachment.origin if type(attachment) is RemoteModelAttachment else 'loopback'), ('write', ROOT + '/gateway/events'),
            ('write', ROOT + '/gateway/budget')}


def _authority(root, signed_task, task_plan, spec, placements, remote_outcomes=None):
    from .workflow_worker import _verify_group_workflow_effect_receipt
    return _verify_group_workflow_effect_receipt(root, signed_task, task_plan=task_plan,
                                                spec=spec, placements=placements, remote_outcomes=remote_outcomes)


def _key(attachment, context, effect, scope, workflow_sha):
    return 'remote-provider-child:' + digest({'execution_id': context.execution_id,
        'attachment_sha256': attachment.attachment_sha256, 'effect': effect, 'scope': scope,
        'workflow_effect_sha256': workflow_sha})


def _gateway_paths(root, gateway):
    if type(gateway) is not ProviderInvocationGateway:
        raise PermissionError('remote member requires actual native provider gateway')
    if gateway.event_bus.root != root / ROOT / 'gateway/events' or gateway.budget_ledger.root != root / ROOT / 'gateway/budget':
        raise PermissionError('remote gateway escaped prepared owned state scopes')


def _observe(gateway, receipt, attachment, context, identity=None):
    """Correlate actual independently durable native event and budget images."""
    from .provider_gateway import _digest, MAX_RESPONSE_BYTES
    if receipt.get('outcome_sha256') != _digest({k: v for k, v in receipt.items() if k != 'outcome_sha256'}, limit=MAX_RESPONSE_BYTES):
        raise PermissionError('remote provider outcome integrity differs')
    identity = identity or {'wire_model_id':attachment.provider_model_id,'provider_id':attachment.provider_id,
        'adapter_id':attachment.adapter_id,'budget_id':attachment.budget_id,'authority_revision':attachment.grant_revision}
    provider = receipt['provider_receipt']
    if (receipt['model_attachment_sha256'] != attachment.attachment_sha256 or
            receipt['task_plan_sha256'] != context.authority_reference_sha256 or receipt.get('exact_receipt') is not True or
            receipt['model_revision'] != attachment.model_revision or receipt['authority_revision'] != identity['authority_revision'] or
            provider['invocation_id'] != context.execution_id or provider['model_id'] != identity['wire_model_id'] or
            provider['provider_id'] != identity['provider_id'] or provider['adapter_id'] != identity['adapter_id']):
        raise PermissionError('remote actual provider receipt identity differs')
    budget = gateway.budget_ledger._receipt(context.execution_id, 'settled')
    if (budget['receipt_sha256'] != provider['budget_receipt_sha256'] or budget.get('outcome') != 'success' or
            budget.get('budget_id') != identity['budget_id'] or budget.get('provider_id') != identity['provider_id'] or
            budget.get('adapter_id') != identity['adapter_id'] or budget.get('correlation_id') != provider['correlation_id']):
        raise PermissionError('remote provider budget settlement not observed')
    page = gateway.event_bus.replay(after_revision=provider['completed_revision'] - 1, limit=1)
    if page.get('errors') or len(page['events']) != 1:
        raise PermissionError('remote completed provider event not observed')
    envelope = page['events'][0]
    event = envelope.get('event', envelope)
    if (event.get('event_id') != context.execution_id + '-completed' or
            event.get('operation', {}).get('result') != 'success' or
            event.get('operation', {}).get('lifecycle') != 'completed' or
            event.get('work', {}).get('project_id') != context.project_id or
            event.get('work', {}).get('task_id') != context.root_execution_id or
            event.get('actor', {}).get('session_id') != context.session_id or
            event.get('correlation_id') != provider['correlation_id'] or
            event.get('integrity', {}).get('input_sha256') != provider['input_sha256'] or
            event.get('integrity', {}).get('output_sha256') != provider['output_sha256']):
        raise PermissionError('remote completed event correlation differs')
    return receipt['outcome_sha256']


def _execute_custodied_member(*, root, gateway, binding, invocation, context, cancel_requested,
        signed_task, task_plan, spec, placements, invoke, identity=None):
    attachment = invocation.attachment
    _gateway_paths(root, gateway)
    def live():
        if cancel_requested and cancel_requested():
            raise PermissionError('remote member cancelled')
        if datetime.fromisoformat(context.deadline_utc.replace('Z', '+00:00')) <= datetime.now(timezone.utc):
            raise PermissionError('remote member deadline expired')
        _, bindings = _authority(root, signed_task, task_plan, spec, placements)
        if not _claims(attachment) <= {(row['effect'], row['scopes'][0]) for row in bindings}:
            raise PermissionError('remote workflow lacks exact network/event/budget pre-intents')
        binding.assert_current()
        return bindings

    task, _ = _authority(root, signed_task, task_plan, spec, placements)
    workflow_sha = digest(task)
    live()
    ledger = EffectIntentLedger(root)
    children = []
    for effect, scope in sorted(_claims(attachment)):
        live()
        key = _key(attachment, context, effect, scope, workflow_sha)
        ledger.intend(idempotency_key=key, execution_id=context.execution_id, effect=effect, scopes=(scope,))
        children.append({'idempotency_key': key, 'execution_id': context.execution_id, 'effect': effect, 'scopes': [scope]})
    def cancelled():
        try:
            live()
            return False
        except Exception:
            return True

    live()
    value, receipt = invoke(cancelled)
    live()
    result_sha = _observe(gateway, receipt, attachment, context, identity)
    for child in children:
        live()
        ledger.commit(idempotency_key=child['idempotency_key'], execution_id=context.execution_id, result_sha256=result_sha)
        child['result_sha256'] = result_sha
    return {'schema_version': 'px.remote-member-provider-outcome/1.0' if identity is None else 'px.local-member-provider-outcome/1.0', 'value': value,
        'provider_receipt': receipt, 'model_id': attachment.model_id, 'attachment_sha256': attachment.attachment_sha256,
        'task_plan_sha256': invocation.task_plan_sha256, 'context_sha256': invocation.context_sha256,
        'execution_context': context.as_dict(), 'child_effect_outcomes': children, 'workflow_effect_sha256': workflow_sha, **({'binding_identity':identity} if identity is not None else {})}


def execute_remote_member(*, root, gateway, binding, selected_policy, invocation, context,
        actor_id, accountable_owner, output_limit, cancel_requested, signed_task, task_plan, spec, placements):
    root = Path(root).resolve(strict=True)
    attachment = invocation.attachment
    if type(attachment) is not RemoteModelAttachment or binding.attachment != attachment or selected_policy != binding.policy:
        raise PermissionError('remote member differs from native signed prepared provider binding')
    if (type(context) is not ExecutionContext or context.provider_id != attachment.provider_id or
            context.authority_reference_sha256 != invocation.task_plan_sha256 or
            context.project_id != invocation.context['project_id'] or invocation.task_plan_sha256 != task_plan['plan_sha256']):
        raise PermissionError('remote member requires exact prepared execution context')
    _gateway_paths(root, gateway)

    task, _ = _authority(root, signed_task, task_plan, spec, placements)
    workflow_sha = digest(task)
    canonical = CanonicalModelRequest(request_id=context.execution_id, session_id=context.session_id,
        client_id=actor_id, operation_id=context.execution_id, privacy='policy_gated', route=attachment.adapter_id,
        messages=({'role': 'user', 'content': json.dumps(invocation.context, sort_keys=True, separators=(',', ':'), ensure_ascii=False)},),
        tools=(), max_output_tokens=attachment.max_output_tokens,
        deadline_ms=min(300000, int((datetime.fromisoformat(context.deadline_utc.replace('Z', '+00:00')) - datetime.now(timezone.utc)).total_seconds() * 1000)),
        metadata={'execution_context': context.as_dict(), 'prepared_context_sha256': invocation.context_sha256,
                  'task_plan_sha256': invocation.task_plan_sha256, 'model_attachment_sha256': attachment.attachment_sha256,
                  'profile_sha256': attachment.profile_sha256, 'prepared_model_id': attachment.model_id,
                  'provider_model_id': attachment.provider_model_id, 'workflow_effect_sha256': workflow_sha})
    budget_policy = gateway.budget_ledger._policy(attachment.budget_id, actor_id, attachment.provider_id)
    if budget_policy['unknown_billing'] == 'deny':
        raise PermissionError('remote unknown billing lacks explicit conservative policy')
    request = ProviderRequest(invocation_id=context.execution_id, correlation_id=context.trace_root_id,
        project_id=context.project_id, adapter_id=attachment.adapter_id, model_id=attachment.provider_model_id,
        actor_id=actor_id, accountable_owner=accountable_owner, payload=canonical.as_dict(),
        task_id=context.root_execution_id, session_id=context.session_id, budget_id=attachment.budget_id,
        max_input_tokens=attachment.context_tokens, max_output_tokens=attachment.max_output_tokens,
        authority_revision=attachment.grant_revision, task_plan_sha256=invocation.task_plan_sha256,
        model_attachment_sha256=attachment.attachment_sha256, model_revision=attachment.model_revision,
        requested_egress=attachment.origin, expected_charge_microunits=budget_policy['unknown_charge_microunits'])

    return _execute_custodied_member(root=root,gateway=gateway,binding=binding,invocation=invocation,context=context,
        cancel_requested=cancel_requested,signed_task=signed_task,task_plan=task_plan,spec=spec,placements=placements,
        invoke=lambda cancelled:execute_provider_request(gateway, selected_policy, request, binding.adapter,
            streaming=True,cancel_requested=cancelled,max_output_bytes=output_limit))


def _local_identity(binding, policy, invocation):
    from .group_provider_adapters import GroupProviderBinding
    from .model_attachment import ModelAttachment
    if (type(binding) is not GroupProviderBinding or type(invocation.attachment) is not ModelAttachment
            or binding.model_id != invocation.model_id or binding.artifact_sha256 != invocation.attachment.artifact_sha256):
        raise PermissionError('local receipt requires its current native artifact binding')
    binding.assert_current()
    model = policy['model']
    if (policy['task_plan_sha256'] != invocation.task_plan_sha256 or model['model_revision'] != invocation.attachment.model_revision
            or model['privacy'] != invocation.attachment.privacy or model['authority_class'] != invocation.attachment.authority_class
            or model['provider_id'] != 'llama.cpp' or model['adapter_id'] != binding.adapter_id
            or model['model_id'] != binding.artifact_sha256 or model['attachment_sha256'] != invocation.attachment.attachment_sha256):
        raise PermissionError('local signed policy differs from actual prepared artifact')
    return {'wire_model_id':binding.artifact_sha256,'provider_id':model['provider_id'],
        'adapter_id':binding.adapter_id,'budget_id':binding.budget_id,'authority_revision':policy['authority']['revision'],
        'profile_sha256':binding.profile.profile_sha256,'policy_sha256':digest(policy)}


def _current_local_identity(root, invocation):
    from .workflow_worker import _group_adapter_resolver, _group_policy
    resolver, policy = _group_adapter_resolver(Path(root)), _group_policy(Path(root))
    if resolver is None or policy is None:
        raise PermissionError('current configured local provider authority is unavailable')
    selected = policy(invocation.model_id) if callable(policy) else policy
    return _local_identity(resolver(invocation.model_id), selected, invocation)


def execute_local_custodied_member(*, binding, policy, invoke, **owner):
    identity = _local_identity(binding,policy,owner['invocation'])
    if identity != _current_local_identity(owner['root'],owner['invocation']):
        raise PermissionError('local provider identity is not the current host binding')
    return _execute_custodied_member(binding=binding,invoke=invoke,identity=identity,**owner)


def verify_remote_member_outcome(root, task_plan, invocation, execution_context, envelope):
    """Verify real immediate output and retain metadata without a second text copy."""
    from .model_protocol import canonical_sha256, MAX_STREAM_OUTPUT_BYTES, MAX_TOOL_ARGUMENT_BYTES
    from .operational_event_bus import OperationalEventBus
    from .provider_budget import ProviderBudgetLedger
    attachment = invocation.attachment
    fields = {'schema_version', 'value', 'provider_receipt', 'model_id', 'attachment_sha256',
              'task_plan_sha256', 'context_sha256', 'execution_context', 'child_effect_outcomes', 'workflow_effect_sha256'}
    local = type(attachment) is not RemoteModelAttachment
    identity = _current_local_identity(root,invocation) if local else None
    if local: fields.add('binding_identity')
    expected_schema = 'px.local-member-provider-outcome/1.0' if local else 'px.remote-member-provider-outcome/1.0'
    if type(envelope) is not dict or set(envelope) != fields or envelope.get('schema_version') != expected_schema or (local and envelope['binding_identity'] != identity):
        raise PermissionError('native remote member outcome required')
    if (envelope['execution_context'] != execution_context.as_dict() or envelope['model_id'] != invocation.model_id or
            envelope['task_plan_sha256'] != task_plan['plan_sha256'] or envelope['context_sha256'] != invocation.context_sha256 or
            envelope['attachment_sha256'] != attachment.attachment_sha256):
        raise PermissionError('remote immediate outcome differs from prepared invocation')
    provider = envelope['provider_receipt']['provider_receipt']
    if type(envelope['value']) is not str or provider['output_sha256'] != canonical_sha256({'text': envelope['value'], 'reasoning': '', 'tool_calls': []}, limit=MAX_STREAM_OUTPUT_BYTES + MAX_TOOL_ARGUMENT_BYTES):
        raise PermissionError('remote immediate text differs from actual normalized provider output')
    root = Path(root).resolve(strict=True)
    engine = Path(os.environ['PX_ENGINE_ROOT']).resolve(strict=True)
    state = root / ROOT / 'gateway'
    gateway = ProviderInvocationGateway(engine, OperationalEventBus(engine, state / 'events', state), ProviderBudgetLedger(engine, state / 'budget', state))
    result = _observe(gateway, envelope['provider_receipt'], attachment, execution_context, identity)
    _verify_children(root, attachment, execution_context, envelope, result)
    return {**{key: value for key, value in envelope.items() if key != 'value'},
            'schema_version': 'px.local-member-provider-evidence/1.0' if local else 'px.remote-member-provider-evidence/1.0', 'output_sha256': provider['output_sha256']}


def _verify_children(root, attachment, context, outcome, result):
    ledger = EffectIntentLedger(root)
    expected = {_key(attachment, context, effect, scope, outcome['workflow_effect_sha256']) for effect, scope in _claims(attachment)}
    if {child['idempotency_key'] for child in outcome['child_effect_outcomes']} != expected or len(outcome['child_effect_outcomes']) != len(expected):
        raise PermissionError('remote native child effect denominator differs')
    for effect, scope in _claims(attachment):
        actual = ledger.fence(_key(attachment, context, effect, scope, outcome['workflow_effect_sha256']))
        if actual['disposition'] != 'committed' or actual['execution_id'] != context.execution_id or actual['effect'] != effect or actual['scopes'] != [scope] or actual['result_sha256'] != result:
            raise PermissionError('remote native child effect is not committed exactly')


def verify_remote_workflow_effect_results(root, task_plan, remote_outcomes, *, signed_task):
    """Observe exact native remote denominator; never trust caller result digests."""
    from .model_group_preparation import member_attachment
    from .model_attachment import model_attachment_from_dict, validate_model_attachment
    from .operational_event_bus import OperationalEventBus
    from .provider_budget import ProviderBudgetLedger
    root = Path(root).resolve(strict=True)
    from .studio_authority import StudioAuthorityStore
    workflow_sha = digest(StudioAuthorityStore.open_existing(root).verify_receipt(signed_task))
    attachments = {}
    for model in task_plan['model_execution_group']['model_ids'] if 'model_ids' in task_plan['model_execution_group'] else [row['model_id'] for row in task_plan['model_execution_group']['branches']]:
        value, member = member_attachment(task_plan, model)
        typed = model_attachment_from_dict(value)
        if not validate_model_attachment(typed, root=root)['valid']:
            raise PermissionError('remote shared settlement profile/grant is no longer current' if type(typed) is RemoteModelAttachment else 'local shared settlement attachment is no longer current')
        attachments[model] = (typed, member)
    if type(remote_outcomes) is not dict or set(remote_outcomes) != set(attachments):
        raise PermissionError('exact remote outcome denominator required before shared settlement')
    engine = Path(os.environ['PX_ENGINE_ROOT']).resolve(strict=True)
    gateway_root = root / ROOT / 'gateway'
    gateway = ProviderInvocationGateway(engine, OperationalEventBus(engine, gateway_root / 'events', gateway_root),
                                        ProviderBudgetLedger(engine, gateway_root / 'budget', gateway_root))
    observed = {}
    for model, (attachment, member) in attachments.items():
        outcome = remote_outcomes[model]
        local = type(attachment) is not RemoteModelAttachment
        from .model_group_preparation import member_execution_input
        identity = _current_local_identity(root,member_execution_input(task_plan,member)) if local else None
        context = execution_context_from_dict(outcome['execution_context'])
        fields = {'schema_version', 'output_sha256', 'provider_receipt', 'model_id', 'attachment_sha256',
                  'task_plan_sha256', 'context_sha256', 'execution_context', 'child_effect_outcomes', 'workflow_effect_sha256'}
        if local: fields.add('binding_identity')
        schema = 'px.local-member-provider-evidence/1.0' if local else 'px.remote-member-provider-evidence/1.0'
        if (type(outcome) is not dict or set(outcome) != fields or outcome['schema_version'] != schema or (local and outcome['binding_identity'] != identity) or outcome['model_id'] != model or
                outcome['task_plan_sha256'] != task_plan['plan_sha256'] or outcome['attachment_sha256'] != attachment.attachment_sha256 or
                outcome['context_sha256'] != member['context_sha256'] or outcome['workflow_effect_sha256'] != workflow_sha):
            raise PermissionError('remote member outcome differs from exact prepared member')
        result = _observe(gateway, outcome['provider_receipt'], attachment, context, identity)
        if outcome['output_sha256'] != outcome['provider_receipt']['provider_receipt']['output_sha256']:
            raise PermissionError('remote minimized output digest differs')
        _verify_children(root, attachment, context, outcome, result)
        observed[model] = result
    result_sha = digest({'task_plan_sha256': task_plan['plan_sha256'], 'remote_members': observed})
    claims = set().union(*(_claims(attachment) for attachment, _ in attachments.values())) if attachments else set()
    return {claim: result_sha for claim in claims}


def settle_remote_workflow_effects(root, task_plan, signed_task, spec, placements, remote_outcomes):
    """Commit shared parents only after all actual native member effects settle."""
    _, bindings = _authority(root, signed_task, task_plan, spec, placements)
    results = verify_remote_workflow_effect_results(root, task_plan, remote_outcomes, signed_task=signed_task)
    ledger = EffectIntentLedger(Path(root))
    completed = []
    for binding in bindings:
        pair = (binding['effect'], binding['scopes'][0])
        if pair not in results:
            continue
        _authority(root, signed_task, task_plan, spec, placements, remote_outcomes=remote_outcomes)
        ledger.commit(idempotency_key=binding['idempotency_key'], execution_id=binding['execution_id'], result_sha256=results[pair])
        completed.append({**binding, 'result_sha256': results[pair]})
    return tuple(completed)
