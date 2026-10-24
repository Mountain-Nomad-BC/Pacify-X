"""Authorable exact service wire mapping; it grants no provider admission."""
from pathlib import Path
from .archive_io import reject_path_links
from .json_io import load_json_object
from .model_protocol import validate_protocol_surface


def service_protocol(adapter_id, provider_id):
    path = Path(__file__).with_suffix('.json')
    reject_path_links(path)
    document = load_json_object(path, max_bytes=32 * 1024)
    rows = document.get('adapters')
    if document.get('schema_version') != 'px.remote-service-protocols/1.0' or type(rows) is not dict:
        raise ValueError('remote service protocol mapping invalid')
    row = rows.get(adapter_id)
    fields = {'provider_id', 'surface', 'origin', 'endpoint', 'auth_header', 'auth_prefix', 'headers', 'omit_stream_options'}
    if (type(row) is not dict or set(row) != fields or row['provider_id'] != provider_id
            or type(row['headers']) is not dict or type(row['omit_stream_options']) is not bool
            or row['auth_header'] not in {'Authorization', 'X-Api-Key', 'X-Goog-Api-Key'}
            or row['auth_prefix'] not in {'Bearer ', ''}
            or row['endpoint'] not in {'/v1/chat/completions', '/v1/responses', '/v1/messages', '/v1beta/models/{model}:streamGenerateContent?alt=sse'}):
        raise PermissionError('exact remote adapter/service protocol unavailable')
    validate_protocol_surface(row['surface'])
    return row


def service_endpoint(protocol, model_id=None):
    endpoint = protocol['endpoint']
    if '{model}' in endpoint:
        import re
        if type(model_id) is not str or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,255}', model_id) is None:
            raise ValueError('Gemini model must be one bounded resource component')
        return endpoint.replace('{model}', model_id)
    return endpoint
