"""Native text-only Gemini translation; no tools, transport or authority."""

def request_payload(request):
    if request.tools or request.response_schema is not None:
        raise ValueError('Gemini tool/schema contract unavailable')
    contents, system = [], []
    for message in request.messages:
        role, content = message['role'], message['content']
        if type(content) is not str:
            raise ValueError('Gemini text-only content required')
        part = {'text': content}
        if role in {'system', 'developer'}:
            system.append(part)
        elif role in {'user', 'assistant'}:
            contents.append({'role': 'model' if role == 'assistant' else 'user', 'parts': [part]})
        else:
            raise ValueError('Gemini tool-result contract unavailable')
    if not contents:
        raise ValueError('Gemini requires actual conversational contents')
    payload = {'contents': contents, 'generationConfig': {'maxOutputTokens': request.max_output_tokens, 'candidateCount': 1}}
    if system:
        payload['systemInstruction'] = {'parts': system}
    return payload


def stream_events(owner, payload):
    if payload.get('error') or payload.get('promptFeedback', {}).get('blockReason'):
        raise ValueError('Gemini rejected the request')
    out = []
    if isinstance(payload.get('responseId'), str):
        owner._provider_request_id = payload['responseId']
    usage = payload.get('usageMetadata')
    if usage is not None:
        if type(usage) is not dict or any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('promptTokenCount', 'candidatesTokenCount')):
            raise ValueError('Gemini exact usage counters required')
        thoughts = usage.get('thoughtsTokenCount', 0)
        if type(thoughts) is not int or thoughts < 0:
            raise ValueError('Gemini thought token counter invalid')
        owner._input_tokens = usage['promptTokenCount']
        owner._output_tokens = usage['candidatesTokenCount'] + thoughts
    candidates = payload.get('candidates', [])
    if type(candidates) is not list or len(candidates) > 1:
        raise ValueError('Gemini requires one candidate')
    if not candidates:
        return out
    candidate = candidates[0]
    if type(candidate) is not dict or candidate.get('index', 0) != 0:
        raise ValueError('Gemini candidate identity invalid')
    content = candidate.get('content', {})
    if type(content) is not dict or content.get('role', 'model') != 'model' or type(content.get('parts', [])) is not list:
        raise ValueError('Gemini content invalid')
    for part in content.get('parts', []):
        if type(part) is not dict or set(part) - {'text', 'thought', 'thoughtSignature'} or type(part.get('text')) is not str:
            raise ValueError('Gemini unsupported content part')
        if 'thought' in part and type(part['thought']) is not bool:
            raise ValueError('Gemini thought marker invalid')
        if part['text'].strip():
            out.append(owner._event('reasoning_delta' if part.get('thought') else 'text_delta', {'text': part['text']}))
    reason = candidate.get('finishReason')
    if reason:
        if reason not in {'STOP', 'MAX_TOKENS'}:
            raise ValueError('Gemini terminal candidate was blocked or unsupported')
        if owner._input_tokens is None or owner._output_tokens is None:
            raise ValueError('Gemini terminal usage unavailable')
        out.extend(owner._terminal('length' if reason == 'MAX_TOKENS' else 'stop'))
    return out
