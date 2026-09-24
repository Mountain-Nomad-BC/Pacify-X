"""Immutable model-route evidence and lineage records.

This module is subordinate to :mod:`runtime.models`.  It describes route
signals/decisions and their lineage, but it never selects a model, grants an
effect, promotes learned state, starts a runtime, or mutates routing policy.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable, Mapping, Sequence

from .json_io import bounded_strings, validate_json_value

ROUTE_PHASES = frozenset({"discovery", "calibration", "anneal", "freeze", "certify", "publish"})
CHALLENGER_MODES = frozenset({"none", "threshold", "sample", "always"})
SIGNAL_MATURITY = frozenset({"candidate", "provisional", "stable", "stale", "revoked"})
CAPACITY_STATES = frozenset({"admit", "wait", "deny", "unknown"})
DISPATCH_STATES = frozenset({"dispatch", "wait", "fallback_required", "deterministic_resolved"})
MAX_ROUTE_CANDIDATES = 64
MAX_EVIDENCE_REFS = 64


def _jsonable(value: object) -> object:
    if type(value) is tuple:
        return [_jsonable(item) for item in value]
    if type(value) is list:
        return [_jsonable(item) for item in value]
    if type(value) is dict:
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _canonical(value: object) -> bytes:
    value = _jsonable(value)
    validate_json_value(value, max_nodes=20_000)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _bounded_text(value: object, name: str, *, max_bytes: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} must be bounded nonempty text")
    return value.strip()


def _unit_interval(value: object, name: str) -> float:
    if type(value) not in (int, float) or type(value) is bool:
        raise ValueError(f"{name} must be a finite number in [0,1]")
    number = float(value)
    if not math.isfinite(number) or not 0.0 <= number <= 1.0:
        raise ValueError(f"{name} must be a finite number in [0,1]")
    return number


@dataclass(frozen=True, slots=True)
class AdaptiveRouteSignal:
    """Measured route evidence.  A signal is evidence, never route authority."""

    model_id: str
    affinity: float = 0.0
    quality: float = 0.0
    availability: float = 1.0
    pressure: float = 0.0
    maturity: str = "candidate"
    model_generation_sha256: str | None = None
    evidence_sha256: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.model_id, "route signal model_id")
        for name in ("affinity", "quality", "availability", "pressure"):
            _unit_interval(getattr(self, name), f"route signal {name}")
        if self.maturity not in SIGNAL_MATURITY:
            raise ValueError("unsupported route signal maturity")
        if self.model_generation_sha256 is not None and not _valid_sha256(self.model_generation_sha256):
            raise ValueError("route signal model generation must be lowercase SHA-256 or null")
        if self.maturity in {"stable", "provisional"} and not _valid_sha256(self.model_generation_sha256):
            raise ValueError("mature route signals require exact model-generation identity")
        if type(self.evidence_sha256) is not tuple or len(self.evidence_sha256) > MAX_EVIDENCE_REFS:
            raise ValueError("route signal evidence must be a bounded immutable sequence")
        if len(set(self.evidence_sha256)) != len(self.evidence_sha256) or any(
            not _valid_sha256(value) for value in self.evidence_sha256
        ):
            raise ValueError("route signal evidence requires distinct lowercase SHA-256 identities")
        if self.maturity in {"stable", "provisional"} and not self.evidence_sha256:
            raise ValueError("mature route signals require hashed evidence")

    @property
    def evidence_only(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class RouteCandidateRecord:
    model_id: str
    base_score: float
    adjusted_score: float
    rank: int
    capacity_state: str = "unknown"
    evidence_sha256: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.model_id, "route candidate model_id")
        for name in ("base_score", "adjusted_score"):
            value = getattr(self, name)
            if type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or abs(float(value)) > 1e100:
                raise ValueError(f"route candidate {name} must be a bounded finite number")
        if type(self.rank) is not int or not 1 <= self.rank <= MAX_ROUTE_CANDIDATES:
            raise ValueError("route candidate rank is invalid")
        if self.capacity_state not in CAPACITY_STATES:
            raise ValueError("route candidate capacity state is invalid")
        if type(self.evidence_sha256) is not tuple or len(self.evidence_sha256) > MAX_EVIDENCE_REFS:
            raise ValueError("route candidate evidence budget exceeded")
        if len(set(self.evidence_sha256)) != len(self.evidence_sha256) or any(
            not _valid_sha256(value) for value in self.evidence_sha256
        ):
            raise ValueError("route candidate evidence identities are invalid")
        if type(self.reasons) is not tuple:
            raise ValueError("route candidate reasons must be immutable")
        bounded_strings(self.reasons, max_items=64, max_item_bytes=512, max_bytes=16_384)


@dataclass(frozen=True, slots=True)
class ModelRouteDecision:
    request_id: str
    task_class: str
    subject_ids: tuple[str, ...]
    policy_sha256: str
    policy_semantic_sha256: str
    phase: str
    candidates: tuple[RouteCandidateRecord, ...]
    primary_model_id: str | None
    challenger_model_id: str | None
    dispatch_state: str
    wait_reason: str | None
    fallback_used: bool
    authority_granted: bool
    decision_sha256: str

    def record(self) -> dict[str, object]:
        return _jsonable({
            "schema_version": "px.model-route-decision/1.0",
            **asdict(self),
        })  # type: ignore[return-value]


def build_route_decision(
    *,
    request_id: str,
    task_class: str,
    subject_ids: Iterable[str],
    policy_sha256: str,
    policy_semantic_sha256: str,
    phase: str,
    candidates: Sequence[RouteCandidateRecord],
    primary_model_id: str | None,
    challenger_model_id: str | None = None,
    dispatch_state: str,
    wait_reason: str | None = None,
    fallback_used: bool = False,
) -> ModelRouteDecision:
    """Create an immutable, content-addressed route decision.

    The decision records what ``runtime.models`` selected.  It deliberately
    hard-codes ``authority_granted=False``; execution still requires the normal
    PX effect/provider/model-runtime authorities.
    """

    request = _bounded_text(request_id, "route request_id", max_bytes=512)
    task = _bounded_text(task_class, "route task_class")
    subjects = tuple(
        bounded_strings(subject_ids, max_items=64, max_item_bytes=256, max_bytes=16_384)
    )
    if not subjects:
        raise ValueError("route decisions require at least one admitted subject/task identifier")
    if not _valid_sha256(policy_sha256) or not _valid_sha256(policy_semantic_sha256):
        raise ValueError("route policy byte/semantic identities must be lowercase SHA-256")
    if phase not in ROUTE_PHASES:
        raise ValueError("unsupported route phase")
    rows = tuple(candidates)
    if not 1 <= len(rows) <= MAX_ROUTE_CANDIDATES:
        raise ValueError("route decision requires a bounded nonempty candidate set")
    if any(type(row) is not RouteCandidateRecord for row in rows):
        raise ValueError("route decision candidates must be typed")
    if tuple(row.rank for row in rows) != tuple(range(1, len(rows) + 1)):
        raise ValueError("route candidate ranks must be contiguous and ordered")
    ids = tuple(row.model_id for row in rows)
    if len(set(ids)) != len(ids):
        raise ValueError("route candidate identities must be distinct")
    if primary_model_id is not None and primary_model_id not in ids:
        raise ValueError("primary route must be present in the candidate set")
    if challenger_model_id is not None:
        if challenger_model_id not in ids or challenger_model_id == primary_model_id:
            raise ValueError("challenger route must be a distinct candidate")
    if dispatch_state not in DISPATCH_STATES:
        raise ValueError("unsupported route dispatch state")
    if dispatch_state == "dispatch" and primary_model_id is None:
        raise ValueError("dispatch decisions require a primary model")
    if dispatch_state == "wait" and (primary_model_id is None or not wait_reason):
        raise ValueError("wait decisions require a primary model and wait reason")
    if dispatch_state in {"fallback_required", "deterministic_resolved"} and challenger_model_id is not None:
        raise ValueError("non-dispatch route decisions cannot carry a challenger")
    if wait_reason is not None:
        wait_reason = _bounded_text(wait_reason, "route wait_reason", max_bytes=512)
    if type(fallback_used) is not bool:
        raise ValueError("fallback_used must be boolean")

    body = {
        "schema_version": "px.model-route-decision/1.0",
        "request_id": request,
        "task_class": task,
        "subject_ids": list(subjects),
        "policy_sha256": policy_sha256,
        "policy_semantic_sha256": policy_semantic_sha256,
        "phase": phase,
        "candidates": [_jsonable(asdict(row)) for row in rows],
        "primary_model_id": primary_model_id,
        "challenger_model_id": challenger_model_id,
        "dispatch_state": dispatch_state,
        "wait_reason": wait_reason,
        "fallback_used": fallback_used,
        "authority_granted": False,
    }
    digest = _sha256(body)
    return ModelRouteDecision(
        request_id=request,
        task_class=task,
        subject_ids=subjects,
        policy_sha256=policy_sha256,
        policy_semantic_sha256=policy_semantic_sha256,
        phase=phase,
        candidates=rows,
        primary_model_id=primary_model_id,
        challenger_model_id=challenger_model_id,
        dispatch_state=dispatch_state,
        wait_reason=wait_reason,
        fallback_used=fallback_used,
        authority_granted=False,
        decision_sha256=digest,
    )


def stable_sample(key: str, *, rate: float, namespace: str = "px.model-route-challenger/1") -> bool:
    """Deterministic shadow sampling; never use process-randomized ``hash()``."""

    _bounded_text(key, "sample key", max_bytes=1024)
    _bounded_text(namespace, "sample namespace", max_bytes=256)
    rate = _unit_interval(rate, "sample rate")
    digest = hashlib.sha256(f"{namespace}\0{key}".encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:8], "big") / float(2**64)
    return bucket < rate


def route_transition_record(
    *,
    before_decision_sha256: str,
    after_decision_sha256: str,
    trigger: str,
    evidence_sha256: Sequence[str],
) -> dict[str, object]:
    """Record a route transition as evidence without authorizing policy mutation."""

    if not _valid_sha256(before_decision_sha256) or not _valid_sha256(after_decision_sha256):
        raise ValueError("route transition requires valid decision identities")
    if before_decision_sha256 == after_decision_sha256:
        raise ValueError("route transition requires distinct before/after decisions")
    trigger = _bounded_text(trigger, "route transition trigger", max_bytes=512)
    evidence = tuple(evidence_sha256)
    if not 1 <= len(evidence) <= MAX_EVIDENCE_REFS or len(set(evidence)) != len(evidence) or any(
        not _valid_sha256(value) for value in evidence
    ):
        raise ValueError("route transition requires distinct bounded evidence identities")
    body = {
        "schema_version": "px.model-route-transition/1.0",
        "before_decision_sha256": before_decision_sha256,
        "after_decision_sha256": after_decision_sha256,
        "trigger": trigger,
        "evidence_sha256": sorted(evidence),
        "authority_granted": False,
        "promotion_required": True,
    }
    return {**body, "transition_sha256": _sha256(body)}
