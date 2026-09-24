from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from runtime.learning_promotion import route_evidence_candidate
from runtime.model_capacity import ModelCapacityNeed, ModelCapacitySnapshot, assess_model_capacity
from runtime.model_route_state import AdaptiveRouteSignal
from runtime.models import (
    ModelCapability,
    ModelRuntimeHint,
    bind_model_routing_policy,
    load_model_routing_policy,
    load_model_routing_policy_binding,
    model_routing_policy_semantic_sha256,
    route_models,
)
from scripts.benchmark_model_routes import benchmark_payload

ROOT = Path(__file__).parents[1]


def model(model_id: str, *, privacy="local", cost="free") -> ModelCapability:
    return ModelCapability(
        model_id=model_id, runtime="llama.cpp", available=True, context_tokens=8192,
        traits=("coding",), supports_tools=True, privacy=privacy, cost_class=cost,
        latency_class="low", warm_cost=0.0, cold_cost=0.0, failure_modes=(),
    )


def test_stable_affinity_can_rank_but_provisional_evidence_cannot() -> None:
    policy = replace(load_model_routing_policy(ROOT), route_phase="publish")
    binding = bind_model_routing_policy(policy, model_routing_policy_semantic_sha256(policy))
    models = (model("a"), model("b"))
    hints = {
        "a": ModelRuntimeHint("a", "resident", "healthy", True, True, 0, fabric_generation_id="a" * 64),
        "b": ModelRuntimeHint("b", "resident", "healthy", True, True, 0, fabric_generation_id="b" * 64),
    }
    provisional = {"b": AdaptiveRouteSignal("b", affinity=1.0, quality=1.0, maturity="provisional", model_generation_sha256="b" * 64, evidence_sha256=("1" * 64,))}
    decision = route_models(
        ("coding",), models, request_id="r1", task_class="coding", subject_ids=("coding",),
        policy_binding=binding, runtime_hints=hints, route_signals=provisional,
    )
    assert decision.primary_model_id == "a"

    stable = {"b": AdaptiveRouteSignal("b", affinity=1.0, quality=1.0, maturity="stable", model_generation_sha256="b" * 64, evidence_sha256=("1" * 64,))}
    decision = route_models(
        ("coding",), models, request_id="r2", task_class="coding", subject_ids=("coding",),
        policy_binding=binding, runtime_hints=hints, route_signals=stable,
    )
    assert decision.primary_model_id == "b"
    assert decision.authority_granted is False


def test_freeze_disables_challenger_and_certify_enables_evidence_challenger() -> None:
    base = load_model_routing_policy(ROOT)
    models = (model("a"), model("b"))
    frozen_policy = replace(base, route_phase="freeze")
    frozen_binding = bind_model_routing_policy(frozen_policy, model_routing_policy_semantic_sha256(frozen_policy))
    frozen = route_models(
        ("coding",), models, request_id="same", task_class="coding", subject_ids=("coding",),
        policy_binding=frozen_binding,
    )
    assert frozen.challenger_model_id is None
    cert_policy = replace(base, route_phase="certify")
    cert_binding = bind_model_routing_policy(cert_policy, model_routing_policy_semantic_sha256(cert_policy))
    cert = route_models(
        ("coding",), models, request_id="same", task_class="coding", subject_ids=("coding",),
        policy_binding=cert_binding,
    )
    assert cert.primary_model_id == "a"
    assert cert.challenger_model_id == "b"


def test_capacity_wait_is_dropless_and_fallback_requires_explicit_callsite_intent() -> None:
    policy = replace(load_model_routing_policy(ROOT), route_phase="publish")
    binding = bind_model_routing_policy(policy, model_routing_policy_semantic_sha256(policy))
    models = (model("a"), model("b", cost="low"))
    snap = ModelCapacitySnapshot(
        cpu_cores_total=8, cpu_cores_available=4, ram_gb_total=32, ram_gb_available=32,
        vram_gb_total=8, vram_gb_available=8, concurrent_slots_total=2, concurrent_slots_available=2,
        queue_depth=0, max_queue_depth=8,
    )
    capacities = {
        "a": assess_model_capacity(snap, ModelCapacityNeed("a", cpu_cores=6)),
        "b": assess_model_capacity(snap, ModelCapacityNeed("b", cpu_cores=2)),
    }
    waiting = route_models(
        ("coding",), models, request_id="r", task_class="coding", subject_ids=("coding",),
        policy_binding=binding, capacity_decisions=capacities,
    )
    assert waiting.primary_model_id == "a"
    assert waiting.dispatch_state == "wait"
    assert waiting.fallback_used is False

    fallback = route_models(
        ("coding",), models, request_id="r", task_class="coding", subject_ids=("coding",),
        policy_binding=binding, capacity_decisions=capacities, allow_capacity_fallback=True,
    )
    assert fallback.primary_model_id == "b"
    assert fallback.dispatch_state == "dispatch"
    assert fallback.fallback_used is True


def test_route_learning_bridge_emits_candidate_only() -> None:
    candidate = route_evidence_candidate(
        route_evidence_sha256="a" * 64, incumbent_policy_sha256="b" * 64,
        candidate_policy_sha256="c" * 64, task_classes=("coding", "hvac"),
        review_reasons=("distribution_drift",), complexity_tax_passed=True,
    )
    assert candidate["record_type"] == "route_evidence_candidate"
    assert candidate["state"] == "candidate"
    assert candidate["canonical"] is False
    assert candidate["policy_write_allowed"] is False
    assert candidate["learning_direct_write_allowed"] is False
    assert candidate["promotion_required"] is True


def test_policy_contract_is_frozen_and_benchmark_cli_path_is_evidence_only(tmp_path: Path) -> None:
    policy = load_model_routing_policy(ROOT)
    assert policy.route_phase == "freeze"
    assert policy.capacity_dropless is True
    assert policy.capacity_fallback_requires_explicit is True
    assert policy.challenger_certify_mode == "always"
    binding = load_model_routing_policy_binding(ROOT)
    assert binding.policy == policy
    assert len(binding.source_sha256) == 64 and len(binding.semantic_sha256) == 64

    fixture_sha = "d" * 64
    incumbent_sha, candidate_sha = "a" * 64, "b" * 64
    row = {
        "fixture_id": "f1", "domain": "coding", "ranking": ["m1", "m2"],
        "primary_model_id": "m1", "challenger_model_id": None, "verified_success": True,
        "latency_ms": 10.0, "remote_cost": 0.0, "local_completion": True, "feature_ids": ["coding"],
    }
    payload = {
        "schema_version": "px.model-route-benchmark-input/1.0", "fixture_sha256": fixture_sha,
        "domain_floors": {"coding": 0.5},
        "materiality": {"min_quality_delta": 0.01, "min_latency_improvement_ratio": 0.05, "min_remote_cost_reduction_ratio": 0.05, "min_local_completion_delta": 0.05},
        "incumbent": [{**row, "policy_sha256": incumbent_sha}],
        "candidate": [{**row, "policy_sha256": candidate_sha}],
    }
    result = benchmark_payload(ROOT, payload)
    assert result["authority_granted"] is False
    assert result["auto_promotion_allowed"] is False
    assert len(result["benchmark_policy_sha256"]) == 64
    assert result["route_evidence"]["authority_granted"] is False


def test_policy_binding_rejects_in_memory_mutation_and_route_signal_generation_mismatch() -> None:
    from runtime.models import ModelRoutingPolicyBinding
    binding = load_model_routing_policy_binding(ROOT)
    mutated = replace(binding.policy, route_phase="certify")
    with pytest.raises(ValueError, match="semantic identity is stale"):
        ModelRoutingPolicyBinding(mutated, binding.source_sha256, binding.semantic_sha256)

    models = (model("a"), model("b"))
    hints = {
        "a": ModelRuntimeHint("a", "resident", "healthy", True, True, 0, fabric_generation_id="a" * 64),
        "b": ModelRuntimeHint("b", "resident", "healthy", True, True, 0, fabric_generation_id="b" * 64),
    }
    signal = {"b": AdaptiveRouteSignal(
        "b", affinity=1.0, quality=1.0, maturity="stable",
        model_generation_sha256="c" * 64, evidence_sha256=("d" * 64,),
    )}
    with pytest.raises(ValueError, match="does not match runtime hint"):
        route_models(
            ("coding",), models, request_id="mismatch", task_class="coding", subject_ids=("coding",),
            policy_binding=binding, runtime_hints=hints, route_signals=signal,
        )


def test_benchmark_cli_executes_from_repo_root_and_emits_content_addressed_envelope(tmp_path: Path) -> None:
    import subprocess
    import sys

    row = {
        "fixture_id": "f1", "domain": "coding", "ranking": ["m1", "m2"],
        "primary_model_id": "m1", "challenger_model_id": None, "verified_success": True,
        "latency_ms": 10.0, "remote_cost": 1.0, "local_completion": False, "feature_ids": ["coding"],
    }
    candidate = {**row, "primary_model_id": "m2", "ranking": ["m2", "m1"], "verified_success": True, "latency_ms": 8.0, "local_completion": True}
    payload = {
        "schema_version": "px.model-route-benchmark-input/1.0",
        "fixture_sha256": "e" * 64,
        "domain_floors": {"coding": 0.5},
        "materiality": {
            "min_quality_delta": 0.1,
            "min_latency_improvement_ratio": 0.1,
            "min_remote_cost_reduction_ratio": 0.1,
            "min_local_completion_delta": 0.1,
        },
        "incumbent": [{**row, "policy_sha256": "a" * 64}],
        "candidate": [{**candidate, "policy_sha256": "b" * 64}],
    }
    input_path = tmp_path / "input.json"
    output_path = tmp_path / "output.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    subprocess.run(
        [sys.executable, "scripts/benchmark_model_routes.py", "--root", str(ROOT), "--input", str(input_path), "--output", str(output_path)],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(result["envelope_sha256"]) == 64
    assert result["authority_granted"] is False
    assert result["auto_promotion_allowed"] is False
