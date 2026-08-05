"""Integrated evidence, trust, drift, identity, benchmark, and runtime-health controls."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


INJECTION_MARKERS = (
    "ignore previous",
    "override system",
    "reveal secret",
    "disable policy",
    "bypass approval",
    "expand permissions",
    "hidden instruction",
)
PASSPORT_COMPONENTS = (
    "identity",
    "memory",
    "knowledge",
    "reasoning",
    "correction",
    "evidence",
    "health",
    "certification",
    "drift",
    "version",
)


def _stable(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class TrustEvidence:
    memory_id: str
    evidence_current: bool
    current_revision: bool
    telemetry_healthy: bool
    graph_consistent: bool
    correction_clear: bool
    provenance_resolved: bool
    confidence: float
    retrieved_text: str
    contradictions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TrustDecision:
    memory_id: str
    decision: str
    trust_score: float
    reasons: tuple[str, ...]
    gate_sequence: tuple[str, ...]
    evidence_sha256: str


def evaluate_memory_trust(value: TrustEvidence) -> TrustDecision:
    reasons = []
    checks = {
        "evidence": value.evidence_current,
        "current_revision": value.current_revision,
        "telemetry": value.telemetry_healthy,
        "knowledge_graph": value.graph_consistent,
        "correction": value.correction_clear,
        "provenance": value.provenance_resolved,
    }
    reasons.extend(f"{name}_failed" for name, passed in checks.items() if not passed)
    if not 0 <= value.confidence <= 1:
        reasons.append("confidence_out_of_range")
    if value.confidence < 0.6:
        reasons.append("confidence_below_trust_threshold")
    if value.contradictions:
        reasons.append("contradictions_unresolved")
    if any(marker in value.retrieved_text.casefold() for marker in INJECTION_MARKERS):
        reasons.append("memory_poison_indicator")
    score = max(0.0, min(1.0, value.confidence * sum(checks.values()) / len(checks)))
    return TrustDecision(
        value.memory_id,
        "use" if not reasons else "quarantine",
        round(score, 6),
        tuple(sorted(reasons)),
        (
            "retrieve",
            "evidence",
            "current_revision",
            "telemetry",
            "knowledge_graph",
            "confidence",
            "correction",
            "use",
        ),
        _stable(asdict(value)),
    )


@dataclass(frozen=True, slots=True)
class IdentityBaseline:
    runtime_id: str
    model_id: str
    model_version: str
    persona_id: str
    policy_sha256: str


def validate_identity(
    expected: IdentityBaseline, observed: IdentityBaseline
) -> dict[str, object]:
    mismatches = tuple(
        name
        for name in asdict(expected)
        if getattr(expected, name) != getattr(observed, name)
    )
    return {
        "decision": "valid" if not mismatches else "drifted",
        "mismatches": mismatches,
        "expected_sha256": _stable(asdict(expected)),
        "observed_sha256": _stable(asdict(observed)),
    }


def validate_personality(
    baseline: Mapping[str, float],
    observed: Mapping[str, float],
    *,
    tolerance: float = 0.15,
) -> dict[str, object]:
    if not 0 <= tolerance <= 1:
        raise ValueError("personality tolerance must be between zero and one")
    missing = tuple(sorted(set(baseline) - set(observed)))
    drift = tuple(
        sorted(
            name
            for name in set(baseline) & set(observed)
            if abs(float(baseline[name]) - float(observed[name])) > tolerance
        )
    )
    return {
        "decision": "valid" if not missing and not drift else "drifted",
        "missing_traits": missing,
        "drifted_traits": drift,
        "baseline_sha256": _stable(baseline),
        "observed_sha256": _stable(observed),
    }


@dataclass(frozen=True, slots=True)
class DriftReport:
    decision: str
    drift_types: tuple[str, ...]
    scores: Mapping[str, float]
    threshold: float


def detect_runtime_drift(
    baseline: Mapping[str, Sequence[float]],
    observed: Mapping[str, Sequence[float]],
    *,
    threshold: float = 0.2,
) -> DriftReport:
    if not 0 <= threshold <= 1:
        raise ValueError("drift threshold must be between zero and one")
    names = ("behavior", "knowledge", "reasoning", "prompt", "memory")
    scores = {}
    for name in names:
        left = tuple(map(float, baseline.get(name, ())))
        right = tuple(map(float, observed.get(name, ())))
        if not left or len(left) != len(right):
            scores[name] = 1.0
            continue
        scores[name] = round(
            sum(abs(a - b) for a, b in zip(left, right)) / len(left), 6
        )
    drift = tuple(name for name in names if scores[name] > threshold)
    return DriftReport(
        "within_threshold" if not drift else "drifted", drift, scores, threshold
    )


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    case_id: str
    prompt: str
    expected: str
    match: str = "exact"


def run_golden_benchmarks(
    cases: Iterable[BenchmarkCase],
    runner: Callable[[str], str],
) -> dict[str, object]:
    results = []
    for case in cases:
        try:
            actual = runner(case.prompt)
            passed = (
                actual == case.expected
                if case.match == "exact"
                else case.expected in actual
                if case.match == "contains"
                else False
            )
            error = None if passed else "output_mismatch"
        except Exception as exception:
            actual = ""
            passed = False
            error = type(exception).__name__
        results.append(
            {
                "case_id": case.case_id,
                "passed": passed,
                "error": error,
                "actual_sha256": hashlib.sha256(actual.encode()).hexdigest(),
                "expected_sha256": hashlib.sha256(case.expected.encode()).hexdigest(),
            }
        )
    passed = sum(item["passed"] for item in results)
    return {
        "decision": "passed" if results and passed == len(results) else "failed",
        "passed": passed,
        "total": len(results),
        "results": tuple(results),
    }


def cognitive_ekg(metrics: Mapping[str, float]) -> dict[str, object]:
    thresholds = {
        "evidence_coverage": (0.8, "minimum"),
        "trusted_memory_ratio": (0.7, "minimum"),
        "correction_success": (0.9, "minimum"),
        "poison_rate": (0.01, "maximum"),
        "drift_score": (0.2, "maximum"),
        "benchmark_pass_rate": (0.95, "minimum"),
    }
    abnormalities = []
    for name, (limit, direction) in thresholds.items():
        value = float(metrics.get(name, -1))
        if (
            value < 0
            or (direction == "minimum" and value < limit)
            or (direction == "maximum" and value > limit)
        ):
            abnormalities.append(name)
    return {
        "health": "healthy" if not abnormalities else "degraded",
        "abnormalities": tuple(sorted(abnormalities)),
        "metrics_sha256": _stable(metrics),
        "hidden_reasoning_collected": False,
    }


def build_runtime_passport(
    components: Mapping[str, Mapping[str, object]],
    *,
    trust_decisions: Iterable[TrustDecision],
    drift: DriftReport,
    benchmarks: Mapping[str, object],
) -> dict[str, object]:
    missing = tuple(name for name in PASSPORT_COMPONENTS if not components.get(name))
    untrusted = tuple(
        sorted(item.memory_id for item in trust_decisions if item.decision != "use")
    )
    reasons = []
    if missing:
        reasons.append("passport_components_missing")
    if untrusted:
        reasons.append("untrusted_memory_present")
    if drift.decision != "within_threshold":
        reasons.append("runtime_drift_detected")
    if benchmarks.get("decision") != "passed":
        reasons.append("golden_benchmarks_failed")
    passport = {
        "schema_version": "1.0",
        "components": {
            name: dict(components.get(name, {})) for name in PASSPORT_COMPONENTS
        },
        "untrusted_memory_ids": untrusted,
        "drift": asdict(drift),
        "benchmarks": dict(benchmarks),
        "decision": "certified" if not reasons else "degraded",
        "reasons": tuple(reasons),
    }
    return {**passport, "passport_sha256": _stable(passport)}


class BlackBoxRecorder:
    """Append-only redacted runtime event recorder; never stores prompts, responses, or secrets."""

    PROHIBITED = {
        "raw_prompt",
        "raw_response",
        "prompt",
        "response",
        "secret",
        "token",
        "credential",
    }

    def __init__(self, root: Path, *, runtime_id: str) -> None:
        self.root = root.resolve()
        self.runtime_id = runtime_id

    def record(
        self,
        event_type: str,
        payload: Mapping[str, object],
        *,
        evidence_refs: Sequence[str],
    ) -> str:
        prohibited = sorted(key for key in payload if key.casefold() in self.PROHIBITED)
        if prohibited:
            raise ValueError("prohibited black-box fields: " + ", ".join(prohibited))
        existing = tuple(sorted(self.root.glob("*.json"))) if self.root.is_dir() else ()
        sequence = len(existing) + 1
        record = {
            "schema_version": "1.0",
            "sequence": sequence,
            "runtime_id": self.runtime_id,
            "event_type": event_type,
            "payload_hash": _stable(payload),
            "evidence_refs": list(evidence_refs),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        path = self.root / f"{sequence:06d}-{event_type}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
        return path.as_posix()


def verify_reality(
    claims: Iterable[Mapping[str, object]],
    *,
    current_evidence_ids: Iterable[str],
) -> dict[str, object]:
    current = set(map(str, current_evidence_ids))
    unsupported = []
    contradicted = []
    for claim in claims:
        claim_id = str(claim.get("id", "unnamed"))
        evidence = set(map(str, claim.get("evidence_refs", ())))
        if not evidence or not evidence <= current:
            unsupported.append(claim_id)
        if claim.get("contradicted") is True:
            contradicted.append(claim_id)
    return {
        "decision": "reality_supported"
        if not unsupported and not contradicted
        else "not_supported",
        "unsupported_claims": tuple(sorted(unsupported)),
        "contradicted_claims": tuple(sorted(contradicted)),
        "anti_bs_internal_control": True,
    }
