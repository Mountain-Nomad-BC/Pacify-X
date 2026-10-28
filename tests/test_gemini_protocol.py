import json
import pytest
from tests.test_remote_model_bridge import configured
from runtime.model_protocol_translate import WireStreamTranslator
from runtime.remote_service_protocols import service_protocol, service_endpoint


def translator():
    return WireStreamTranslator(surface='gemini_generate_content', request_id='r', adapter_id='gemini-generate-content', model_id='configured-model')


@pytest.mark.parametrize('reason', ['SAFETY', 'RECITATION', 'OTHER', 'MALFORMED_FUNCTION_CALL'])
def test_blocked_gemini_is_not_success(reason):
    with pytest.raises(ValueError, match='blocked'):
        translator().feed_sse(None, json.dumps({'candidates':[{'finishReason':reason}]}))


@pytest.mark.parametrize('model', ['../escape', 'model?key=secret', 'models/model', 'a%2fb', '', 'x'*257])
def test_resource_path_cannot_escape(model):
    with pytest.raises(ValueError, match='resource component'):
        service_endpoint(service_protocol('gemini-generate-content','gemini'), model)


def test_native_terminal_and_exact_thought_usage():
    owner = translator()
    payload = {'candidates':[{'content':{'parts':[{'text':'reason','thought':True}]}}], 'usageMetadata':{'promptTokenCount':7,'candidatesTokenCount':2,'thoughtsTokenCount':3}}
    assert owner.feed_sse(None,json.dumps(payload))[0].kind == 'reasoning_delta'
    events = owner.feed_sse(None,json.dumps({'candidates':[{'finishReason':'MAX_TOKENS'}]}))
    assert events[0].payload == {'input_tokens':7,'output_tokens':5}
    assert events[-1].payload['reason'] == 'length'
    with pytest.raises(ValueError,match='after terminal'):
        owner.feed_sse(None,'{}')


@pytest.mark.parametrize('payload', ['[DONE]', {'candidates':[{'finishReason':'STOP'}]}, {'candidates':[{},{}]}, {'candidates':[{'content':{'parts':[{'functionCall':{}}]}}]}])
def test_unsupported_or_unmetered_terminal_is_rejected(payload):
    with pytest.raises(ValueError):
        translator().feed_sse(None,payload if isinstance(payload,str) else json.dumps(payload))


def test_gemini_reaches_actual_prepared_group_custody(configured, monkeypatch):
    import io
    from runtime.remote_provider_profiles import CONFIG, ROOT
    from runtime.studio_models import EffectGrant
    import tests.test_remote_group_effect_owner as owner
    from tests.test_remote_member_effect_owner import run
    engine, root, authority, profile, _ = configured
    profile.update(provider_id='gemini', adapter_id='gemini-generate-content', origin='https://generativelanguage.googleapis.com', grant_id='gemini-fixture-grant')
    authority.admit_grant(EffectGrant(profile['grant_id'], 'human:vscode-local-user', ('read','write','network'),
        (ROOT, profile['origin']), 'fixture-owner', ('explicit-disposable-gemini-permission',), '2099-01-01T00:00:00Z','admitted'))
    path = root / CONFIG
    body = authority.verify_receipt(json.loads(path.read_text()))
    body['profiles'] = [profile]
    path.write_text(json.dumps(authority.sign_receipt(body)))
    for relative, section, changes in (
        ('registry/provider_adapters.json','adapters',{'adapter_id':profile['adapter_id'],'provider_id':'gemini'}),
        ('models/provider-protocols.json','adapters',{'adapter_id':profile['adapter_id'],'surfaces':['gemini_generate_content']}),
        ('registry/provider_budget_policy.json','budgets',{'provider_id':'gemini'})):
        target = engine / relative
        payload = json.loads(target.read_text()); payload[section][0].update(changes)
        target.write_text(json.dumps(payload))
    class NativeRecordingTransport:
        def __init__(self): self.calls=[]
        def open(self, **request):
            self.calls.append({k:v for k,v in request.items() if k != 'credential'})
            payload={'responseId':'gemini-fixture-response','candidates':[{'content':{'parts':[{'text':'hello'}]},'finishReason':'STOP'}],
                     'usageMetadata':{'promptTokenCount':3,'candidatesTokenCount':1}}
            return self, io.BytesIO(('data: '+json.dumps(payload)+'\n\n').encode())
        def close(self): pass
    monkeypatch.setattr(owner,'RecordingTransport',NativeRecordingTransport)
    f = owner.remote_group_fixture(configured,monkeypatch)
    result = run(f)
    assert result['control_state'] == 'succeeded', result['member_failures']
    assert len(f['transport'].calls) == 1
    assert 'contents' in json.loads(f['transport'].calls[0]['body'])
    assert all(f['ledger'].fence(row['idempotency_key'])['disposition']=='committed' for row in f['effects'])


def test_authored_protocol_matrix_matches_actual_adapter_denominator():
    from pathlib import Path
    from runtime.paths import framework_root
    from runtime.provider_gateway import load_provider_protocols,load_provider_registry
    root=framework_root()
    matrix=load_provider_protocols(root)
    registry=load_provider_registry(root)
    assert {row['adapter_id'] for row in matrix['adapters']} == {row['adapter_id'] for row in registry['adapters']}
    row=next(row for row in registry['adapters'] if row['adapter_id']=='gemini-generate-content')
    assert row['admitted'] is False and row['status']=='unconfigured'
    for adapter in ('codex-app-server','codegpt-chat','github-copilot-chat','openai-chat-compatible'):
        row=next(row for row in matrix['adapters'] if row['adapter_id']==adapter)
        assert row['implemented'] is False and row['surfaces']==['terminal']
