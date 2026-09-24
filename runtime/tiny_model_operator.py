"""Governed tiny-model adapter for bounded PX candidate selection.

The adapter is deliberately authority-free. PX supplies a closed candidate set;
the model may only select/reorder those IDs or return unresolved. Any invented ID,
malformed output, timeout, or contract drift fails closed.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

MAX_CANDIDATES = 64
MAX_RESPONSE_BYTES = 64 * 1024
MAX_REASON_BYTES = 4096


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _text(value: object, name: str, maximum: int = 512) -> str:
    result = str(value or "").strip()
    if not result or len(result.encode("utf-8")) > maximum:
        raise ValueError(f"{name} must be nonempty bounded text")
    return result


@dataclass(frozen=True, slots=True)
class OperatorCandidate:
    candidate_id: str
    category: str
    revision: str
    summary: str
    score: float
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _text(self.candidate_id, "candidate_id", 512)
        _text(self.category, "category", 128)
        _text(self.revision, "revision", 256)
        if len(self.summary.encode("utf-8")) > 4096:
            raise ValueError("candidate summary exceeds bound")
        if not 0.0 <= float(self.score) <= 1.0:
            raise ValueError("candidate score must be in [0,1]")
        if len(self.evidence_refs) > 16 or any(len(str(item).encode("utf-8")) > 1024 for item in self.evidence_refs):
            raise ValueError("candidate evidence exceeds bound")


@dataclass(frozen=True, slots=True)
class OperatorDecision:
    selected_ids: tuple[str, ...]
    unresolved: bool
    reason: str
    invoked: bool
    repaired: bool
    receipt_sha256: str
    raw_response_sha256: str | None


class TinyModelOperator:
    """Schema-validating wrapper around an injected local-model invocation.

    ``invoke`` receives one JSON-serializable request and returns text/bytes or a
    JSON-compatible mapping. It is intentionally injected so process/provider
    custody remains with PX's model gateway/runtime owners.
    """

    def __init__(
        self,
        invoke: Callable[[Mapping[str, Any]], object],
        *,
        model_id: str,
        profile_id: str,
        model_generation: str,
        fabric_generation: str,
        max_selected: int = 3,
        timeout_ms: int = 5000,
    ) -> None:
        self._invoke = invoke
        self.model_id = _text(model_id, "model_id", 256)
        self.profile_id = _text(profile_id, "profile_id", 256)
        self.model_generation = _text(model_generation, "model_generation", 256)
        self.fabric_generation = _text(fabric_generation, "fabric_generation", 256)
        if not 1 <= int(max_selected) <= 3:
            raise ValueError("max_selected must be 1..3")
        self.max_selected = int(max_selected)
        if not 250 <= int(timeout_ms) <= 30_000:
            raise ValueError("timeout_ms must be 250..30000")
        self.timeout_ms = int(timeout_ms)

    @staticmethod
    def _decode(value: object) -> tuple[dict[str, Any], str]:
        if isinstance(value, Mapping):
            payload = dict(value)
            raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        else:
            if isinstance(value, bytes):
                if len(value) > MAX_RESPONSE_BYTES:
                    raise ValueError("operator response exceeds byte bound")
                raw = value.decode("utf-8")
            else:
                raw = str(value)
                if len(raw.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise ValueError("operator response exceeds byte bound")
            payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("operator response must be a JSON object")
        return payload, raw

    def _validate(self, payload: Mapping[str, Any], allowed: set[str]) -> tuple[tuple[str, ...], bool, str]:
        if set(payload) - {"selected_ids", "unresolved", "reason"}:
            raise ValueError("operator response contains unsupported fields")
        selected = payload.get("selected_ids", [])
        if not isinstance(selected, list) or len(selected) > self.max_selected:
            raise ValueError("operator selected_ids must be a bounded list")
        normalized: list[str] = []
        for item in selected:
            value = str(item).strip()
            if value not in allowed:
                raise ValueError(f"operator returned non-candidate id: {value}")
            if value not in normalized:
                normalized.append(value)
        unresolved = payload.get("unresolved", False)
        if not isinstance(unresolved, bool):
            raise ValueError("operator unresolved must be boolean")
        reason = str(payload.get("reason", "")).strip()
        if len(reason.encode("utf-8")) > MAX_REASON_BYTES:
            raise ValueError("operator reason exceeds bound")
        if not normalized and not unresolved:
            raise ValueError("operator must select a candidate or explicitly return unresolved")
        if unresolved and normalized:
            raise ValueError("unresolved response cannot also select candidates")
        return tuple(normalized), unresolved, reason

    def select(
        self,
        *,
        query: str,
        purpose: str,
        candidates: Sequence[OperatorCandidate],
        contract_revision: str,
        retrieval_generation: str,
        constraints: Sequence[str] = (),
    ) -> OperatorDecision:
        query = _text(query, "query", 16_384)
        purpose = _text(purpose, "purpose", 256)
        contract_revision = _text(contract_revision, "contract_revision", 256)
        retrieval_generation = _text(retrieval_generation, "retrieval_generation", 256)
        rows = tuple(candidates)
        if not rows or len(rows) > MAX_CANDIDATES:
            raise ValueError("operator candidate count must be 1..64")
        ids = [row.candidate_id for row in rows]
        if len(set(ids)) != len(ids):
            raise ValueError("operator candidate IDs must be unique")
        if len(rows) == 1:
            receipt = {
                "schema_version": "px.tiny-operator-decision/1.0",
                "deterministic": True,
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                "selected_ids": ids,
                "candidate_ids": ids,
                "model_id": self.model_id,
                "profile_id": self.profile_id,
                "model_generation": self.model_generation,
                "fabric_generation": self.fabric_generation,
                "retrieval_generation": retrieval_generation,
                "contract_revision": contract_revision,
            }
            return OperatorDecision((ids[0],), False, "single eligible candidate", False, False, _stable(receipt), None)

        request = {
            "schema_version": "px.tiny-operator-request/1.0",
            "purpose": purpose,
            "query": query,
            "model_id": self.model_id,
            "profile_id": self.profile_id,
            "model_generation": self.model_generation,
            "fabric_generation": self.fabric_generation,
            "retrieval_generation": retrieval_generation,
            "contract_revision": contract_revision,
            "constraints": [str(item)[:1000] for item in constraints[:24]],
            "candidate_ids_are_closed_world": True,
            "candidate_count": len(rows),
            "candidates": [asdict(row) for row in rows],
            "execution_policy": {
                "timeout_ms": self.timeout_ms,
                "reasoning": "disabled",
                "temperature": 0,
                "max_output_tokens": 256,
                "cancellation_owner": "injected-px-provider-runtime",
            },
            "required_output": {
                "selected_ids": f"array of 0..{self.max_selected} candidate IDs only",
                "unresolved": "boolean",
                "reason": "brief text",
            },
            "authority_granted": False,
        }
        allowed = set(ids)
        repaired = False
        raw_hash: str | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            current = request if attempt == 0 else {
                **request,
                "repair": {
                    "attempt": 1,
                    "instruction": "Return only the required JSON object. Do not invent IDs. If uncertain, set unresolved=true and selected_ids=[].",
                    "previous_error": type(last_error).__name__ if last_error else "invalid-output",
                },
            }
            try:
                payload, raw = self._decode(self._invoke(current))
                raw_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                selected, unresolved, reason = self._validate(payload, allowed)
                receipt = {
                    "schema_version": "px.tiny-operator-decision/1.0",
                    "deterministic": False,
                    "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
                    "candidate_ids": ids,
                    "selected_ids": list(selected),
                    "unresolved": unresolved,
                    "model_id": self.model_id,
                    "profile_id": self.profile_id,
                    "model_generation": self.model_generation,
                    "fabric_generation": self.fabric_generation,
                    "retrieval_generation": retrieval_generation,
                    "contract_revision": contract_revision,
                    "raw_response_sha256": raw_hash,
                    "repaired": attempt == 1,
                    "authority_granted": False,
                }
                return OperatorDecision(selected, unresolved, reason, True, attempt == 1, _stable(receipt), raw_hash)
            except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as error:
                last_error = error
                repaired = attempt == 1
        raise ValueError(f"tiny operator failed closed after bounded repair: {type(last_error).__name__}")
