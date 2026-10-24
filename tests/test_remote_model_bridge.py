"""Actual native gateway consumer and disposable signed host permissions only."""
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path

import pytest

from runtime.execution_context import ExecutionContext
from runtime.remote_model_bridge import chat, list_models
from runtime.remote_provider_profiles import CONFIG, ROOT, digest, https_origin
from runtime.studio_authority import StudioAuthorityStore
from runtime.studio_models import EffectGrant
from runtime.provider_gateway import build_provider_execution_policy
from tests.studio_approval_testkit import approval_proof
from tests.test_provider_gateway_streaming import _project


class RecordingTransport:
    def __init__(self):
        self.calls = []
        self.closed = 0
    def open(self, **request):
        self.calls.append({k: v for k, v in request.items() if k != 'credential'})
        assert request['credential'] == 'fixture-credential-never-log'
        response = io.BytesIO(b'data: {"id":"fixture-upstream","choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\n'
            b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
            b'data: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}\n\n'
            b'data: [DONE]\n\n')
        return self, response
    def close(self):
        self.closed += 1


@pytest.fixture
def configured(tmp_path, monkeypatch):
    monkeypatch.setenv('PX_STUDIO_KEY_ROOT', str(tmp_path / 'host-keys'))
    engine = _project(str(tmp_path))
    registry = json.loads((engine / 'registry/provider_adapters.json').read_text())
    registry['adapters'][0].update(adapter_id='custom-openai-chat', provider_id='custom', mode='remote', billing_state='unknown')
    (engine / 'registry/provider_adapters.json').write_text(json.dumps(registry))
    protocols = json.loads((engine / 'models/provider-protocols.json').read_text())
    protocols['adapters'][0].update(adapter_id='custom-openai-chat', tools=False, structured_output=False, exact_token_count=False)
    (engine / 'models/provider-protocols.json').write_text(json.dumps(protocols))
    budget = json.loads((engine / 'registry/provider_budget_policy.json').read_text())
    budget['budgets'][0].update(actor_id='pacify-x-vscode', provider_id='custom', max_input_tokens=8192, max_output_tokens=1024)
    (engine / 'registry/provider_budget_policy.json').write_text(json.dumps(budget))
    root = tmp_path / 'project'
    root.mkdir()
    authority = StudioAuthorityStore(root)
    actor = 'human:vscode-local-user'
    authority.admit_grant(EffectGrant('remote-grant', actor, ('read', 'write', 'network'),
        (ROOT, '.agentic_engineering_os_px/studios/authority', 'https://provider.example'),
        'fixture-owner', ('fixture-explicit-permission',), '2099-01-01T00:00:00Z', 'admitted'))
    profile = {'profile_id': 'custom-fixture', 'provider_id': 'custom', 'adapter_id': 'custom-openai-chat',
        'model_id': 'provider-declared-model', 'model_revision': 'provider-declared-fixture-revision',
        'origin': 'https://provider.example', 'approved_addresses': ['8.8.8.8'],
        'credential_reference': 'PX_CUSTOM_FIXTURE_CREDENTIAL', 'context_tokens': 8192, 'max_output_tokens': 1024,
        'capabilities': {'coding': 0.5, 'planning': 0.5, 'review': 0.5, 'classification': 0.5,
                         'toolUse': False, 'vision': False, 'structuredOutput': False},
        'locality': 'remote', 'cost_class': 'billable-api', 'grant_id': 'remote-grant',
        'policy_locator': ROOT + '/policy.json', 'budget_id': 'budget-1',
        'authorized_requesters': [actor], 'revision_evidence': ['fixture-owner-model-declaration']}
    config = {'schema_version': 'px.remote-provider-profiles/1.0', 'state': 'approved', 'approved_by': 'fixture-owner',
        'evidence_refs': ['fixture-explicit-approval'], 'expires_utc': '2099-01-01T00:00:00Z', 'profiles': [profile]}
    path = root / CONFIG
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(authority.sign_receipt(config)))
    constraints = digest({'fixture': 'actual-owner-constraints'})
    _, grant_revision = authority.resolve_grant('remote-grant', subject_id=actor, required_effects=('read', 'write', 'network'))
    policy = build_provider_execution_policy(task_plan_sha256=constraints,
        model={'provider_id': 'custom', 'adapter_id': 'custom-openai-chat', 'model_id': profile['model_id'],
               'model_revision': profile['model_revision'], 'attachment_sha256': digest(profile),
               'privacy': 'policy_gated', 'authority_class': 'installed_host'},
        authority={'revision': grant_revision, 'provider_effect': True},
        egress={'mode': 'allowlist', 'allowed_destinations': [profile['origin']]},
        cost={'budget_id': 'budget-1', 'max_charge_microunits': 100}, fallbacks=[], exact_receipt_required=True)
    (root / profile['policy_locator']).write_text(json.dumps(authority.sign_receipt(policy)))
    context = ExecutionContext('fixture-run', None, 'fixture-run', 'fixture-project', 'fixture-session', 1, 1,
        None, constraints, digest({'fixture': 'budget'}), 'fixture-run',
        (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(), 'pacify-x-vscode', 'custom', 'fixture-run')
    state_path = root / '.agentic_engineering_os_px/runtime-core/agent-console/task-state.json'
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({'schemaVersion': 'px.agent-task-store/2.0', 'epoch': 1,
        'runs': [{'runId': 'fixture-run', 'epoch': 1, 'revision': 1, 'status': 'running'}]}))
    payload = {'profile_id': profile['profile_id'], 'request_id': 'fixture-run', 'client_session_id': 'fixture-session',
        'correlation_id': 'fixture-correlation', 'project_id': 'fixture-project', 'messages': [{'role': 'user', 'content': 'fixture'}],
        'max_output_tokens': 1024, 'deadline_ms': 30000, 'execution_context': context.as_dict(),
        'requester_id': actor, 'profile_sha256': digest(profile)}
    return engine, root, authority, profile, payload


def approved(root, payload):
    return {**payload, 'approval_capability': approval_proof(root, 'remote-model', 'chat', payload)}


def test_native_catalog_truthfully_refuses_unowned_remote_dispatch(configured):
    engine, root, authority, profile, payload = configured
    listed = list_models(engine, root)['models'][0]
    assert listed['provider_id'] == 'custom' and listed['locality'] == 'remote'
    assert listed['cost_class'] == 'billable-api' and 'model_sha256' not in listed
    assert listed['available'] is False and listed['adapter_ready'] is True
    request = {'prepared_group_reference': {'schema_version': 'px.prepared-group-reference/1.0',
        'plan_id': 'fixture-plan', 'plan_sha256': digest({'fixture': 'reference'})},
        'profile_id': profile['profile_id'], 'profile_sha256': digest(profile), 'provider_id': 'custom'}
    before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
    with pytest.raises(PermissionError, match='payload-bound signed remote approval required'):
        chat(engine, root, request)
    assert sorted(str(p.relative_to(root)) for p in root.rglob('*')) == before
    with pytest.raises(ValueError, match='closed remote prepared-group'):
        chat(engine, root, approved(root, payload))


def test_concrete_custom_protocol_uses_pins_and_exact_terminal_usage(configured):
    from runtime.remote_provider_adapters import CustomOpenAIChatAdapter
    from runtime.model_protocol import CanonicalModelRequest
    from runtime.provider_gateway import ProviderStreamControl
    engine, root, authority, profile, payload = configured
    transport = RecordingTransport()
    checks=[]
    adapter = CustomOpenAIChatAdapter(profile, credential_resolver=lambda reference: 'fixture-credential-never-log',
        validate_current=lambda: checks.append('current'), transport=transport)
    canonical = CanonicalModelRequest(request_id='fixture-protocol', session_id='fixture-session',
        client_id='fixture', operation_id='fixture-custom-chat', privacy='policy_gated', route='custom-openai-chat',
        messages=({'role':'user','content':'fixture'},), tools=(), max_output_tokens=1024, deadline_ms=30000)
    events = list(adapter.stream(profile['model_id'], canonical, ProviderStreamControl(30000)))
    assert [e.payload['text'] for e in events if e.kind == 'text_delta'] == ['hello']
    usage = adapter.provider_usage(next(e.payload for e in events if e.kind == 'usage'))
    assert usage.input_tokens == 3 and usage.output_tokens == 1
    assert usage.billing_state == 'unknown' and usage.charge_microunits is None
    assert transport.closed == 1 and len(checks) >= 3
    assert transport.calls[0]['origin'] == profile['origin'] and transport.calls[0]['addresses'] == ['8.8.8.8']
    assert json.loads(transport.calls[0]['body'])['model'] == profile['model_id']


def test_concrete_protocol_refuses_before_credentials_when_owner_currentness_fails(configured):
    from runtime.remote_provider_adapters import CustomOpenAIChatAdapter
    from runtime.model_protocol import CanonicalModelRequest
    from runtime.provider_gateway import ProviderStreamControl
    _, _, _, profile, _ = configured
    def deny(): raise PermissionError('fixture actual owner currentness denied')
    def secret(_): pytest.fail('credential resolved before current authority')
    adapter=CustomOpenAIChatAdapter(profile,credential_resolver=secret,validate_current=deny,transport=RecordingTransport())
    request=CanonicalModelRequest(request_id='fixture-deny',session_id='fixture',client_id='fixture',
        operation_id='fixture',privacy='policy_gated',route='custom-openai-chat',messages=({'role':'user','content':'fixture'},),
        tools=(),max_output_tokens=1,deadline_ms=30000)
    with pytest.raises(PermissionError,match='currentness denied'):
        list(adapter.stream(profile['model_id'],request,ProviderStreamControl(30000)))


def test_normal_native_catalog_contains_unavailable_remote_with_local_intact(configured, monkeypatch):
    from runtime import vscode_model_bridge
    engine, root, authority, profile, _ = configured
    local = {'profile_id': 'genuine-local-fixture', 'provider_id': 'llama.cpp'}
    monkeypatch.setattr(vscode_model_bridge, '_available', lambda *_: [local])
    response = vscode_model_bridge.list_models(engine, root)
    assert response['models'][0] == local
    assert response['models'][1]['provider_id'] == 'custom'
    assert response['models'][1]['available'] is False
    (root / CONFIG).write_text('{"invalid":"fixture-private-metadata"}')
    response = vscode_model_bridge.list_models(engine, root)
    assert response['models'] == [local]
    assert response['remote_catalog_status'] == 'configuration_invalid'
    assert 'fixture-private-metadata' not in json.dumps(response)


def test_actual_transport_connects_pin_tls_original_hostname_without_dns(configured, monkeypatch):
    from runtime import remote_provider_adapters as module
    _, _, _, profile, _ = configured
    calls = []
    class Socket:
        def close(self): calls.append(('socket-close',))
    class Context:
        def wrap_socket(self, raw, *, server_hostname):
            calls.append(('tls-host', server_hostname))
            return raw
    class Response:
        status = 302
        headers = {}
    class Connection:
        def __init__(self, hostname, **options):
            calls.append(('http-host', hostname))
            self._context = options['context']
        def request(self, method, route, **kwargs):
            calls.append(('request', method, route))
        def getresponse(self): return Response()
        def close(self): calls.append(('connection-close',))
    monkeypatch.setattr(module.ssl, 'create_default_context', lambda: Context())
    monkeypatch.setattr(module.http.client, 'HTTPSConnection', Connection)
    monkeypatch.setattr(module.socket, 'create_connection', lambda address, **kwargs: calls.append(('pin', address)) or Socket())
    from urllib.error import HTTPError
    with pytest.raises(HTTPError) as error:
        module.PinnedHttpsTransport().open(origin=profile['origin'], addresses=profile['approved_addresses'],
                                           body=b'fixture', credential='fixture-secret', timeout=5)
    assert error.value.code == 302
    assert ('pin', ('8.8.8.8', 443)) in calls
    assert ('tls-host', 'provider.example') in calls
    assert ('connection-close',) in calls and ('socket-close',) in calls
    assert 'fixture-secret' not in str(error.value)
    assert calls.count(('request', 'POST', '/v1/chat/completions')) == 1


@pytest.mark.parametrize('origin,addresses', [('http://provider.example', ['8.8.8.8']),
    ('https://provider.example/path', ['8.8.8.8']), ('https://provider.example', ['127.0.0.1']),
    ('https://provider.example', ['169.254.169.254']), ('https://u@provider.example', ['8.8.8.8'])])
def test_endpoint_ssrf_shapes_refused(origin, addresses):
    with pytest.raises(ValueError): https_origin(origin, addresses)
