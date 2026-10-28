import io
import json
import pytest
from runtime.remote_service_protocols import service_protocol
from runtime.remote_provider_adapters import remote_adapter_for
from runtime.model_protocol import CanonicalModelRequest
from runtime.provider_gateway import ProviderStreamControl


@pytest.mark.parametrize("adapter,provider,frames", [
    ("openai-responses", "openai", [{"type":"response.output_text.delta","delta":"hello"}, {"type":"response.completed","response":{"id":"r","usage":{"input_tokens":3,"output_tokens":1}}}]),
    ("gemini-generate-content", "gemini", [{"responseId":"r","candidates":[{"index":0,"content":{"role":"model","parts":[{"text":"hello"}]},"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":3,"candidatesTokenCount":1}}]),
    ("mistral-chat", "mistral", [{"id":"r","choices":[{"delta":{"content":"hello"},"finish_reason":None}]}, {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1}}, "[DONE]"]),
    ("claude-anthropic-messages", "claude", [{"type":"message_start","message":{"id":"r","usage":{"input_tokens":1,"cache_creation_input_tokens":2}}}, {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"hello"}}, {"type":"message_delta","usage":{"output_tokens":1}}, {"type":"message_stop"}]),
])
def test_named_service_recording_wire_and_reported_usage(adapter, provider, frames):
    protocol = service_protocol(adapter, provider)
    class Transport:
        def open(self, **request):
            self.request = request
            stream = "".join("data: " + (f if isinstance(f,str) else json.dumps(f)) + "\n\n" for f in frames)
            return self, io.BytesIO(stream.encode())
        def close(self): self.closed = True
    transport = Transport()
    profile = {"adapter_id":adapter,"provider_id":provider,"origin":protocol["origin"],"approved_addresses":["8.8.8.8"],"credential_reference":"FIXTURE_SECRET","model_id":"configured-model"}
    native = remote_adapter_for(profile, credential_resolver=lambda _:"fixture-secret", validate_current=lambda:None, transport=transport)
    request = CanonicalModelRequest(request_id="r",session_id="s",client_id="c",operation_id="o",privacy="policy_gated",route=adapter,messages=({"role":"system","content":"instruction"},{"role":"user","content":"question"}),tools=(),max_output_tokens=8,deadline_ms=30000)
    events = list(native.stream(profile["model_id"],request,ProviderStreamControl(30000)))
    assert [e.payload["text"] for e in events if e.kind == "text_delta"] == ["hello"]
    assert next(e.payload for e in events if e.kind == "usage")["input_tokens"] == 3
    body = json.loads(transport.request["body"])
    if provider == "gemini":
        assert body["systemInstruction"] == {"parts":[{"text":"instruction"}]}
        assert body["contents"] == [{"role":"user","parts":[{"text":"question"}]}]
        assert body["generationConfig"]["maxOutputTokens"] == 8
    else:
        assert body["model"] == "configured-model" and body["stream"] is True
    assert transport.request["adapter_id"] == adapter and transport.request["provider_id"] == provider
    assert transport.closed is True
    if provider == "claude": assert body["system"] == "instruction" and body["max_tokens"] == 8
    if provider == "mistral": assert "stream_options" not in body
    if provider == "openai": assert "input" in body and body["max_output_tokens"] == 8


@pytest.mark.parametrize("adapter,provider", [("openai-responses","custom"),("mistral-chat","openai"),("claude-anthropic-messages","mistral")])
def test_service_alias_cannot_select_another_wire(adapter,provider):
    with pytest.raises(PermissionError, match="exact remote adapter/service"): service_protocol(adapter,provider)


@pytest.mark.parametrize("adapter,provider", [("openai-responses","openai"),("mistral-chat","mistral"),("claude-anthropic-messages","claude"),("gemini-generate-content","gemini")])
def test_actual_transport_exact_endpoint_headers_and_tls_pin(adapter,provider,monkeypatch):
    from runtime import remote_provider_adapters as module
    from types import SimpleNamespace
    protocol = service_protocol(adapter,provider)
    calls = {}
    class Connection:
        def __init__(self,hostname,**options): self._context=options["context"]
        def request(self,method,path,**options): calls.update(method=method,path=path,**options)
        def getresponse(self): return SimpleNamespace(status=200)
    raw=SimpleNamespace(close=lambda:None)
    def wrap(sock,server_hostname):
        calls["tls_hostname"]=server_hostname
        return sock
    def connect(address,**options):
        calls["pin"]=address
        return raw
    monkeypatch.setattr(module.http.client,"HTTPSConnection",Connection)
    monkeypatch.setattr(module.ssl,"create_default_context",lambda:SimpleNamespace(wrap_socket=wrap))
    monkeypatch.setattr(module.socket,"create_connection",connect)
    module.PinnedHttpsTransport().open(origin=protocol["origin"],addresses=["8.8.8.8"],body=b"{}",credential="fixture-key",timeout=1,adapter_id=adapter,provider_id=provider,model_id="configured-model")
    assert calls["path"] == protocol["endpoint"].replace("{model}","configured-model") and calls["method"] == "POST"
    assert calls["headers"][protocol["auth_header"]] == protocol["auth_prefix"] + "fixture-key"
    assert all(calls["headers"][k] == v for k,v in protocol["headers"].items())
    assert calls["pin"] == ("8.8.8.8",443) and calls["tls_hostname"] == protocol["origin"][8:]
