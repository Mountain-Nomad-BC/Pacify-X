from datetime import datetime, timezone
from runtime.semantic_query_receipts import query_receipt

def test_receipt_identity_is_time_independent():
    a = query_receipt(operation="x", actor_id="a", project_id="p", request={"q":1}, result_identity={"r":2}, observed_at=datetime(2026,1,1,tzinfo=timezone.utc))
    b = query_receipt(operation="x", actor_id="a", project_id="p", request={"q":1}, result_identity={"r":2}, observed_at=datetime(2026,2,1,tzinfo=timezone.utc))
    assert a["receipt_sha256"] == b["receipt_sha256"]
    assert a["observed_at"] != b["observed_at"]

import pytest
from runtime.semantic_integration_limits import SemanticIntegrationLimits


def test_receipt_rejects_naive_time_and_oversized_request_identity():
    with pytest.raises(ValueError, match="timezone-aware"):
        query_receipt(
            operation="x", actor_id="a", project_id="p",
            request={"q": 1}, result_identity={"r": 2},
            observed_at=datetime(2026, 1, 1),
        )
    limits = SemanticIntegrationLimits(max_query_bytes=8)
    with pytest.raises(ValueError, match="query budget"):
        query_receipt(
            operation="x", actor_id="a", project_id="p",
            request={"query": "too large"}, result_identity={"r": 2}, limits=limits,
        )
