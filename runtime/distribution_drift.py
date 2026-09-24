"""Bounded deterministic distribution-drift metrics used only as evidence."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Iterable

_EPS = 1e-12
_MAX_BINS = 4096


def _sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _distribution(values: Iterable[float], label: str) -> tuple[float, ...]:
    rows = tuple(values)
    if not rows or len(rows) > _MAX_BINS:
        raise ValueError(f"{label} must contain 1..{_MAX_BINS} bins")
    parsed: list[float] = []
    for value in rows:
        if type(value) not in (int, float) or type(value) is bool:
            raise ValueError(f"{label} bins must be numeric")
        number = float(value)
        if not math.isfinite(number) or number < 0:
            raise ValueError(f"{label} bins must be finite and nonnegative")
        parsed.append(number)
    total = sum(parsed)
    if not math.isfinite(total) or total <= 0:
        raise ValueError(f"{label} must have positive total mass")
    return tuple(value / total for value in parsed)


def population_stability_index(expected: Iterable[float], actual: Iterable[float]) -> float:
    p = _distribution(expected, "expected")
    q = _distribution(actual, "actual")
    if len(p) != len(q):
        raise ValueError("expected and actual distributions must have equal length")
    return sum((qi - pi) * math.log((qi + _EPS) / (pi + _EPS)) for pi, qi in zip(p, q))


def jensen_shannon_divergence(expected: Iterable[float], actual: Iterable[float]) -> float:
    p = _distribution(expected, "expected")
    q = _distribution(actual, "actual")
    if len(p) != len(q):
        raise ValueError("expected and actual distributions must have equal length")
    m = tuple((x + y) / 2.0 for x, y in zip(p, q))
    def kl(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        return sum(x * math.log2((x + _EPS) / (y + _EPS)) for x, y in zip(left, right) if x > 0)
    value = 0.5 * kl(p, m) + 0.5 * kl(q, m)
    return max(0.0, min(1.0, value))


@dataclass(frozen=True, slots=True)
class DriftFinding:
    metric: str
    psi: float
    jsd: float
    severity: str
    propose_learning_candidate: bool
    evidence_sha256: str
    authority_granted: bool = False


def assess_distribution_drift(metric: str, expected: Iterable[float], actual: Iterable[float], *, psi_warn: float = 0.1, psi_high: float = 0.25, jsd_high: float = 0.1) -> DriftFinding:
    if type(metric) is not str or not metric.strip() or len(metric.encode()) > 256:
        raise ValueError("metric must be bounded nonempty text")
    thresholds = (psi_warn, psi_high, jsd_high)
    if any(type(value) not in (int, float) or type(value) is bool or not math.isfinite(float(value)) or float(value) < 0 for value in thresholds):
        raise ValueError("drift thresholds must be finite and nonnegative")
    if float(psi_warn) > float(psi_high):
        raise ValueError("psi_warn must not exceed psi_high")
    p = _distribution(expected, "expected"); q = _distribution(actual, "actual")
    if len(p) != len(q):
        raise ValueError("expected and actual distributions must have equal length")
    psi = population_stability_index(p, q); jsd = jensen_shannon_divergence(p, q)
    if psi >= float(psi_high) or jsd >= float(jsd_high): severity = "high"
    elif psi >= float(psi_warn): severity = "medium"
    else: severity = "low"
    payload = {"metric": metric.strip(), "expected": p, "actual": q, "psi": psi, "jsd": jsd, "severity": severity, "thresholds": {"psi_warn": float(psi_warn), "psi_high": float(psi_high), "jsd_high": float(jsd_high)}}
    return DriftFinding(metric.strip(), psi, jsd, severity, severity == "high", _sha(payload), False)
