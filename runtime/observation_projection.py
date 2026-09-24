"""Reversible projection policy for large observations."""
from __future__ import annotations
import hashlib, json, re
from typing import Mapping
from .evidence_reducer import validate_verified_receipt

SCHEMA_VERSION = "px.observation-pack/1.0"
_SHA = re.compile(r"^[0-9a-f]{64}$")

def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def build_observation_pack(text: str, *, source_locator: str, stable_handle: str, provider_requests_since_observed: int, threshold_chars: int = 10240, full_request_count: int = 2, excerpt_chars: int = 1024, reducer_receipt: Mapping[str, object] | None = None) -> dict[str, object]:
    if type(text) is not str or type(source_locator) is not str or not source_locator.strip() or len(source_locator) > 1024:
        raise ValueError("observation source is invalid")
    if type(stable_handle) is not str or not stable_handle.strip() or len(stable_handle) > 512:
        raise ValueError("stable handle is invalid")
    for value, label, minimum in ((provider_requests_since_observed, "request count", 0), (threshold_chars, "threshold", 1), (full_request_count, "full request count", 0), (excerpt_chars, "excerpt chars", 2)):
        if type(value) is not int or isinstance(value, bool) or value < minimum: raise ValueError(f"{label} is invalid")
    digest = hashlib.sha256(text.encode()).hexdigest(); reduction_sha = None
    if reducer_receipt is not None:
        validate_verified_receipt(reducer_receipt)
        if reducer_receipt.get("source_sha256") != digest or reducer_receipt.get("source_locator") != source_locator:
            raise ValueError("reducer receipt does not bind this observation")
        reduction_sha = str(reducer_receipt["receipt_sha256"])
    show_full = len(text) <= threshold_chars or provider_requests_since_observed < full_request_count
    if reducer_receipt is not None:
        projected = json.dumps(dict(reducer_receipt), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        mode = "verified_receipt"
    elif show_full:
        projected = text; mode = "full"
    else:
        half = max(1, excerpt_chars // 2); head = text[:half]; tail = text[-half:]
        projected = f"{head}\n...[observation archived: handle={stable_handle} sha256={digest} chars={len(text)}]...\n{tail}"
        mode = "handle"
    body = {"schema_version": SCHEMA_VERSION, "mode": mode, "stable_handle": stable_handle, "source_locator": source_locator, "content_sha256": digest, "original_chars": len(text), "projected_text": projected, "reducer_receipt_sha256": reduction_sha, "reversible": True, "authority_granted": False}
    return {**body, "pack_sha256": _hash(body)}

def validate_observation_pack(pack: Mapping[str, object]) -> None:
    if pack.get("schema_version") != SCHEMA_VERSION or pack.get("reversible") is not True or pack.get("authority_granted") is not False:
        raise ValueError("observation pack contract is invalid")
    body = {str(k): v for k, v in pack.items() if k != "pack_sha256"}
    if not _SHA.fullmatch(str(pack.get("content_sha256", ""))) or pack.get("pack_sha256") != _hash(body):
        raise ValueError("observation pack identity is invalid")
