"""Deterministic receipts for model/semantic integration queries."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Mapping

from .semantic_code_types import canonical_json_bytes, stable_sha256
from .semantic_integration_limits import SemanticIntegrationLimits


def _identity_text(value: str | None, field: str, *, nullable: bool = False) -> None:
    if nullable and value is None:
        return
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 512:
        raise ValueError(f"{field} must be bounded nonempty text")


def query_receipt(
    *,
    operation: str,
    actor_id: str,
    project_id: str,
    request: Mapping[str, object],
    result_identity: Mapping[str, object],
    authority_token_id: str | None = None,
    observed_at: datetime | None = None,
    limits: SemanticIntegrationLimits = SemanticIntegrationLimits(),
) -> dict[str, object]:
    # observed_at is evidence metadata and intentionally excluded from deterministic identity.
    _identity_text(operation, "operation")
    _identity_text(actor_id, "actor_id")
    _identity_text(project_id, "project_id")
    _identity_text(authority_token_id, "authority_token_id", nullable=True)
    if not isinstance(request, Mapping) or not isinstance(result_identity, Mapping):
        raise TypeError("request and result_identity must be mappings")
    request_bytes = canonical_json_bytes(request)
    result_bytes = canonical_json_bytes(result_identity)
    if len(request_bytes) > limits.max_query_bytes:
        raise ValueError("receipt request identity exceeds query budget")
    if len(result_bytes) > limits.max_receipt_bytes:
        raise ValueError("receipt result identity exceeds receipt budget")

    moment = observed_at or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    identity = {
        "schema_version": "px.semantic-query-receipt/1.0",
        "operation": operation,
        "actor_id": actor_id,
        "project_id": project_id,
        "authority_token_id": authority_token_id,
        "request_sha256": stable_sha256(request),
        "result_sha256": stable_sha256(result_identity),
    }
    receipt = {
        **identity,
        "receipt_sha256": stable_sha256(identity),
        "observed_at": moment.astimezone(timezone.utc).isoformat(),
    }
    if len(json.dumps(receipt, sort_keys=True).encode("utf-8")) > limits.max_receipt_bytes:
        raise ValueError("receipt budget exceeded")
    return receipt
