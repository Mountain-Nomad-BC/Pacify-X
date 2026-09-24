from __future__ import annotations

from runtime.semantic_code_receipts import semantic_receipt


def test_receipt_is_deterministic_without_observation_timestamp():
    one = semantic_receipt(
        operation="x", project_revision="p", source_revision="s", result={"a": 1}
    )
    two = semantic_receipt(
        operation="x", project_revision="p", source_revision="s", result={"a": 1}
    )
    assert one == two
    assert len(one["receipt_sha256"]) == 64
