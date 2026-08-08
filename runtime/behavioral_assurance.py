"""Behavioral assurance and non-mutating closed-loop improvement primitives."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
import hashlib
import re
import time
from typing import Any, Callable, Iterable, Mapping


TOKEN = re.compile(r"[a-z0-9]+")
DISCRIMINATING_ROLES = {"negative", "boundary", "degradation"}


@dataclass(frozen=True, slots=True)
class Control:
    control_id: str
    role: str
    payload: Any
    oracle: Any


@dataclass(frozen=True, slots=True)
class ControlResult:
    control_id: str
    role: str
    passed: bool
    elapsed_ms: float
    observed: Any
    error_type: str | None = None


@dataclass(frozen=True, slots=True)
class ProbeResult:
    passed: bool
    degraded: bool
    discriminating: bool
    controls: tuple[ControlResult, ...]
    reasons: tuple[str, ...]


def run_behavioral_probe(
    controls: Iterable[Control],
    invoke: Callable[[Any], Any],
    compare: Callable[[Any, Any], bool],
    *,
    max_latency_ms: float | None = None,
) -> ProbeResult:
    declared = tuple(controls)
    roles = {item.role for item in declared}
    reasons: list[str] = []
    if max_latency_ms is not None and max_latency_ms < 0:
        raise ValueError("maximum latency must be non-negative")
    if len({item.control_id for item in declared}) != len(declared):
        reasons.append("duplicate_control_id")
    if roles - ({"positive"} | DISCRIMINATING_ROLES):
        reasons.append("invalid_control_role")
    if "positive" not in roles:
        reasons.append("missing_positive_control")
    if not roles.intersection(DISCRIMINATING_ROLES):
        reasons.append("missing_discriminating_control")
    results: list[ControlResult] = []
    for control in declared:
        started = time.perf_counter()
        try:
            observed = invoke(control.payload)
            error_type = None
            passed = bool(compare(observed, control.oracle))
        except Exception as error:  # sanitized; evidence layer owns details
            observed = None
            error_type = type(error).__name__
            passed = False
        elapsed = (time.perf_counter() - started) * 1000
        if max_latency_ms is not None and elapsed > max_latency_ms:
            reasons.append(f"latency_exceeded:{control.control_id}")
            passed = False
        if not passed:
            reasons.append(f"control_failed:{control.control_id}")
        results.append(
            ControlResult(
                control.control_id,
                control.role,
                passed,
                elapsed,
                observed,
                error_type,
            )
        )
    distinct_oracles = {repr(item.oracle) for item in declared}
    distinct_observations = {repr(item.observed) for item in results}
    discriminating = len(distinct_oracles) < 2 or len(distinct_observations) >= 2
    if not discriminating:
        reasons.append("constant_output_not_discriminating")
    passed = bool(results) and all(item.passed for item in results) and not reasons
    return ProbeResult(
        passed,
        any(item.error_type is not None for item in results),
        discriminating,
        tuple(results),
        tuple(sorted(set(reasons))),
    )


CAUSE_ROUTES = {
    "source_absent": "source",
    "source_insufficient": "source",
    "retrieval_miss": "retrieval",
    "ranking_failure": "ranking",
    "reasoning_failure": "reasoning",
    "scope_refusal_failure": "scope",
    "dependency_degraded": "dependency",
    "stale_knowledge": "freshness",
    "contradiction": "contradiction_review",
    "policy_denial": "policy_review",
    "tool_failure": "tooling",
    "oracle_ambiguous": "oracle_review",
    "unknown": "manual_triage",
}


@dataclass(frozen=True, slots=True)
class FailureSignals:
    expected_in_scope: bool = True
    dependency_healthy: bool = True
    policy_denied: bool = False
    tool_failed: bool = False
    retrieved_count: int = 0
    deep_search_has_support: bool = False
    shown_context_has_support: bool = False
    answer_has_required_support: bool = False
    source_stale: bool = False
    contradiction_present: bool = False
    oracle_reliable: bool = True


def attribute_failure(signals: FailureSignals) -> dict[str, Any]:
    if signals.retrieved_count < 0:
        raise ValueError("retrieved_count must be non-negative")
    contributors: list[tuple[str, float]] = []
    reasons: list[str] = []
    fixed = (
        (not signals.oracle_reliable, "oracle_ambiguous", 0.95, "oracle_not_reliable"),
        (signals.policy_denied, "policy_denial", 0.99, "policy_denied"),
        (signals.tool_failed, "tool_failure", 0.98, "tool_failed"),
        (not signals.dependency_healthy, "dependency_degraded", 0.97, "dependency_unhealthy"),
        (signals.contradiction_present, "contradiction", 0.90, "conflicting_evidence"),
        (signals.source_stale, "stale_knowledge", 0.88, "source_stale"),
    )
    for active, cause, confidence, reason in fixed:
        if active:
            contributors.append((cause, confidence))
            reasons.append(reason)
    if not signals.expected_in_scope:
        if signals.answer_has_required_support:
            contributors.append(("scope_refusal_failure", 0.96))
            reasons.append("out_of_scope_answered")
    elif signals.retrieved_count == 0:
        cause = "ranking_failure" if signals.deep_search_has_support else "source_absent"
        contributors.append((cause, 0.90 if signals.deep_search_has_support else 0.80))
        reasons.append("no_visible_retrieval")
    elif not signals.shown_context_has_support:
        cause = "ranking_failure" if signals.deep_search_has_support else "retrieval_miss"
        contributors.append((cause, 0.88 if signals.deep_search_has_support else 0.72))
        reasons.append("retrieved_context_lacks_support")
    elif not signals.answer_has_required_support:
        contributors.extend((("source_insufficient", 0.70), ("reasoning_failure", 0.60)))
        reasons.append("supported_context_did_not_reach_answer")
    if not contributors:
        contributors.append(("unknown", 0.35))
        reasons.append("insufficient_signals")
    contributors.sort(key=lambda item: (-item[1], item[0]))
    primary, confidence = contributors[0]
    return {
        "primary": primary,
        "confidence": confidence,
        "recommended_route": CAUSE_ROUTES[primary],
        "contributors": tuple(
            {"cause": cause, "confidence": value} for cause, value in contributors
        ),
        "reasons": tuple(sorted(set(reasons))),
        "mutation_allowed": False,
    }


def validate_evaluation_lineage(lineage: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    case_class = str(lineage.get("case_class", ""))
    origin = str(lineage.get("origin", ""))
    authority = str(lineage.get("oracle_authority", ""))
    if origin in {"model_generated", "derived"} and authority in {
        "model_provisional",
        "unknown",
    }:
        reasons.append("generated_case_cannot_self_certify")
    if case_class in {"holdout", "external_benchmark"}:
        if lineage.get("treatment_visibility") == "visible":
            reasons.append("protected_case_visible_to_treatment")
        if lineage.get("oracle_visibility") == "visible":
            reasons.append("protected_oracle_visible_before_run")
    if not lineage.get("source_refs"):
        reasons.append("lineage_source_missing")
    return not reasons, tuple(sorted(set(reasons)))


def normalize_query(text: str) -> str:
    return " ".join(TOKEN.findall(text.casefold()))


def query_hash(text: str) -> str:
    return hashlib.sha256(normalize_query(text).encode("utf-8")).hexdigest()


def cluster_coverage_frontier(
    queries: Iterable[str], *, min_chars: int = 12
) -> tuple[dict[str, Any], ...]:
    counts: Counter[str] = Counter()
    for raw in queries:
        normalized = normalize_query(raw)
        if len(normalized) < min_chars:
            continue
        counts[normalized] += 1
    return tuple(
        {
            "representative": key,
            "normalized": key,
            "query_sha256": hashlib.sha256(key.encode("utf-8")).hexdigest(),
            "demand_count": count,
            "oracle_known": False,
            "candidate_only": True,
        }
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    )


def conservative_near_duplicate(a: str, b: str, *, threshold: float = 0.94) -> bool:
    left, right = normalize_query(a), normalize_query(b)
    if not left or not right or not 0 <= threshold <= 1:
        return False
    return SequenceMatcher(a=left, b=right).ratio() >= threshold


def prioritize_improvement(
    *,
    failure_severity: float,
    demand: float,
    confidence: float,
    regression: bool,
    safety_critical: bool,
    risk_of_change: float,
) -> dict[str, Any]:
    normalized = (failure_severity, confidence, risk_of_change)
    if any(value < 0 or value > 1 for value in normalized) or demand < 0:
        raise ValueError("normalized inputs are out of range")
    demand_component = min(1.0, demand / 10.0)
    score = 100 * (
        0.30 * failure_severity
        + 0.20 * demand_component
        + 0.20 * confidence
        + 0.15 * float(regression)
        + 0.15 * float(safety_critical)
    )
    score *= 1.0 - 0.35 * risk_of_change
    reasons = []
    for active, reason in (
        (regression, "regression"),
        (safety_critical, "safety_critical"),
        (demand_component >= 0.5, "high_demand"),
        (confidence < 0.6, "low_attribution_confidence"),
        (risk_of_change > 0.7, "high_change_risk"),
    ):
        if active:
            reasons.append(reason)
    return {
        "priority": round(max(0.0, min(100.0, score)), 3),
        "reasons": tuple(reasons),
        "admission_required": True,
        "mutation_allowed": False,
    }


def assurance_score(
    axes: Mapping[str, float],
    *,
    minimum_axis: float = 0.70,
) -> dict[str, Any]:
    required = {
        "behavior",
        "evaluator_calibration",
        "evidence_integrity",
        "coverage",
        "regression",
        "operations",
    }
    missing = sorted(required - set(axes))
    invalid = sorted(name for name, value in axes.items() if not 0 <= float(value) <= 1)
    below = sorted(name for name in required if name in axes and axes[name] < minimum_axis)
    score = sum(float(axes[name]) for name in required if name in axes) / max(1, len(required))
    return {
        "score": round(score, 6),
        "admissible": not missing and not invalid and not below,
        "missing_axes": tuple(missing),
        "invalid_axes": tuple(invalid),
        "below_threshold": tuple(below),
        "minimum_axis": minimum_axis,
        "average_never_overrides_gate": True,
    }
