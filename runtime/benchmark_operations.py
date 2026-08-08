"""Deterministic controls for cold benchmarks and post-run improvement lanes.

This module owns benchmark treatment state.  It deliberately does not execute an
external benchmark, mutate a capability, or promote an improvement candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from pathlib import Path
import statistics
from typing import Any, Iterable, Mapping, Sequence


class BenchmarkLane(str, Enum):
    PREFLIGHT = "preflight"
    COLD = "cold"
    CONTROL = "control"
    ANALYSIS = "analysis"
    IMPROVEMENT = "improvement"
    REGRESSION = "regression"


class BenchmarkFailureClass(str, Enum):
    TASK_REASONING_FAILURE = "task_reasoning_failure"
    IMPLEMENTATION_FAILURE = "implementation_failure"
    VALIDATION_FAILURE = "validation_failure"
    TIMEOUT = "timeout"
    CONTEXT_LIMIT = "context_limit"
    TOOL_FAILURE = "tool_failure"
    CONTAINER_FAILURE = "container_failure"
    DEPENDENCY_FAILURE = "dependency_failure"
    MODEL_PROVIDER_FAILURE = "model_provider_failure"
    PACIFY_X_BOOTSTRAP_FAILURE = "pacify_x_bootstrap_failure"
    HARNESS_FAILURE = "harness_failure"
    ORACLE_AMBIGUOUS = "oracle_ambiguous"
    CONTAMINATION_BLOCK = "contamination_block"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    UNKNOWN = "unknown"


REQUIRED_PROFILE_SECTIONS = (
    "benchmark",
    "agent",
    "model",
    "pacify_x",
    "limits",
    "permissions",
    "retry_policy",
    "environment",
)
NON_GRADED_FAILURES = {
    BenchmarkFailureClass.CONTAINER_FAILURE,
    BenchmarkFailureClass.DEPENDENCY_FAILURE,
    BenchmarkFailureClass.MODEL_PROVIDER_FAILURE,
    BenchmarkFailureClass.PACIFY_X_BOOTSTRAP_FAILURE,
    BenchmarkFailureClass.HARNESS_FAILURE,
    BenchmarkFailureClass.ORACLE_AMBIGUOUS,
    BenchmarkFailureClass.CONTAMINATION_BLOCK,
    BenchmarkFailureClass.RESOURCE_EXHAUSTION,
}


def _stable(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def content_hash(value: object) -> str:
    return hashlib.sha256(_stable(value).encode("utf-8")).hexdigest()


def _enum_value(value: Enum | str) -> str:
    return str(value.value) if isinstance(value, Enum) else str(value)


def _profile_payload(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in profile.items()
        if key not in {"frozen", "frozen_hash", "comparison_hash"}
    }


def _comparison_payload(profile: Mapping[str, Any]) -> dict[str, Any]:
    payload = _profile_payload(profile)
    raw_pacify = payload.get("pacify_x", {})
    pacify = dict(raw_pacify) if isinstance(raw_pacify, Mapping) else {"invalid": True}
    pacify.pop("enabled", None)
    pacify.pop("capabilities", None)
    payload["pacify_x"] = pacify
    payload.pop("run_id", None)
    return payload


def freeze_execution_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    """Return a content-addressed immutable treatment declaration."""
    candidate = dict(profile)
    missing = [section for section in REQUIRED_PROFILE_SECTIONS if section not in candidate]
    if missing:
        raise ValueError("missing profile sections: " + ", ".join(missing))
    if candidate.get("schema_version") != "1.0" or not str(candidate.get("run_id", "")).strip():
        raise ValueError("schema_version 1.0 and a non-empty run_id are required")
    invalid_sections = [
        section
        for section in REQUIRED_PROFILE_SECTIONS
        if not isinstance(candidate.get(section), Mapping)
    ]
    if invalid_sections:
        raise ValueError("profile sections must be objects: " + ", ".join(invalid_sections))
    if not isinstance(candidate["pacify_x"].get("enabled"), bool):
        raise ValueError("pacify_x.enabled must be boolean")
    try:
        BenchmarkLane(_enum_value(candidate["lane"]))
        retry = candidate["retry_policy"]
        max_retries = int(retry["max_retries"])
        retryable = tuple(sorted(set(map(str, retry["retryable_classes"]))))
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid lane or retry policy") from error
    if max_retries < 0:
        raise ValueError("max_retries must be non-negative")
    candidate["retry_policy"] = {
        **dict(retry),
        "max_retries": max_retries,
        "retryable_classes": list(retryable),
    }
    payload = _profile_payload(candidate)
    return {
        **payload,
        "frozen": True,
        "frozen_hash": content_hash(payload),
        "comparison_hash": content_hash(_comparison_payload(payload)),
    }


def verify_frozen_profile(profile: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if profile.get("frozen") is not True:
        reasons.append("profile_not_frozen")
    missing = [section for section in REQUIRED_PROFILE_SECTIONS if section not in profile]
    reasons.extend(f"profile_section_missing:{item}" for item in missing)
    reasons.extend(
        f"profile_section_invalid:{section}"
        for section in REQUIRED_PROFILE_SECTIONS
        if section in profile and not isinstance(profile.get(section), Mapping)
    )
    try:
        BenchmarkLane(_enum_value(profile.get("lane", "")))
    except ValueError:
        reasons.append("lane_invalid")
    payload = _profile_payload(profile)
    if profile.get("frozen_hash") != content_hash(payload):
        reasons.append("frozen_hash_mismatch")
    if profile.get("comparison_hash") != content_hash(_comparison_payload(payload)):
        reasons.append("comparison_hash_mismatch")
    retry = profile.get("retry_policy")
    if not isinstance(retry, Mapping):
        reasons.append("retry_policy_invalid")
    else:
        try:
            if int(retry.get("max_retries", -1)) < 0:
                reasons.append("retry_budget_invalid")
        except (TypeError, ValueError):
            reasons.append("retry_budget_invalid")
        if not isinstance(retry.get("retryable_classes"), list):
            reasons.append("retryable_classes_invalid")
    if profile.get("lane") == BenchmarkLane.COLD.value:
        environment = profile.get("environment", {})
        if not isinstance(environment, Mapping):
            reasons.append("environment_invalid")
        else:
            if environment.get("memory") not in {"disabled", "ephemeral_empty"}:
                reasons.append("cold_memory_not_isolated")
            if environment.get("cache") not in {"disabled", "empty", "ephemeral_empty"}:
                reasons.append("cold_cache_not_isolated")
    return not reasons, tuple(sorted(set(reasons)))


@dataclass(frozen=True, slots=True)
class PreflightDecision:
    scoreable: bool
    failed_checks: tuple[str, ...]
    profile_hash: str | None
    lane: str


def evaluate_preflight(
    profile: Mapping[str, Any],
    checks: Mapping[str, bool],
    *,
    required_checks: Sequence[str] = (
        "harness_ready",
        "oracle_ready",
        "dependencies_ready",
        "permissions_ready",
        "evidence_sink_ready",
    ),
) -> PreflightDecision:
    valid, reasons = verify_frozen_profile(profile)
    failures = list(reasons)
    failures.extend(
        f"preflight_failed:{name}"
        for name in required_checks
        if checks.get(name) is not True
    )
    return PreflightDecision(
        not failures and valid,
        tuple(sorted(set(failures))),
        str(profile.get("frozen_hash")) if valid else None,
        str(profile.get("lane", "unknown")),
    )


@dataclass(frozen=True, slots=True)
class RetryDecision:
    allowed: bool
    reason: str
    remaining: int


def decide_benchmark_retry(
    profile: Mapping[str, Any],
    *,
    completed_attempts: int,
    failure_class: BenchmarkFailureClass | str,
    observed_profile_hash: str,
) -> RetryDecision:
    valid, _ = verify_frozen_profile(profile)
    expected_hash = str(profile.get("frozen_hash", ""))
    if not valid or observed_profile_hash != expected_hash:
        return RetryDecision(False, "treatment_changed", 0)
    if completed_attempts < 1:
        return RetryDecision(False, "completed_attempts_must_be_positive", 0)
    retry = profile["retry_policy"]
    maximum = int(retry["max_retries"])
    remaining = max(0, maximum - (completed_attempts - 1))
    normalized = BenchmarkFailureClass(_enum_value(failure_class)).value
    if normalized not in set(map(str, retry["retryable_classes"])):
        return RetryDecision(False, "failure_class_not_retryable", remaining)
    if completed_attempts > maximum:
        return RetryDecision(False, "retry_budget_exhausted", 0)
    return RetryDecision(True, "retry_admitted_under_frozen_treatment", remaining)


@dataclass(frozen=True, slots=True)
class ContaminationDecision:
    allowed: bool
    reasons: tuple[str, ...]


def evaluate_contamination(
    *,
    lane: BenchmarkLane | str,
    oracle_visibility: str,
    treatment_visibility: str,
    benchmark_informed_changes: Iterable[str] = (),
) -> ContaminationDecision:
    selected = BenchmarkLane(_enum_value(lane))
    reasons: list[str] = []
    if selected is BenchmarkLane.COLD:
        if oracle_visibility not in {"hidden", "post_run_only"}:
            reasons.append("cold_oracle_visible")
        if treatment_visibility == "visible":
            reasons.append("cold_case_visible_to_treatment")
        if tuple(benchmark_informed_changes):
            reasons.append("cold_treatment_benchmark_informed")
    return ContaminationDecision(not reasons, tuple(sorted(set(reasons))))


def matched_control_comparison(
    pacify_on: Mapping[str, Any], pacify_off: Mapping[str, Any]
) -> dict[str, Any]:
    on_valid, on_reasons = verify_frozen_profile(pacify_on)
    off_valid, off_reasons = verify_frozen_profile(pacify_off)
    reasons = [*(f"on:{item}" for item in on_reasons), *(f"off:{item}" for item in off_reasons)]
    if on_valid and off_valid:
        if pacify_on.get("comparison_hash") != pacify_off.get("comparison_hash"):
            reasons.append("treatment_not_matched")
        on_pacify = pacify_on.get("pacify_x", {})
        off_pacify = pacify_off.get("pacify_x", {})
        if not isinstance(on_pacify, Mapping) or on_pacify.get("enabled") is not True:
            reasons.append("on_profile_not_enabled")
        if not isinstance(off_pacify, Mapping) or off_pacify.get("enabled") is not False:
            reasons.append("off_profile_not_disabled")
    return {
        "valid": not reasons,
        "matched": not reasons,
        "comparison_hash": pacify_on.get("comparison_hash") if not reasons else None,
        "reasons": tuple(sorted(set(reasons))),
    }


def admit_test_only_capability(
    *, execution_mode: str, capability_scope: str
) -> tuple[bool, str]:
    if capability_scope != "test_only":
        return True, "normal_capability_scope"
    if execution_mode != "benchmark":
        return False, "test_only_capability_requires_benchmark_execution_mode"
    return True, "test_only_capability_admitted_in_benchmark_context"


def _numeric_summary(values: Iterable[float]) -> dict[str, float | int]:
    samples = tuple(map(float, values))
    if not samples:
        return {"samples": 0}
    return {
        "samples": len(samples),
        "mean": round(statistics.fmean(samples), 6),
        "median": round(statistics.median(samples), 6),
        "standard_deviation": round(statistics.stdev(samples), 6)
        if len(samples) > 1
        else 0.0,
        "min": min(samples),
        "max": max(samples),
    }


def summarize_matched_results(
    treatment_runs: Iterable[Mapping[str, Any]],
    control_runs: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    treatment = tuple(treatment_runs)
    control = tuple(control_runs)
    required = {"task_id", "passed"}
    if any(not required.issubset(item) for item in (*treatment, *control)):
        raise ValueError("every matched result requires task_id and passed")
    treatment_tasks = {str(item["task_id"]) for item in treatment}
    control_tasks = {str(item["task_id"]) for item in control}
    if treatment_tasks != control_tasks or not treatment_tasks:
        raise ValueError("matched result task denominators differ or are empty")
    for task in treatment_tasks:
        treatment_count = sum(str(item["task_id"]) == task for item in treatment)
        control_count = sum(str(item["task_id"]) == task for item in control)
        if treatment_count != control_count:
            raise ValueError(f"matched trial counts differ for task {task}")

    def frequencies(rows: tuple[Mapping[str, Any], ...]) -> dict[str, float]:
        result: dict[str, float] = {}
        for task in sorted({str(item["task_id"]) for item in rows}):
            samples = [item.get("passed") is True for item in rows if str(item["task_id"]) == task]
            result[task] = round(sum(samples) / len(samples), 6)
        return result

    on_frequency, off_frequency = frequencies(treatment), frequencies(control)
    treatment_only = sorted(
        task for task in treatment_tasks if on_frequency[task] > 0 and off_frequency[task] == 0
    )
    control_only = sorted(
        task for task in treatment_tasks if off_frequency[task] > 0 and on_frequency[task] == 0
    )
    on_rate = sum(item.get("passed") is True for item in treatment) / len(treatment)
    off_rate = sum(item.get("passed") is True for item in control) / len(control)
    metrics = {}
    for name in ("quality", "latency", "cost", "tokens", "tool_calls", "wall_time"):
        metrics[name] = {
            "treatment": _numeric_summary(
                float(item[name]) for item in treatment if name in item
            ),
            "control": _numeric_summary(
                float(item[name]) for item in control if name in item
            ),
        }
    return {
        "valid": True,
        "task_count": len(treatment_tasks),
        "treatment_pass_rate": round(on_rate, 6),
        "control_pass_rate": round(off_rate, 6),
        "absolute_pass_delta": round(on_rate - off_rate, 6),
        "relative_pass_improvement": round((on_rate - off_rate) / off_rate, 6)
        if off_rate
        else None,
        "treatment_only_passes": treatment_only,
        "control_only_passes": control_only,
        "common_passes": sorted(
            task for task in treatment_tasks if on_frequency[task] > 0 and off_frequency[task] > 0
        ),
        "common_failures": sorted(
            task for task in treatment_tasks if on_frequency[task] == 0 and off_frequency[task] == 0
        ),
        "per_task": {
            task: {"treatment": on_frequency[task], "control": off_frequency[task]}
            for task in sorted(treatment_tasks)
        },
        "metrics": metrics,
        "infrastructure_errors": {
            "treatment": sum(item.get("infrastructure_error") is True for item in treatment),
            "control": sum(item.get("infrastructure_error") is True for item in control),
        },
        "significance_claimed": False,
    }


def result_claim_labels(
    *,
    matched_control: bool,
    custody_sealed: bool,
    contamination_clear: bool,
    external_environment_matched: bool,
    limitations: Iterable[str] = (),
) -> dict[str, Any]:
    limits = tuple(sorted(set(map(str, limitations))))
    if not custody_sealed or not contamination_clear:
        validity = "RESULT INVALID - DO NOT PUBLISH"
    elif matched_control and not limits:
        validity = "RESULT VALID FOR CONTROLLED PACIFY-X UPLIFT CLAIM"
    else:
        validity = "RESULT PARTIALLY VALID - SEE LIMITATIONS"
    comparable = (
        "DIRECTLY_COMPARABLE"
        if external_environment_matched and not limits
        else "APPROXIMATELY_COMPARABLE"
        if external_environment_matched
        else "NOT_CAUSALLY_COMPARABLE"
    )
    return {
        "valid": validity != "RESULT INVALID - DO NOT PUBLISH",
        "result_validity": validity,
        "external_comparability": comparable,
        "limitations": limits,
    }


def build_custody_record(
    run_id: str,
    artifacts: Mapping[str, bytes | Path],
    aggregate: Mapping[str, Any],
    *,
    cold: bool,
    parent_run_id: str | None = None,
    benchmark_informed: bool = False,
) -> dict[str, Any]:
    """Hash benchmark artifacts without changing them or their source paths."""
    if cold and benchmark_informed:
        raise ValueError("cold benchmark evidence cannot be benchmark-informed")
    rows = []
    for name, source in sorted(artifacts.items()):
        payload = source.read_bytes() if isinstance(source, Path) else bytes(source)
        rows.append({"path": str(name), "sha256": hashlib.sha256(payload).hexdigest()})
    record = {
        "run_id": run_id,
        "cold": cold,
        "artifacts": rows,
        "aggregate": dict(aggregate),
        "sealed": True,
        "parent_run_id": parent_run_id,
        "benchmark_informed": benchmark_informed,
    }
    return {**record, "custody_hash": content_hash(record)}


def classify_failure(
    run_id: str,
    task_id: str,
    contributors: Mapping[BenchmarkFailureClass | str, float],
    evidence: Iterable[str],
) -> dict[str, Any]:
    if not contributors:
        contributors = {BenchmarkFailureClass.UNKNOWN: 0.0}
    normalized = []
    for cause, confidence in contributors.items():
        member = BenchmarkFailureClass(_enum_value(cause))
        value = float(confidence)
        if not 0 <= value <= 1:
            raise ValueError("failure confidence must be between zero and one")
        normalized.append((member, value))
    normalized.sort(key=lambda item: (-item[1], item[0].value))
    primary = normalized[0][0]
    return {
        "run_id": run_id,
        "task_id": task_id,
        "classification": primary.value,
        "graded_failure": primary not in NON_GRADED_FAILURES,
        "contributors": [
            {"cause": cause.value, "confidence": confidence}
            for cause, confidence in normalized
        ],
        "evidence": sorted(set(map(str, evidence))),
    }
