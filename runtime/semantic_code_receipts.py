"""Deterministic receipts for semantic reads and mutation attempts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .semantic_code_types import stable_sha256


def semantic_receipt(
    *,
    operation: str,
    project_revision: str | None,
    source_revision: str | None,
    result: Any,
    include_timestamp: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "operation": operation,
        "project_revision": project_revision,
        "source_revision": source_revision,
        "result_sha256": stable_sha256(result),
    }
    if include_timestamp:
        payload["observed_utc"] = datetime.now(timezone.utc).isoformat()
    payload["receipt_sha256"] = stable_sha256(payload)
    return payload
