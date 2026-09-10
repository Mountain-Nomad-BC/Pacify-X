"""Capability-based, availability-aware model discovery and routing."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import shutil
from typing import Callable, Iterable

from .archive_io import reject_path_links
from .json_io import bounded_strings, load_json_object

MAX_MODEL_CANDIDATES = 256


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
    reject_path_links(root)
    path = root / "models" / "routing-policy.json"
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=65536)
    if (
        set(payload) != {"schema_version", "mode", "eligibility", "scoring", "fallback"}
        or payload["schema_version"] != "1.0"
        or payload["mode"] != "capability_and_availability"
    ):
        raise ValueError("unsupported model routing policy contract")
    scoring = payload["scoring"]
    eligibility = payload["eligibility"]
    if (
        type(scoring) is not dict
        or set(scoring)
        != {
            "trait_weight",
            "privacy_weights",
            "cost_weights",
            "latency_weights",
            "cold_cost_weight",
        }
        or type(eligibility) is not dict
        or set(eligibility)
        != {
            "unavailable_is_ineligible",
            "required_traits_must_all_match",
            "minimum_context_must_match",
            "sensitive_privacy",
        }
    ):
        raise ValueError("model routing policy fields are incomplete or unsupported")
    if (
        eligibility["required_traits_must_all_match"] is not True
        or eligibility["minimum_context_must_match"] is not True
    ):
        raise ValueError("unsupported model eligibility contract")
    fallback = payload["fallback"]
    if (
        type(fallback) is not dict
        or set(fallback)
        != {
            "when_no_eligible_model",
            "silent_privacy_downgrade",
            "silent_context_downgrade",
            "auto_download",
        }
        or fallback["when_no_eligible_model"] != "return_explicit_fallback_required"
        or any(
            fallback[key] is not False
            for key in (
                "silent_privacy_downgrade",
                "silent_context_downgrade",
                "auto_download",
            )
        )
    ):
        raise ValueError("unsupported model fallback contract")
    privacy = eligibility["sensitive_privacy"]
    if type(privacy) is not list or not 1 <= len(privacy) <= 64:
        raise ValueError("model sensitive privacy requires a bounded list")
    policy = ModelRoutingPolicy(
        trait_weight=scoring["trait_weight"],
        privacy_weights=scoring["privacy_weights"],
        cost_weights=scoring["cost_weights"],
        latency_weights=scoring["latency_weights"],
        cold_cost_weight=scoring["cold_cost_weight"],
        sensitive_privacy=tuple(privacy),
        unavailable_is_ineligible=eligibility["unavailable_is_ineligible"],
    )
    _validate_routing_policy(policy)
    return policy


def _validate_routing_policy(policy: ModelRoutingPolicy) -> None:
    if type(policy) is not ModelRoutingPolicy:
        raise ValueError("typed model routing policy is required")

    def weight(value):
        if (
            type(value) not in (int, float)
            or abs(value) > 1e100
            or not math.isfinite(value)
        ):
            raise ValueError("model routing weights must be bounded finite numbers")

    weight(policy.trait_weight)
    weight(policy.cold_cost_weight)
    if policy.trait_weight <= 0 or policy.cold_cost_weight < 0:
        raise ValueError(
            "model trait weight must be positive and cold cost weight nonnegative"
        )
    for values in (policy.privacy_weights, policy.cost_weights, policy.latency_weights):
        if type(values) is not dict or len(values) > 64:
            raise ValueError("model policy weights require bounded objects")
        bounded_strings(
            values.keys(), max_items=64, max_item_bytes=256, max_bytes=16384
        )
        for value in values.values():
            weight(value)
    if type(policy.sensitive_privacy) is not tuple or not policy.sensitive_privacy:
        raise ValueError(
            "model sensitive privacy requires a bounded immutable sequence"
        )
    bounded_strings(
        policy.sensitive_privacy, max_items=64, max_item_bytes=256, max_bytes=16384
    )
    if type(policy.unavailable_is_ineligible) is not bool:
        raise ValueError("model availability policy must be boolean")


def discover_local_runtimes(
    names: Iterable[str] = ("ollama", "llama-server", "lmstudio"),
    *,
    resolver: Callable[[str], str | None] = shutil.which,
    max_runtimes: int = 3,
) -> tuple[tuple[str, str], ...]:
    if type(max_runtimes) is not int or not 1 <= max_runtimes <= 8:
        raise ValueError("max_runtimes must be between 1 and 8")
    names = bounded_strings(
        names, max_items=MAX_MODEL_CANDIDATES, max_item_bytes=256, max_bytes=65536
    )
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
    policy = DEFAULT_ROUTING_POLICY if policy is None else policy
    _validate_routing_policy(policy)
    if type(min_context_tokens) is not int or not 1 <= min_context_tokens <= 2**31:
        raise ValueError("minimum model context must be a bounded positive integer")
    if type(sensitive) is not bool:
        raise ValueError("sensitive model routing must be boolean")
    required = set(
        bounded_strings(task_traits, max_items=64, max_item_bytes=256, max_bytes=16384)
    )
    routes: list[ModelRoute] = []
    seen = set()
    for index, model in enumerate(models):
        if index >= MAX_MODEL_CANDIDATES:
            raise ValueError("model capability record budget exceeded")
        validate_model_capability(model)
        if model.model_id in seen:
            raise ValueError("duplicate model capability identity")
        seen.add(model.model_id)
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


def validate_model_capability(model: ModelCapability) -> None:
    """Validate raw capability types before selection can coerce their meaning."""
    if type(model) is not ModelCapability:
        raise ValueError("typed model capability is required")
    for field in ("model_id", "runtime", "privacy", "cost_class", "latency_class"):
        value = getattr(model, field)
        if (
            type(value) is not str
            or not value.strip()
            or len(value) > 256
            or len(value.encode()) > 256
        ):
            raise ValueError(f"model {field} must be bounded nonempty text")
    if type(model.available) is not bool or type(model.supports_tools) is not bool:
        raise ValueError("model availability and tool support must be boolean")
    if type(model.context_tokens) is not int or not 0 <= model.context_tokens <= 2**31:
        raise ValueError("model context must be a bounded nonnegative integer")
    for field in ("traits", "failure_modes"):
        values = getattr(model, field)
        if type(values) not in (tuple, list):
            raise ValueError(f"model {field} must be a bounded string sequence")
        bounded_strings(values, max_items=64, max_item_bytes=256, max_bytes=16384)
    for field in ("warm_cost", "cold_cost"):
        value = getattr(model, field)
        if (
            type(value) not in (int, float)
            or not 0 <= value <= 1e100
            or not math.isfinite(value)
        ):
            raise ValueError(
                f"model {field} must be bounded finite nonnegative metadata"
            )
