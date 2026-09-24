from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from runtime.model_profile import load_runtime_profiles, runtime_profile_from_mapping
from runtime.models import ModelCapability, ModelRuntimeHint, load_model_portfolio, load_model_routing_policy, rank_models


ROOT = Path(__file__).parents[1]


def test_runtime_profile_registry_is_exact_digest_bound_and_operator_profile_is_bounded() -> None:
    profiles = load_runtime_profiles(ROOT)
    assert len(profiles) == 10
    assert len({item.profile_id for item in profiles}) == len(profiles)
    operator = next(item for item in profiles if item.model_id == "qwen35-4b-operator")
    assert operator.lane == "control"
    assert operator.residency == "resident"
    assert operator.gpu_layers == 0
    assert operator.reasoning is False
    assert operator.text_only is True
    # The librarian profile has been benchmark-certified: its measured placement is frozen and it
    # no longer requires a benchmark. A profile must not sit in the candidate state once certified.
    assert operator.is_certified is True
    assert operator.benchmark_required is False
    # Certification freezes measured placement, so threads must be a concrete measured value.
    assert isinstance(operator.threads, int) and operator.threads > 0
    assert len(operator.profile_sha256) == 64


def test_profile_digest_changes_with_execution_relevant_state_and_certification_fails_open_fields() -> None:
    source = next(item for item in load_runtime_profiles(ROOT) if item.model_id == "qwen35-4b-operator")
    raw = source.identity_payload()
    raw["context_tokens"] = source.context_tokens + 4096
    changed = runtime_profile_from_mapping(raw)
    assert changed.profile_sha256 != source.profile_sha256

    # A certified profile may not silently drop its frozen placement. Unfreezing the measured
    # thread/GPU values must fail closed, which is what "certification fails open fields" means.
    unfrozen = dict(source.identity_payload())
    unfrozen.update({"state": "certified", "benchmark_required": False,
                     "threads": None, "threads_batch": None})
    with pytest.raises(ValueError, match="frozen thread/GPU placement"):
        runtime_profile_from_mapping(unfrozen)


def test_control_profile_rejects_reasoning_gpu_or_idle_residency() -> None:
    source = next(item for item in load_runtime_profiles(ROOT) if item.model_id == "qwen35-4b-operator")
    for field, value, match in (
        ("reasoning", True, "reasoning"),
        ("gpu_layers", 1, "CPU-only"),
        ("idle_evict_seconds", 10, "resident"),
    ):
        raw = source.identity_payload()
        raw[field] = value
        with pytest.raises(ValueError, match=match):
            runtime_profile_from_mapping(raw)


def test_model_portfolio_preserves_operator_effect_boundary_and_deep_candidate() -> None:
    portfolio = load_model_portfolio(ROOT)
    operator = next(item for item in portfolio if item.model_id == "qwen35-4b-operator")
    deep = next(item for item in portfolio if item.model_id == "qwen3-30b-a3b-deep")
    assert operator.role == "resident_px_operator_preferred_candidate"
    assert "learning_trigger_planning" in operator.traits
    assert "graph_map_update_planning" in operator.traits
    # The operator and deep artifacts are now acquired: identity is hash-bound, not null.
    assert operator.artifact_sha256 == (
        "5a5bc7a3f9375b395e9f81fb69109038cf160c84606b8192f13cbb8355ca59f2"
    )
    assert operator.authority["effect_grant_required"] is True
    assert operator.authority["direct_tool_execution"] is False
    assert operator.authority["canonical_memory_write"] is False
    assert operator.authority["graph_map_persistence"] is False
    assert operator.authority["learning_promotion"] is False
    assert deep.role == "preferred_deep_hybrid_candidate"
    assert deep.artifact_sha256 == (
        "e6db7da56bdb19ba30541c73628f15e8f1f45be1b1f96df4383e03fec375e43a"
    )


def test_control_routing_requires_certified_runtime_hint_and_deterministic_unresolved() -> None:
    policy = load_model_routing_policy(ROOT)
    operator = next(item for item in load_model_portfolio(ROOT) if item.model_id == "qwen35-4b-operator")
    profile = next(item for item in load_runtime_profiles(ROOT) if item.model_id == operator.model_id)
    candidate = ModelCapability(
        operator.model_id, operator.runtime, True, profile.context_tokens, operator.traits, True,
        operator.privacy, "free", "low", 0.1, 1.0, (),
    )
    resolved = rank_models(("px_internal_operator",), (candidate,), policy=policy, control_lane=True, deterministic_unresolved=False)
    assert resolved[0].fallback_required is True
    assert resolved[0].model_id is None

    hint = ModelRuntimeHint(
        model_id=candidate.model_id,
        residency="resident",
        health="healthy",
        certified=False,
        control_eligible=True,
        queue_depth=0,
        profile_id="control-qwen35-4b-cpu-q6",
        fabric_generation_id="a" * 64,
    )
    blocked = rank_models(("px_internal_operator",), (candidate,), policy=policy, runtime_hints={candidate.model_id: hint}, control_lane=True)
    assert blocked[0].fallback_required is True

    certified_hint = ModelRuntimeHint(**{**asdict(hint), "certified": True})
    routed = rank_models(("px_internal_operator",), (candidate,), policy=policy, runtime_hints={candidate.model_id: certified_hint}, control_lane=True)
    assert routed[0].model_id == candidate.model_id
    assert routed[0].fallback_required is False


def test_certification_freezes_only_measured_placement_not_arbitrary_profile_changes() -> None:
    from scripts.certify_local_model_profiles import _certified_profile

    profile = next(item for item in load_runtime_profiles(ROOT) if item.model_id == "qwen35-4b-operator")
    effective = profile.identity_payload()
    effective.update({"threads": 4, "threads_batch": 4, "gpu_layers": 0})
    certified = _certified_profile(profile, {"effective_profile": effective})
    assert certified["state"] == "certified"
    assert certified["benchmark_required"] is False
    assert certified["threads"] == 4

    tampered = dict(effective)
    tampered["context_tokens"] = profile.context_tokens + 4096
    with pytest.raises(ValueError, match="non-placement profile field: context_tokens"):
        _certified_profile(profile, {"effective_profile": tampered})
