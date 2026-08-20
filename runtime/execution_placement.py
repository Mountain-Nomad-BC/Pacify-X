"""Vendor-neutral, baseline-first execution placement decisions.

Placement recommendations never execute a migration.  The current placement is
always a candidate, hard gates fail closed, boundary costs are included in total
system score, and promotion requires separately hashed benchmark and rollback
evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4


MODES = {"language_runtime", "deployment_platform", "database_storage"}
CLASSES = {
    "language_runtime": {"host_language", "native_library", "ffi_extension", "compiled_worker", "subprocess", "service", "jit_aot", "gpu_accelerator"},
    "deployment_platform": {"local_process", "container", "managed_container", "serverless_function", "serverless_container", "vm", "kubernetes", "batch", "queue_worker", "edge", "scheduled_job", "hybrid"},
    "database_storage": {"relational", "key_value", "document", "graph", "vector", "time_series", "object_blob", "cache", "queue_log", "embedded", "search_index", "hybrid_projection"},
}
DEFAULT_WEIGHTS = {"correctness": 0.30, "latency": 0.17, "throughput": 0.12, "operability": 0.12, "portability": 0.08, "cost": 0.08, "maintainability": 0.08, "reversibility": 0.05}


def _hash(value: object) -> str:
    rendered = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _valid_hash(value: object) -> bool:
    text = str(value)
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _bounded_score(value: object, label: str) -> float:
    score = float(value)
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError(f"{label} must be finite and between zero and one")
    return score


def decide_placement(
    *,
    mode: str,
    candidates: Sequence[Mapping[str, Any]],
    baseline_sha256: str,
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    minimum_improvement: float = 0.05,
) -> dict[str, Any]:
    if mode not in MODES or not _valid_hash(baseline_sha256):
        raise ValueError("placement mode or baseline hash is invalid")
    if not 0 <= minimum_improvement <= 1:
        raise ValueError("minimum improvement must be between zero and one")
    normalized_weights = {str(key): _bounded_score(value, f"weight:{key}") for key, value in weights.items()}
    if not normalized_weights or sum(normalized_weights.values()) <= 0:
        raise ValueError("at least one positive placement weight is required")
    current = [candidate for candidate in candidates if candidate.get("keep_current") is True]
    if len(current) != 1:
        raise ValueError("exactly one keep_current candidate is required")
    rows = []
    ids = set()
    for candidate in candidates:
        identifier = str(candidate.get("id", "")).strip()
        candidate_class = str(candidate.get("class", "")).strip()
        if not identifier or identifier in ids or candidate_class not in CLASSES[mode]:
            raise ValueError("candidate IDs must be unique and classes must match the placement mode")
        ids.add(identifier)
        scores = candidate.get("scores")
        gates = candidate.get("gates")
        boundary = candidate.get("boundary_costs")
        if not isinstance(scores, Mapping) or not isinstance(gates, Mapping) or not isinstance(boundary, Mapping):
            raise ValueError("candidate scores, gates, and boundary costs are required")
        unknown_scores = set(scores) - set(normalized_weights)
        if unknown_scores:
            raise ValueError("candidate has unweighted scores: " + ", ".join(sorted(unknown_scores)))
        score_values = {key: _bounded_score(scores.get(key, 0), f"score:{identifier}:{key}") for key in normalized_weights}
        boundary_values = {str(key): _bounded_score(value, f"boundary:{identifier}:{key}") for key, value in boundary.items()}
        required_gates = ("compatible", "correctness", "rollback_ready", "baseline_available")
        eligible = all(gates.get(gate) is True for gate in required_gates)
        weighted = sum(score_values[key] * normalized_weights[key] for key in normalized_weights) / sum(normalized_weights.values())
        boundary_penalty = sum(boundary_values.values()) / max(1, len(boundary_values))
        total = weighted - boundary_penalty
        rows.append({"id": identifier, "class": candidate_class, "keep_current": bool(candidate.get("keep_current")), "eligible": eligible, "failed_gates": [gate for gate in required_gates if gates.get(gate) is not True], "weighted_benefit": round(weighted, 9), "boundary_penalty": round(boundary_penalty, 9), "total_system_score": round(total, 9), "scores": score_values, "boundary_costs": boundary_values})
    rows.sort(key=lambda item: (-item["total_system_score"], item["id"]))
    current_row = next(row for row in rows if row["keep_current"])
    eligible = [row for row in rows if row["eligible"]]
    best = eligible[0] if eligible else current_row
    selected = best if best["id"] == current_row["id"] or best["total_system_score"] >= current_row["total_system_score"] + minimum_improvement else current_row
    recommendation = "keep_current" if selected["id"] == current_row["id"] else "bounded_prototype"
    decision = {
        "schema_version": "px.execution-placement-decision/1.0",
        "mode": mode,
        "baseline_sha256": baseline_sha256,
        "weights": dict(sorted(normalized_weights.items())),
        "minimum_improvement": minimum_improvement,
        "candidates": rows,
        "selected_candidate": selected["id"],
        "current_candidate": current_row["id"],
        "recommendation": recommendation,
        "promotion_tier": 0 if recommendation == "keep_current" else 1,
        "migration_authorized": False,
        "provider_selected": False,
        "requires_benchmark_before_promotion": True,
    }
    return {**decision, "decision_sha256": _hash(decision)}


def promotion_gate(
    decision: Mapping[str, Any],
    *,
    after_benchmark_sha256: str,
    rollback_test_sha256: str,
    boundary_validation_sha256: str,
    correctness_passed: bool,
    improvement_passed: bool,
    rollback_passed: bool,
    partial_units: Sequence[str] = (),
) -> dict[str, Any]:
    hashes_valid = all(_valid_hash(value) for value in (decision.get("decision_sha256"), decision.get("baseline_sha256"), after_benchmark_sha256, rollback_test_sha256, boundary_validation_sha256))
    candidate_selected = decision.get("recommendation") == "bounded_prototype" and decision.get("selected_candidate") != decision.get("current_candidate")
    gates = {"candidate_selected": candidate_selected, "hashes_valid": hashes_valid, "correctness": correctness_passed, "improvement": improvement_passed, "rollback": rollback_passed}
    passed = all(gates.values())
    record = {
        "schema_version": "px.execution-placement-promotion/1.0",
        "decision_sha256": decision.get("decision_sha256"),
        "selected_candidate": decision.get("selected_candidate"),
        "gates": gates,
        "evidence_sha256": sorted([after_benchmark_sha256, rollback_test_sha256, boundary_validation_sha256]),
        "partial_units": sorted(set(map(str, partial_units))),
        "passed": passed,
        "promotion_tier": 3 if passed and partial_units else 2 if passed else int(decision.get("promotion_tier", 0)),
        "production_authorized": False,
        "rollback_candidate": decision.get("current_candidate"),
    }
    return {**record, "promotion_sha256": _hash(record)}


CPU_AUTHORITY_KINDS = {"filesystem_io", "database", "serialization", "cleanup_safety", "destructive_decision"}


def observe_workload(
    *,
    workload_id: str,
    workload_kind: str,
    current_placement: str,
    source_sha256: str,
    scheduler_snapshot: Mapping[str, Any],
    before_benchmark: Mapping[str, Any],
    boundary_contract_sha256: str,
    rollback_artifact_sha256: str,
    hardware_route: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind placement scoring to an observed workload and its live owners."""
    required_hashes = (
        source_sha256,
        before_benchmark.get("custody_hash"),
        boundary_contract_sha256,
        rollback_artifact_sha256,
    )
    if (
        not workload_id.strip()
        or not workload_kind.strip()
        or not current_placement.strip()
        or not all(_valid_hash(value) for value in required_hashes)
    ):
        raise ValueError("observed workload requires identity and complete hashed evidence")
    if scheduler_snapshot.get("schema_version") != "px.runtime-work-plane/1.0":
        raise ValueError("placement observation requires the canonical runtime scheduler snapshot")
    if before_benchmark.get("sealed") is not True:
        raise ValueError("before benchmark must be sealed by the benchmark custody owner")
    selected_device = str(
        hardware_route.get("selected_device") or hardware_route.get("device") or ""
    )
    actual_device = str(hardware_route.get("actual_device") or "")
    if selected_device not in {"cpu", "cuda"} or actual_device not in {"cpu", "cuda"}:
        raise ValueError("observed workload requires explicit selected and actual device telemetry")
    route_fallback = bool(hardware_route.get("fallback"))
    if route_fallback != (selected_device != actual_device):
        raise ValueError("hardware fallback telemetry is internally inconsistent")
    if actual_device == "cuda" and hardware_route.get("correctness_passed") is not True:
        raise ValueError("observed CUDA work requires current correctness evidence")
    if workload_kind in CPU_AUTHORITY_KINDS and (
        selected_device != "cpu" or actual_device != "cpu"
    ):
        raise ValueError(f"{workload_kind} remains CPU-authoritative")
    record = {
        "schema_version": "px.execution-placement-workload/1.0",
        "workload_id": workload_id,
        "workload_kind": workload_kind,
        "current_placement": current_placement,
        "source_sha256": source_sha256,
        "scheduler_snapshot_sha256": _hash(scheduler_snapshot),
        "scheduler_bus_revision": int(scheduler_snapshot.get("bus_revision", 0)),
        "before_benchmark_sha256": before_benchmark["custody_hash"],
        "boundary_contract_sha256": boundary_contract_sha256,
        "rollback_artifact_sha256": rollback_artifact_sha256,
        "hardware_route": {
            "selected_device": selected_device,
            "actual_device": actual_device,
            "fallback": route_fallback,
            "fallback_reason": hardware_route.get("routing_reason") or hardware_route.get("reason"),
            "correctness_passed": hardware_route.get("correctness_passed"),
        },
        "cpu_authoritative": workload_kind in CPU_AUTHORITY_KINDS,
        "migration_authorized": False,
    }
    return {**record, "workload_observation_sha256": _hash(record)}


def decide_observed_placement(
    *,
    observation: Mapping[str, Any],
    mode: str,
    candidates: Sequence[Mapping[str, Any]],
    weights: Mapping[str, float] = DEFAULT_WEIGHTS,
    minimum_improvement: float = 0.05,
) -> dict[str, Any]:
    expected = _hash(
        {key: value for key, value in observation.items() if key != "workload_observation_sha256"}
    )
    if (
        observation.get("schema_version") != "px.execution-placement-workload/1.0"
        or observation.get("workload_observation_sha256") != expected
        or not _valid_hash(observation.get("before_benchmark_sha256"))
    ):
        raise ValueError("placement decision requires an intact observed workload")
    decision = decide_placement(
        mode=mode,
        candidates=candidates,
        baseline_sha256=str(observation["before_benchmark_sha256"]),
        weights=weights,
        minimum_improvement=minimum_improvement,
    )
    integrated = {
        **{key: value for key, value in decision.items() if key != "decision_sha256"},
        "schema_version": "px.execution-placement-decision/2.0",
        "workload_observation_sha256": observation["workload_observation_sha256"],
        "scheduler_bus_revision": observation.get("scheduler_bus_revision"),
        "boundary_contract_sha256": observation.get("boundary_contract_sha256"),
        "rollback_artifact_sha256": observation.get("rollback_artifact_sha256"),
        "hardware_route": observation.get("hardware_route"),
        "observed_workload": True,
    }
    return {**integrated, "decision_sha256": _hash(integrated)}


def observed_promotion_gate(
    decision: Mapping[str, Any],
    *,
    after_benchmark: Mapping[str, Any],
    matched_benchmark: Mapping[str, Any],
    rollback_test_sha256: str,
    boundary_validation_sha256: str,
    correctness_passed: bool,
    improvement_passed: bool,
    rollback_passed: bool,
    partial_units: Sequence[str],
) -> dict[str, Any]:
    if decision.get("observed_workload") is not True:
        raise ValueError("observed promotion cannot use a side-effect-free scorer decision")
    if after_benchmark.get("sealed") is not True or matched_benchmark.get("sealed") is not True:
        raise ValueError("after and matched benchmarks require sealed benchmark-owner custody")
    after_benchmark_sha256 = str(after_benchmark.get("custody_hash") or "")
    matched_benchmark_sha256 = str(matched_benchmark.get("custody_hash") or "")
    hashes = (
        decision.get("decision_sha256"),
        decision.get("baseline_sha256"),
        decision.get("workload_observation_sha256"),
        decision.get("boundary_contract_sha256"),
        decision.get("rollback_artifact_sha256"),
        after_benchmark_sha256,
        matched_benchmark_sha256,
        rollback_test_sha256,
        boundary_validation_sha256,
    )
    units = sorted(set(map(str, partial_units)))
    gates = {
        "candidate_selected": decision.get("recommendation") == "bounded_prototype",
        "artifact_set_complete": all(_valid_hash(value) for value in hashes),
        "partial_unit_bounded": bool(units),
        "correctness": correctness_passed,
        "matched_improvement": improvement_passed,
        "rollback": rollback_passed,
    }
    record = {
        "schema_version": "px.execution-placement-promotion/2.0",
        "decision_sha256": decision.get("decision_sha256"),
        "workload_observation_sha256": decision.get("workload_observation_sha256"),
        "selected_candidate": decision.get("selected_candidate"),
        "gates": gates,
        "evidence_sha256": sorted(set(map(str, hashes))),
        "partial_units": units,
        "passed": all(gates.values()),
        "promotion_tier": 3 if all(gates.values()) else int(decision.get("promotion_tier", 0)),
        "production_authorized": False,
        "rollback_candidate": decision.get("current_candidate"),
        "rollback_artifact_sha256": decision.get("rollback_artifact_sha256"),
    }
    return {**record, "promotion_sha256": _hash(record)}


def production_promotion_gate(
    tier3: Mapping[str, Any],
    *,
    production_approval_sha256: str,
    production_validation_sha256: str,
    monitoring_artifact_sha256: str,
    rollback_artifact_sha256: str,
    production_approved: bool,
) -> dict[str, Any]:
    hashes = (
        tier3.get("promotion_sha256"),
        production_approval_sha256,
        production_validation_sha256,
        monitoring_artifact_sha256,
        rollback_artifact_sha256,
    )
    gates = {
        "tier3_passed": tier3.get("passed") is True and tier3.get("promotion_tier") == 3,
        "separate_production_approval": production_approved,
        "production_artifacts_complete": all(_valid_hash(value) for value in hashes),
        "rollback_identity_matches": rollback_artifact_sha256 == tier3.get("rollback_artifact_sha256"),
        "partial_unit_retained": bool(tier3.get("partial_units")),
    }
    record = {
        "schema_version": "px.execution-placement-production/1.0",
        "tier3_promotion_sha256": tier3.get("promotion_sha256"),
        "gates": gates,
        "passed": all(gates.values()),
        "promotion_tier": 4 if all(gates.values()) else int(tier3.get("promotion_tier", 0)),
        "production_authorized": all(gates.values()),
        "partial_units": list(tier3.get("partial_units") or ()),
        "monitoring_artifact_sha256": monitoring_artifact_sha256,
        "rollback_artifact_sha256": rollback_artifact_sha256,
        "automatic_migration_authorized": False,
    }
    return {**record, "production_promotion_sha256": _hash(record)}


def reusable_pattern_gate(
    tier4: Mapping[str, Any],
    *,
    reuse_evidence_sha256: Sequence[str],
    successful_reuses: int,
    regressions: int,
    minimum_reuses: int,
    reusable_pattern_sha256: str,
    rollback_artifact_sha256: str,
) -> dict[str, Any]:
    evidence = sorted(set(map(str, reuse_evidence_sha256)))
    gates = {
        "tier4_passed": tier4.get("passed") is True and tier4.get("promotion_tier") == 4,
        "reuse_denominator": successful_reuses >= minimum_reuses > 0,
        "no_regressions": regressions == 0,
        "reuse_evidence_complete": len(evidence) >= minimum_reuses and all(_valid_hash(value) for value in evidence),
        "pattern_hashed": _valid_hash(reusable_pattern_sha256),
        "rollback_retained": rollback_artifact_sha256 == tier4.get("rollback_artifact_sha256"),
    }
    record = {
        "schema_version": "px.execution-placement-reusable-pattern/1.0",
        "tier4_promotion_sha256": tier4.get("production_promotion_sha256"),
        "gates": gates,
        "passed": all(gates.values()),
        "promotion_tier": 5 if all(gates.values()) else int(tier4.get("promotion_tier", 0)),
        "reusable_pattern_candidate": all(gates.values()),
        "canonical": False,
        "learning_promotion_required": True,
        "reuse_evidence_sha256": evidence,
        "successful_reuses": successful_reuses,
        "regressions": regressions,
        "reusable_pattern_sha256": reusable_pattern_sha256,
        "rollback_artifact_sha256": rollback_artifact_sha256,
    }
    return {**record, "reusable_pattern_promotion_sha256": _hash(record)}


def publish_placement_artifact(root: Path, artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Publish one immutable placement artifact through the runtime work owner."""
    from .work_admission import RuntimeWorkPlane

    artifact_hash = next(
        (
            str(value)
            for key, value in reversed(tuple(artifact.items()))
            if key.endswith("sha256") and _valid_hash(value)
        ),
        _hash(artifact),
    )
    target = root.resolve() / ".engineering-bootstrap" / "runtime-core" / "placement" / f"{artifact_hash}.json"

    def publish() -> dict[str, Any]:
        rendered = json.dumps(dict(artifact), indent=2, sort_keys=True) + "\n"
        if target.is_file():
            if target.read_text(encoding="utf-8") != rendered:
                raise RuntimeError("placement artifact hash collision")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            prepared = target.with_name(f".{target.name}.{uuid4().hex}.prepared")
            prepared.write_text(rendered, encoding="utf-8")
            os.replace(prepared, target)
        return {"path": target.relative_to(root.resolve()).as_posix(), "artifact_sha256": artifact_hash}

    envelope = RuntimeWorkPlane(root).execute(
        f"execution-placement.publish:{artifact_hash}",
        publish,
        reason="explicit placement lifecycle command",
        input_fingerprint=artifact,
        domains=("execution-placement",),
        lane="light",
        cache_seconds=0,
        authoritative=True,
    )
    return {**envelope["result"], "runtime_admission": envelope["admission"]}
