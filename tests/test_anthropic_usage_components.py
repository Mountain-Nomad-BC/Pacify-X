import json
import pytest
from runtime.model_protocol_translate import WireStreamTranslator


def translator():
    return WireStreamTranslator(surface="anthropic_messages", request_id="r", adapter_id="a", model_id="m")


@pytest.mark.parametrize("initial,delta,total", [
    ({"input_tokens": 7}, {"output_tokens": 3}, 7),
    ({"input_tokens": 0, "cache_creation_input_tokens": 4, "cache_read_input_tokens": 8}, {"output_tokens": 0}, 12),
    ({"input_tokens": 2, "cache_creation_input_tokens": 4, "cache_read_input_tokens": 8}, {"input_tokens": 3, "cache_read_input_tokens": 9, "output_tokens": 2}, 16),
])
def test_reported_components_are_current_and_summed(initial, delta, total):
    t = translator()
    t.feed_sse(None, json.dumps({"type": "message_start", "message": {"usage": initial}}))
    t.feed_sse(None, json.dumps({"type": "message_delta", "usage": delta}))
    events = t.feed_sse(None, '{"type":"message_stop"}')
    usage = next(e.payload for e in events if e.kind == "usage")
    assert usage == {"input_tokens": total, "output_tokens": delta["output_tokens"]}


@pytest.mark.parametrize("key", ["input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens"])
@pytest.mark.parametrize("value", [-1, True, "2", None])
def test_invalid_reported_component_refused(key, value):
    with pytest.raises(ValueError, match="nonnegative integer"):
        translator().feed_sse(None, json.dumps({"type": "message_delta", "usage": {key: value}}))


def test_cache_counts_do_not_invent_missing_uncached_usage():
    t = translator()
    t.feed_sse(None, '{"type":"message_delta","usage":{"cache_read_input_tokens":5,"output_tokens":2}}')
    assert all(e.kind != "usage" for e in t.feed_sse(None, '{"type":"message_stop"}'))
