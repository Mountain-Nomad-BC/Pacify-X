"""Causal native protocol/gateway regressions for PX-AUD-090 through 094."""
import json
import pytest
from runtime.model_protocol_translate import iter_sse_frames, WireStreamTranslator
from runtime.model_protocol import CanonicalModelEvent, CanonicalStreamState
from runtime.provider_gateway import ProviderInvocationError
from tests.test_provider_gateway_streaming import _project, _gateway, _request, FakeStreamAdapter


def translator(surface):
    return WireStreamTranslator(surface=surface,request_id='r',adapter_id='a',model_id='m')


def test_sse_utf8_codepoints_survive_every_byte_boundary():
    raw='data: caf\u00e9 \U0001f680\n\n'.encode()
    for cut in range(1,len(raw)):
        assert list(iter_sse_frames([raw[:cut],raw[cut:]]))==[(None,'caf\u00e9 \U0001f680')]


@pytest.mark.parametrize('newline',['\n','\r','\r\n'])
def test_sse_line_endings_and_chunk_boundaries_are_equivalent(newline):
    raw=(newline.join([': comment','event: update','id: ignored','data: one','data: two','','data: next','',''])).encode()
    expected=[('update','one\ntwo'),(None,'next')]
    for cut in range(len(raw)+1):
        assert list(iter_sse_frames([raw[:cut],raw[cut:]]))==expected


@pytest.mark.parametrize('raw',[b'data: \xff\n\n',b'data: \xe2\x82'])
def test_invalid_or_truncated_utf8_never_becomes_replacement_text(raw):
    with pytest.raises(ValueError,match='UTF-8'):list(iter_sse_frames([raw]))


def test_chat_whitespace_is_retained_in_normalized_output_and_hash():
    owner=translator('openai_chat');state=CanonicalStreamState('r','a','m')
    for value in ['hello',' ','world','\n']:
        for event in owner.feed_sse(None,json.dumps({'choices':[{'delta':{'content':value}}]})):state.accept(event)
    for event in owner.feed_sse(None,json.dumps({'choices':[],'usage':{'prompt_tokens':2,'completion_tokens':2}})):state.accept(event)
    for event in owner.feed_sse(None,'[DONE]'):state.accept(event)
    assert state.normalized_output()['text']=='hello world\n'


@pytest.mark.parametrize('status',['failed','cancelled','incomplete','in_progress','unknown'])
def test_failed_responses_never_emit_success_finish(status):
    events=translator('openai_responses').feed_sse('response.completed',json.dumps({'type':'response.completed','response':{'status':status,'usage':{'input_tokens':3,'output_tokens':1}}}))
    assert events[-1].kind=='error'
    assert not any(event.kind=='finish' for event in events)
    assert next(event.payload for event in events if event.kind=='usage')['input_tokens']==3


@pytest.mark.parametrize('reason,expected',[('max_tokens','length'),('tool_use','tool_calls'),('end_turn','stop'),('stop_sequence','stop')])
def test_anthropic_finish_reason_survives_terminal_usage(reason,expected):
    owner=translator('anthropic_messages')
    owner.feed_sse('message_start',json.dumps({'type':'message_start','message':{'usage':{'input_tokens':3}}}))
    owner.feed_sse('message_delta',json.dumps({'type':'message_delta','delta':{'stop_reason':reason},'usage':{'output_tokens':1}}))
    events=owner.feed_sse('message_stop',json.dumps({'type':'message_stop'}))
    assert events[-1].payload['reason']==expected
    assert events[-2].payload['input_tokens']==3


@pytest.mark.parametrize('status',['failed','cancelled','incomplete'])
def test_real_gateway_records_failure_not_completed_and_conservatively_settles(tmp_path,status):
    root=_project(str(tmp_path));path=root/'models/provider-protocols.json'
    policy=json.loads(path.read_text());policy['adapters'][0]['surfaces']=['openai_responses'];path.write_text(json.dumps(policy))
    state=tmp_path/'state';state.mkdir();gateway=_gateway(root,state)
    class Adapter(FakeStreamAdapter):
        protocol_surface='openai_responses'
        def stream(self,model,request,control):
            owner=WireStreamTranslator(surface=self.protocol_surface,request_id=request.request_id,adapter_id=self.adapter_id,model_id=model)
            yield from owner.feed_sse('response.completed',json.dumps({'type':'response.completed','response':{'id':'upstream','status':status,'usage':{'input_tokens':3,'output_tokens':1}}}))
    seen=[]
    with pytest.raises(ProviderInvocationError):gateway.stream(_request(),Adapter(),seen.append)
    assert not any(event.kind=='finish' for event in seen)
    replay=gateway.event_bus.replay()
    assert [row['event']['operation']['lifecycle'] for row in replay['events']]==['started','failed']
    receipt=json.loads((state/'budget/receipts/inv-1.settled.json').read_text())
    assert receipt['outcome']=='failure'
    assert receipt['settlement_basis']=='reservation_burn'


def test_canonical_finish_cannot_launder_explicit_failure_into_success():
    with pytest.raises(ValueError,match='unsuccessful'):
        CanonicalModelEvent('r','a','m',0,'finish',{'reason':'failed'})
