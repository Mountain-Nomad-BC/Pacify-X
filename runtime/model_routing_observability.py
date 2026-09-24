"""Deterministic route observability, drift, collapse, and benchmark evidence.

Outputs are evidence only.  They cannot edit routing policy or promote learned
state; callers must pass them through the existing learning/promotion gates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Mapping, Sequence

from .json_io import validate_json_value

MAX_OUTCOMES = 100_000


def _canonical(value: object) -> bytes:
    validate_json_value(value, max_nodes=500_000)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def content_sha256(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _bounded_text(value: object, name: str, *, maximum: int = 256) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{name} must be bounded nonempty text")
    return value.strip()


def _finite(value: object, name: str, *, minimum: float | None = None, maximum: float | None = None) -> float:
    if type(value) not in (int, float) or type(value) is bool:
        raise ValueError(f"{name} must be finite numeric evidence")
    number = float(value)
    if not math.isfinite(number) or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        raise ValueError(f"{name} is outside its admitted range")
    return number


def _valid_sha(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True, slots=True)
class RouteOutcome:
    fixture_id: str
    domain: str
    policy_sha256: str
    ranking: tuple[str, ...]
    primary_model_id: str
    challenger_model_id: str | None
    verified_success: bool
    latency_ms: float
    remote_cost: float
    local_completion: bool
    feature_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _bounded_text(self.fixture_id, "route fixture_id", maximum=512)
        _bounded_text(self.domain, "route domain")
        if not _valid_sha(self.policy_sha256):
            raise ValueError("route outcome policy_sha256 must be lowercase SHA-256")
        if type(self.ranking) is not tuple or not 1 <= len(self.ranking) <= 64:
            raise ValueError("route outcome ranking must be bounded and nonempty")
        for route_id in self.ranking:
            _bounded_text(route_id, "route ranking identity")
        if len(set(self.ranking)) != len(self.ranking):
            raise ValueError("route ranking identities must be distinct")
        _bounded_text(self.primary_model_id, "route primary_model_id")
        if self.primary_model_id not in self.ranking:
            raise ValueError("route primary must appear in ranking")
        if self.challenger_model_id is not None:
            _bounded_text(self.challenger_model_id, "route challenger_model_id")
            if self.challenger_model_id not in self.ranking or self.challenger_model_id == self.primary_model_id:
                raise ValueError("route challenger must be a distinct ranked model")
        if type(self.verified_success) is not bool or type(self.local_completion) is not bool:
            raise ValueError("route outcome booleans must be typed")
        _finite(self.latency_ms, "route latency_ms", minimum=0.0, maximum=1e12)
        _finite(self.remote_cost, "route remote_cost", minimum=0.0, maximum=1e12)
        if type(self.feature_ids) is not tuple or len(self.feature_ids) > 128:
            raise ValueError("route feature IDs must be bounded and immutable")
        for feature in self.feature_ids:
            _bounded_text(feature, "route feature_id")


def _distribution(outcomes: Sequence[RouteOutcome]) -> dict[str, float]:
    counts = Counter(row.primary_model_id for row in outcomes)
    total = float(sum(counts.values()))
    return {key: counts[key] / total for key in sorted(counts)} if total else {}


def normalized_entropy(distribution: Mapping[str, float]) -> float:
    if type(distribution) is not dict:
        distribution = dict(distribution)
    values = []
    for key, value in distribution.items():
        _bounded_text(key, "route distribution key")
        number = _finite(value, "route distribution weight", minimum=0.0)
        if number > 0:
            values.append(number)
    if len(values) <= 1:
        return 0.0
    total = sum(values)
    ps = [value / total for value in values]
    entropy = -sum(p * math.log2(p) for p in ps)
    return round(entropy / math.log2(len(ps)), 9)


def effective_route_count(distribution: Mapping[str, float]) -> float:
    values = [_finite(v, "route distribution weight", minimum=0.0) for v in distribution.values()]
    positive = [v for v in values if v > 0]
    if not positive:
        return 0.0
    total = sum(positive)
    ps = [v / total for v in positive]
    return round(2 ** (-sum(p * math.log2(p) for p in ps)), 9)


def jensen_shannon_bits(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    keys = sorted(set(left) | set(right))
    if not keys:
        return 0.0
    def normalize(values: Mapping[str, float]) -> dict[str, float]:
        rows = {key: _finite(values.get(key, 0.0), "route distribution value", minimum=0.0) for key in keys}
        total = sum(rows.values())
        return {key: (rows[key] / total if total else 0.0) for key in keys}
    a, b = normalize(left), normalize(right)
    middle = {key: (a[key] + b[key]) / 2.0 for key in keys}
    def kl(p: Mapping[str, float], q: Mapping[str, float]) -> float:
        return sum(p[key] * math.log2(p[key] / q[key]) for key in keys if p[key] > 0)
    return round((kl(a, middle) + kl(b, middle)) / 2.0, 9)


def top_k_overlap(left: Sequence[str], right: Sequence[str], k: int) -> float:
    if type(k) is not int or k < 1 or k > 64:
        raise ValueError("top-k overlap requires k in 1..64")
    denominator = min(k, max(len(left), len(right)))
    if denominator == 0:
        return 1.0
    return round(len(set(left[:k]) & set(right[:k])) / denominator, 9)


def feature_affinity(outcomes: Iterable[RouteOutcome]) -> dict[str, dict[str, dict[str, float | int]]]:
    rows: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for index, outcome in enumerate(outcomes):
        if index >= MAX_OUTCOMES or type(outcome) is not RouteOutcome:
            raise ValueError("route outcome budget/type exceeded")
        for feature in sorted(set(outcome.feature_ids)):
            row = rows[(feature, outcome.primary_model_id)]
            row[0] += int(outcome.verified_success)
            row[1] += 1
    result: dict[str, dict[str, dict[str, float | int]]] = defaultdict(dict)
    for (feature, route), (successes, observations) in sorted(rows.items()):
        result[feature][route] = {
            "successes": successes,
            "observations": observations,
            "smoothed_success": round((successes + 1.0) / (observations + 2.0), 9),
        }
    return dict(result)


def route_transition_counts(sequences: Iterable[Sequence[str]]) -> dict[str, int]:
    counts: Counter[tuple[str, str]] = Counter()
    for index, sequence in enumerate(sequences):
        if index >= MAX_OUTCOMES or isinstance(sequence, (str, bytes)) or len(sequence) > 128:
            raise ValueError("route transition sequence budget exceeded")
        normalized = tuple(_bounded_text(item, "route transition identity") for item in sequence)
        for source, target in zip(normalized, normalized[1:]):
            counts[(source, target)] += 1
    return {f"{source}->{target}": count for (source, target), count in sorted(counts.items())}


def collapse_evidence(
    outcomes: Sequence[RouteOutcome],
    *,
    max_top1_share: float = 0.90,
    min_normalized_entropy: float = 0.20,
) -> dict[str, object]:
    if not outcomes or len(outcomes) > MAX_OUTCOMES or any(type(row) is not RouteOutcome for row in outcomes):
        raise ValueError("bounded route outcomes are required for collapse evidence")
    maximum = _finite(max_top1_share, "max_top1_share", minimum=0.0, maximum=1.0)
    minimum = _finite(min_normalized_entropy, "min_normalized_entropy", minimum=0.0, maximum=1.0)
    distribution = _distribution(outcomes)
    top1 = max(distribution.values(), default=0.0)
    entropy = normalized_entropy(distribution)
    reasons = []
    if top1 > maximum:
        reasons.append("top1_concentration")
    if len(distribution) > 1 and entropy < minimum:
        reasons.append("low_route_entropy")
    body = {
        "schema_version": "px.model-route-collapse-evidence/1.0",
        "observations": len(outcomes),
        "route_distribution": distribution,
        "top1_share": round(top1, 9),
        "normalized_entropy": entropy,
        "effective_route_count": effective_route_count(distribution),
        "review_required": bool(reasons),
        "review_reasons": reasons,
        "authority_granted": False,
    }
    return {**body, "evidence_sha256": content_sha256(body)}


def benchmark_route_outcomes(
    incumbent: Sequence[RouteOutcome],
    candidate: Sequence[RouteOutcome],
    *,
    fixture_sha256: str,
    domain_floors: Mapping[str, float],
    materiality: Mapping[str, float],
    max_js_bits: float = 0.20,
    min_top1_agreement: float = 0.80,
    min_top3_overlap: float = 0.70,
    max_latency_ratio: float | None = None,
) -> dict[str, object]:
    """Compare a candidate route generation with the matched incumbent fixtures."""

    if not _valid_sha(fixture_sha256):
        raise ValueError("fixture_sha256 must be lowercase SHA-256")
    if not incumbent or not candidate or len(incumbent) != len(candidate) or len(incumbent) > MAX_OUTCOMES:
        raise ValueError("matched bounded incumbent/candidate outcome sets are required")
    incumbent_map = {row.fixture_id: row for row in incumbent if type(row) is RouteOutcome}
    candidate_map = {row.fixture_id: row for row in candidate if type(row) is RouteOutcome}
    if len(incumbent_map) != len(incumbent) or len(candidate_map) != len(candidate) or set(incumbent_map) != set(candidate_map):
        raise ValueError("benchmark outcomes require unique matched fixture identities")
    if len({row.policy_sha256 for row in incumbent}) != 1 or len({row.policy_sha256 for row in candidate}) != 1:
        raise ValueError("each benchmark side must bind one route-policy generation")
    if next(iter({row.policy_sha256 for row in incumbent})) == next(iter({row.policy_sha256 for row in candidate})):
        raise ValueError("candidate and incumbent policy generations must be distinct")
    floors: dict[str, float] = {}
    if type(domain_floors) is not dict or len(domain_floors) > 128:
        raise ValueError("domain_floors must be a bounded object")
    for domain, value in sorted(domain_floors.items()):
        floors[_bounded_text(domain, "domain floor identity")] = _finite(value, "domain floor", minimum=0.0, maximum=1.0)
    material_keys = {"min_quality_delta", "min_latency_improvement_ratio", "min_remote_cost_reduction_ratio", "min_local_completion_delta"}
    if type(materiality) is not dict or set(materiality) != material_keys:
        raise ValueError("benchmark materiality must declare all required dimensions")
    material = {key: _finite(value, f"materiality {key}", minimum=0.0, maximum=1.0) for key, value in materiality.items()}
    if not any(value > 0 for value in material.values()):
        raise ValueError("benchmark materiality must require at least one nonzero gain")
    max_js = _finite(max_js_bits, "max_js_bits", minimum=0.0, maximum=1.0)
    min_top1 = _finite(min_top1_agreement, "min_top1_agreement", minimum=0.0, maximum=1.0)
    min_top3 = _finite(min_top3_overlap, "min_top3_overlap", minimum=0.0, maximum=1.0)
    if max_latency_ratio is not None:
        max_latency_ratio = _finite(max_latency_ratio, "max_latency_ratio", minimum=1.0, maximum=1000.0)

    ids = sorted(incumbent_map)
    old = [incumbent_map[key] for key in ids]
    new = [candidate_map[key] for key in ids]
    for before, after in zip(old, new):
        if before.domain != after.domain:
            raise ValueError("matched fixtures cannot change benchmark domain")
    old_dist, new_dist = _distribution(old), _distribution(new)
    top1 = sum(1 for a, b in zip(old, new) if a.primary_model_id == b.primary_model_id) / len(ids)
    top3 = sum(top_k_overlap(a.ranking, b.ranking, 3) for a, b in zip(old, new)) / len(ids)
    old_success = sum(row.verified_success for row in old) / len(old)
    new_success = sum(row.verified_success for row in new) / len(new)
    old_cost = sum(row.remote_cost for row in old)
    new_cost = sum(row.remote_cost for row in new)
    old_local = sum(row.local_completion for row in old) / len(old)
    new_local = sum(row.local_completion for row in new) / len(new)
    old_lat = sorted(row.latency_ms for row in old)
    new_lat = sorted(row.latency_ms for row in new)
    p95_index = max(0, math.ceil(0.95 * len(ids)) - 1)
    old_p95, new_p95 = old_lat[p95_index], new_lat[p95_index]

    domains = sorted(set(row.domain for row in new))
    domain_scores: dict[str, float] = {}
    failed_floors: list[str] = []
    for domain in domains:
        rows = [row for row in new if row.domain == domain]
        score = sum(row.verified_success for row in rows) / len(rows)
        domain_scores[domain] = round(score, 9)
        if domain in floors and score < floors[domain]:
            failed_floors.append(domain)
    missing_fixture_domains = sorted(set(floors) - set(domains))
    missing_floor_definitions = sorted(set(domains) - set(floors))
    failed_floors.extend(f"missing_fixture:{domain}" for domain in missing_fixture_domains)
    failed_floors.extend(f"missing_floor:{domain}" for domain in missing_floor_definitions)

    js = jensen_shannon_bits(old_dist, new_dist)
    top1 = round(top1, 9)
    top3 = round(top3, 9)
    review_reasons: list[str] = []
    if js > max_js:
        review_reasons.append("distribution_drift")
    if top1 < min_top1:
        review_reasons.append("top1_route_drift")
    if top3 < min_top3:
        review_reasons.append("top3_route_drift")
    if failed_floors:
        review_reasons.append("domain_floor")
    if max_latency_ratio is not None and old_p95 > 0 and new_p95 / old_p95 > max_latency_ratio:
        review_reasons.append("latency_budget")

    # Complexity tax: the evaluation manifest declares what "material" means.
    # Tiny floating-point movement must not qualify a more complex fabric.
    quality_gain = new_success - old_success
    latency_gain_ratio = ((old_p95 - new_p95) / old_p95) if old_p95 > 0 else 0.0
    cost_gain_ratio = ((old_cost - new_cost) / old_cost) if old_cost > 0 else 0.0
    local_gain = new_local - old_local
    material_gain = any((
        material["min_quality_delta"] > 0 and quality_gain >= material["min_quality_delta"],
        material["min_latency_improvement_ratio"] > 0 and latency_gain_ratio >= material["min_latency_improvement_ratio"] and new_success >= old_success,
        material["min_remote_cost_reduction_ratio"] > 0 and cost_gain_ratio >= material["min_remote_cost_reduction_ratio"] and new_success >= old_success,
        material["min_local_completion_delta"] > 0 and local_gain >= material["min_local_completion_delta"] and new_success >= old_success,
    ))
    complexity_passed = material_gain and not failed_floors
    if not material_gain:
        review_reasons.append("no_material_gain")

    incumbent_domain_scores: dict[str, float] = {}
    for domain in sorted(set(row.domain for row in old)):
        rows = [row for row in old if row.domain == domain]
        incumbent_domain_scores[domain] = round(sum(row.verified_success for row in rows) / len(rows), 9)

    body = {
        "schema_version": "px.model-route-benchmark/1.0",
        "fixture_sha256": fixture_sha256,
        "incumbent_policy_sha256": old[0].policy_sha256,
        "candidate_policy_sha256": new[0].policy_sha256,
        "fixture_count": len(ids),
        "top1_agreement": top1,
        "top3_overlap": top3,
        "jensen_shannon_bits": js,
        "incumbent_normalized_entropy": normalized_entropy(old_dist),
        "candidate_normalized_entropy": normalized_entropy(new_dist),
        "candidate_effective_route_count": effective_route_count(new_dist),
        "incumbent_verified_success": round(old_success, 9),
        "candidate_verified_success": round(new_success, 9),
        "quality_delta": round(new_success - old_success, 9),
        "incumbent_p95_latency_ms": old_p95,
        "candidate_p95_latency_ms": new_p95,
        "p95_latency_delta_ms": round(new_p95 - old_p95, 9),
        "incumbent_remote_cost": round(old_cost, 9),
        "candidate_remote_cost": round(new_cost, 9),
        "remote_cost_delta": round(new_cost - old_cost, 9),
        "incumbent_local_completion": round(old_local, 9),
        "candidate_local_completion": round(new_local, 9),
        "local_completion_delta": round(new_local - old_local, 9),
        "incumbent_domain_scores": incumbent_domain_scores,
        "candidate_domain_scores": domain_scores,
        "domain_floors": floors,
        "materiality": material,
        "latency_improvement_ratio": round(latency_gain_ratio, 9),
        "remote_cost_reduction_ratio": round(cost_gain_ratio, 9),
        "failed_domain_floors": sorted(failed_floors),
        "review_required": bool(review_reasons),
        "review_reasons": sorted(review_reasons),
        "complexity_tax_passed": complexity_passed,
        "promotion_candidate": complexity_passed and not failed_floors,
        "authority_granted": False,
        "auto_promotion_allowed": False,
    }
    return {**body, "evidence_sha256": content_sha256(body)}
