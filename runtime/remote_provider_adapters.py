"""Closed service wire protocols behind the canonical gateway."""
import http.client
import socket
import ssl

from .model_protocol_translate import canonical_request_to_wire, WireStreamTranslator, iter_sse_frames
from .json_io import bounded_canonical_json_bytes
from .provider_budget import ProviderUsage
from .provider_gateway import MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES
from .remote_provider_profiles import ADAPTER, https_origin
from .remote_service_protocols import service_protocol, service_endpoint


class PinnedHttpsTransport:
    """TLS verifies the configured hostname while sockets use approved public pins.

    No DNS resolution, environment proxy, redirect following or alternate origin.
    """
    def open(self, *, origin, addresses, body, credential, timeout,
             adapter_id=ADAPTER, provider_id='custom', model_id=None):
        hostname = https_origin(origin, addresses)
        protocol = service_protocol(adapter_id, provider_id)
        if protocol['origin'] is not None and origin != protocol['origin']:
            raise PermissionError('remote service origin differs')
        endpoint = service_endpoint(protocol, model_id)
        connection = http.client.HTTPSConnection(hostname, timeout=timeout,
                                                 context=ssl.create_default_context())
        raw = socket.create_connection((addresses[0], 443), timeout=timeout)
        try:
            connection.sock = connection._context.wrap_socket(raw, server_hostname=hostname)
            headers = {'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                       **protocol['headers'], protocol['auth_header']: protocol['auth_prefix'] + credential}
            connection.request('POST', endpoint, body=body, headers=headers)
            response = connection.getresponse()
            if response.status != 200:
                # Preserve typed status without body, credentials, endpoint or private data.
                from urllib.error import HTTPError
                raise HTTPError('', response.status, 'remote provider failure', response.headers, None)
            return connection, response
        except BaseException:
            raw.close()
            connection.close()
            raise


class RemoteStreamingAdapter:
    def __init__(self, profile, *, credential_resolver, validate_current, transport=None):
        self.protocol = service_protocol(profile['adapter_id'], profile['provider_id'])
        if self.protocol['origin'] is not None and profile['origin'] != self.protocol['origin']:
            raise PermissionError('remote service origin differs')
        self.adapter_id = profile['adapter_id']
        self.protocol_surface = self.protocol['surface']
        self.profile = profile
        self.credential_resolver = credential_resolver
        self.validate_current = validate_current
        self.transport = transport or PinnedHttpsTransport()

    def stream(self, model_id, request, control):
        if model_id != self.profile['model_id'] or request.route != self.adapter_id or request.privacy != 'policy_gated':
            raise PermissionError('remote canonical identity differs')
        if request.tools or request.response_schema is not None:
            raise PermissionError('remote protocol has no tool/schema execution contract')
        control.check()
        self.validate_current()
        credential = self.credential_resolver(self.profile['credential_reference'])
        if type(credential) is not str or not credential or len(credential) > 8192 or any(ord(c) < 33 or ord(c) > 126 for c in credential):
            raise PermissionError('remote credential unavailable')
        payload = canonical_request_to_wire(request, surface=self.protocol_surface,
                                            model_id=model_id, stream=True)
        if self.protocol['omit_stream_options']:
            payload.pop('stream_options', None)
        body = bounded_canonical_json_bytes(payload, max_bytes=MAX_REQUEST_BYTES)
        control.check()
        self.validate_current()
        connection, response = self.transport.open(origin=self.profile['origin'],
            addresses=self.profile['approved_addresses'], body=body, credential=credential,
            timeout=control.remaining_seconds(cap=120), adapter_id=self.adapter_id,
            provider_id=self.profile['provider_id'], model_id=model_id)
        translator = WireStreamTranslator(surface=self.protocol_surface, request_id=request.request_id,
                                           adapter_id=self.adapter_id, model_id=model_id)
        try:
            def lines():
                total = 0
                while True:
                    control.check()
                    self.validate_current()
                    line = response.readline(MAX_RESPONSE_BYTES + 1)
                    if not line:
                        return
                    if type(line) is not bytes:
                        raise ValueError('remote stream transport must yield bytes')
                    total += len(line)
                    if total > MAX_RESPONSE_BYTES * 4:
                        raise ValueError('remote stream exceeds transport bound')
                    yield line
            for name, data in iter_sse_frames(lines()):
                control.check()
                for event in translator.feed_sse(name, data):
                    yield event
            if not translator.finished:
                raise ValueError('remote stream has no terminal event')
            self.validate_current()
        finally:
            response.close()
            connection.close()

    def provider_usage(self, usage):
        if any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('input_tokens', 'output_tokens')):
            raise ValueError('remote exact terminal usage required')
        return ProviderUsage('unknown', usage['input_tokens'], usage['output_tokens'], None,
                             usage.get('provider_request_id'))


class CustomOpenAIChatAdapter(RemoteStreamingAdapter):
    adapter_id = ADAPTER
    protocol_surface = 'openai_chat'

    def __init__(self, profile, **options):
        if profile['adapter_id'] != ADAPTER or profile['provider_id'] != 'custom':
            raise PermissionError('custom adapter cannot alias a named service')
        super().__init__(profile, **options)


def remote_adapter_for(profile, **options):
    """Closed native factory for the enclosing prepared effect owner."""
    return RemoteStreamingAdapter(profile, **options)
