"""Capability-based, availability-aware model discovery and routing."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
from typing import Callable, Iterable


@dataclass(frozen=True, slots=True)
class ModelCapability:
    model_id: str
    runtime: str
    available: bool
    context_tokens: int
    traits: tuple[str, ...]
    supports_tools: bool
    privacy: str
    cost_class: str
    latency_class: str
    warm_cost: float
    cold_cost: float
    failure_modes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelRoute:
    model_id: str | None
    score: float
    explanation: tuple[str, ...]
    fallback_required: bool


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicy:
    trait_weight: float
    privacy_weights: dict[str, float]
    cost_weights: dict[str, float]
    latency_weights: dict[str, float]
    cold_cost_weight: float
    sensitive_privacy: tuple[str, ...]
    unavailable_is_ineligible: bool = True


DEFAULT_ROUTING_POLICY = ModelRoutingPolicy(
    trait_weight=10.0,
    privacy_weights={"local": 3.0, "isolated": 2.0, "policy_gated": 0.0},
    cost_weights={"free": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0},
    latency_weights={"low": 0.0, "medium": 1.0, "high": 3.0},
    cold_cost_weight=1.0,
    sensitive_privacy=("local", "isolated"),
)


def load_model_routing_policy(root: Path) -> ModelRoutingPolicy:
    """Load routing weights only when model routing is requested."""
    path = root.resolve() / "models" / "routing-policy.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    scoring = payload["scoring"]
    eligibility = payload["eligibility"]
    policy = ModelRoutingPolicy(
        trait_weight=float(scoring["trait_weight"]),
        privacy_weights={
            str(key): float(value) for key, value in scoring["privacy_weights"].items()
        },
        cost_weights={
            str(key): float(value) for key, value in scoring["cost_weights"].items()
        },
        latency_weights={
            str(key): float(value) for key, value in scoring["latency_weights"].items()
        },
        cold_cost_weight=float(scoring["cold_cost_weight"]),
        sensitive_privacy=tuple(map(str, eligibility["sensitive_privacy"])),
        unavailable_is_ineligible=bool(eligibility["unavailable_is_ineligible"]),
    )
    if policy.trait_weight <= 0 or policy.cold_cost_weight < 0:
        raise ValueError(
            "model routing weights must be non-negative and trait_weight must be positive"
        )
    if not policy.sensitive_privacy:
        raise ValueError(
            "sensitive model routing must declare at least one privacy class"
        )
    return policy


def discover_local_runtimes(
    names: Iterable[str] = ("ollama", "llama-server", "lmstudio"),
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    max_runtimes: int = 3,
) -> tuple[tuple[str, str], ...]:
    if max_runtimes < 1 or max_runtimes > 8:
        raise ValueError("max_runtimes must be between 1 and 8")
    discovered = []
    for name in sorted(set(names))[:max_runtimes]:
        location = resolver(name)
        if location:
            discovered.append((name, location))
    return tuple(discovered)


def rank_models(
    task_traits: Iterable[str],
    models: Iterable[ModelCapability],
    *,
    min_context_tokens: int = 1,
    sensitive: bool = False,
    policy: ModelRoutingPolicy | None = None,
) -> tuple[ModelRoute, ...]:
    policy = policy or DEFAULT_ROUTING_POLICY
    required = set(task_traits)
    routes: list[ModelRoute] = []
    for model in models:
        if policy.unavailable_is_ineligible and not model.available:
            continue
        if model.context_tokens < min_context_tokens:
            continue
        if sensitive and model.privacy not in set(policy.sensitive_privacy):
            continue
        matched = required & set(model.traits)
        if required - matched:
            continue
        privacy = policy.privacy_weights.get(model.privacy, 0.0)
        cost = policy.cost_weights.get(
            model.cost_class, max(policy.cost_weights.values(), default=3.0)
        )
        latency = policy.latency_weights.get(
            model.latency_class, max(policy.latency_weights.values(), default=2.0)
        )
        score = round(
            policy.trait_weight * len(matched)
            + privacy
            - cost
            - latency
            - policy.cold_cost_weight * model.cold_cost,
            3,
        )
        routes.append(
            ModelRoute(
                model.model_id,
                score,
                (
                    f"traits={','.join(sorted(matched))}",
                    f"privacy={model.privacy}",
                    f"cost={model.cost_class}",
                    f"latency={model.latency_class}",
                ),
                False,
            )
        )
    routes.sort(key=lambda item: (-item.score, item.model_id or ""))
    return (
        tuple(routes)
        if routes
        else (
            ModelRoute(None, 0, ("no available model satisfies the contract",), True),
        )
    )
