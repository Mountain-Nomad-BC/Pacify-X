"""Capability-based, availability-aware model discovery and routing."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path
import shutil
import hashlib
import json
from typing import Callable, Iterable, Mapping

from .archive_io import reject_path_links
from .json_io import bounded_strings, load_json_object

MAX_MODEL_CANDIDATES = 256


@dataclass(frozen=True, slots=True)
class PortfolioModel:
    model_id: str
    display_name: str
    source_repo: str
    runtime: str
    lane: str
    role: str
    state: str
    privacy: str
    traits: tuple[str, ...]
    authority: dict[str, bool]
    artifact_sha256: str | None
    default_profile_id: str


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
class ModelRuntimeHint:
    model_id: str
    residency: str
    health: str
    certified: bool
    control_eligible: bool
    queue_depth: int = 0
    profile_id: str | None = None
    fabric_generation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicy:
    trait_weight: float
    privacy_weights: dict[str, float]
    cost_weights: dict[str, float]
    latency_weights: dict[str, float]
    cold_cost_weight: float
    sensitive_privacy: tuple[str, ...]
    unavailable_is_ineligible: bool = True
    resident_bonus: float = 2.0
    warm_bonus: float = 1.0
    cold_penalty: float = 1.0
    queue_penalty: float = 0.25
    deterministic_first: bool = True
    control_requires_certified: bool = True
    max_control_queue_depth: int = 8
    route_phase: str = "freeze"
    max_candidate_projection: int = 3
    affinity_weight: float = 1.5
    quality_weight: float = 2.0
    availability_weight: float = 0.5
    pressure_penalty: float = 1.0
    requires_stable_route_evidence: bool = True
    challenger_discovery_mode: str = "sample"
    challenger_calibration_mode: str = "always"
    challenger_anneal_mode: str = "threshold"
    challenger_freeze_mode: str = "none"
    challenger_certify_mode: str = "always"
    challenger_publish_mode: str = "none"
    challenger_score_margin: float = 0.5
    challenger_sample_rate: float = 0.05
    capacity_dropless: bool = True
    capacity_fallback_requires_explicit: bool = True
    max_route_queue_depth: int = 64


@dataclass(frozen=True, slots=True)
class ModelRoutingPolicyBinding:
    policy: ModelRoutingPolicy
    source_sha256: str
    semantic_sha256: str

    def __post_init__(self) -> None:
        if type(self.policy) is not ModelRoutingPolicy:
            raise ValueError("routing policy binding requires typed policy")
        for name, value in (("source", self.source_sha256), ("semantic", self.semantic_sha256)):
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"routing policy {name} SHA-256 is invalid")
        if self.semantic_sha256 != model_routing_policy_semantic_sha256(self.policy):
            raise ValueError("routing policy binding semantic identity is stale")


DEFAULT_ROUTING_POLICY = ModelRoutingPolicy(
    trait_weight=10.0,
    privacy_weights={"local": 3.0, "isolated": 2.0, "policy_gated": 0.0},
    cost_weights={"free": 0.0, "low": 1.0, "medium": 2.0, "high": 4.0},
    latency_weights={"low": 0.0, "medium": 1.0, "high": 3.0},
    cold_cost_weight=1.0,
    sensitive_privacy=("local", "isolated"),
    resident_bonus=2.0,
    warm_bonus=1.0,
    cold_penalty=1.0,
    queue_penalty=0.25,
    deterministic_first=True,
    control_requires_certified=True,
    max_control_queue_depth=8,
    route_phase="freeze",
    max_candidate_projection=3,
    affinity_weight=1.5,
    quality_weight=2.0,
    availability_weight=0.5,
    pressure_penalty=1.0,
    requires_stable_route_evidence=True,
    challenger_discovery_mode="sample",
    challenger_calibration_mode="always",
    challenger_anneal_mode="threshold",
    challenger_freeze_mode="none",
    challenger_certify_mode="always",
    challenger_publish_mode="none",
    challenger_score_margin=0.5,
    challenger_sample_rate=0.05,
    capacity_dropless=True,
    capacity_fallback_requires_explicit=True,
    max_route_queue_depth=64,
)


def load_model_portfolio(root: Path) -> tuple[PortfolioModel, ...]:
    reject_path_links(root)
    path = root / "models" / "model-portfolio.json"
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=262_144)
    if set(payload) != {"schema_version", "weights_bundled", "auto_download", "selection_rule", "models"}:
        raise ValueError("model portfolio fields are incomplete or unsupported")
    if payload["schema_version"] != "px.model-portfolio/1.0" or payload["weights_bundled"] is not False or payload["auto_download"] is not False:
        raise ValueError("unsupported or unsafe model portfolio contract")
    if payload["selection_rule"] != "candidate_until_exact_artifact_and_profile_are_benchmark_certified":
        raise ValueError("model portfolio selection rule is unsupported")
    rows = payload["models"]
    if type(rows) is not list or not 1 <= len(rows) <= MAX_MODEL_CANDIDATES:
        raise ValueError("model portfolio requires a bounded nonempty model list")
    authority_keys = {
        "direct_tool_execution", "canonical_memory_write", "canonical_knowledge_write",
        "policy_write", "graph_map_persistence", "learning_promotion", "effect_grant_required",
    }
    models: list[PortfolioModel] = []
    seen: set[str] = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
            "model_id", "display_name", "source_repo", "runtime", "lane", "role", "state",
            "privacy", "traits", "authority", "artifact_sha256", "default_profile_id",
        }:
            raise ValueError("model portfolio entry fields are incomplete or unsupported")
        text_fields = ("model_id", "display_name", "source_repo", "runtime", "lane", "role", "state", "privacy", "default_profile_id")
        values: dict[str, str] = {}
        for field in text_fields:
            value = row[field]
            if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 256:
                raise ValueError(f"model portfolio {field} must be bounded nonempty text")
            values[field] = value.strip()
        if values["model_id"] in seen:
            raise ValueError("duplicate model portfolio identity")
        seen.add(values["model_id"])
        traits_raw = row["traits"]
        if type(traits_raw) is not list:
            raise ValueError("model portfolio traits must be a bounded list")
        traits = bounded_strings(traits_raw, max_items=64, max_item_bytes=256, max_bytes=16384)
        authority = row["authority"]
        if type(authority) is not dict or set(authority) != authority_keys:
            raise ValueError("model portfolio authority fields are incomplete or unsupported")
        if authority["effect_grant_required"] is not True or any(
            authority[key] is not False for key in authority_keys - {"effect_grant_required"}
        ):
            raise ValueError("model portfolio entry attempts to grant model-owned authority")
        artifact = row["artifact_sha256"]
        if artifact is not None:
            if type(artifact) is not str or len(artifact) != 64 or any(char not in "0123456789abcdef" for char in artifact):
                raise ValueError("model portfolio artifact SHA-256 must be lowercase hex or null")
        if values["state"] not in {"candidate", "certified", "retired"}:
            raise ValueError("unsupported model portfolio state")
        models.append(PortfolioModel(
            model_id=values["model_id"], display_name=values["display_name"], source_repo=values["source_repo"],
            runtime=values["runtime"], lane=values["lane"], role=values["role"], state=values["state"],
            privacy=values["privacy"], traits=tuple(traits), authority=dict(authority), artifact_sha256=artifact,
            default_profile_id=values["default_profile_id"],
        ))
    return tuple(models)


def model_routing_policy_semantic_sha256(policy: ModelRoutingPolicy) -> str:
    _validate_routing_policy(policy)
    payload = asdict(policy)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def bind_model_routing_policy(policy: ModelRoutingPolicy, source_sha256: str) -> ModelRoutingPolicyBinding:
    _validate_routing_policy(policy)
    return ModelRoutingPolicyBinding(policy, source_sha256, model_routing_policy_semantic_sha256(policy))


def model_routing_policy_sha256(root: Path) -> str:
    """Return the exact admitted routing-policy byte identity."""
    reject_path_links(root)
    path = root / "models" / "routing-policy.json"
    reject_path_links(path)
    raw = path.read_bytes()
    if len(raw) > 65_536:
        raise ValueError("model routing policy exceeds byte budget")
    return hashlib.sha256(raw).hexdigest()


def load_model_routing_policy(root: Path) -> ModelRoutingPolicy:
    """Load the model-route policy; learned evidence never edits this file."""
    reject_path_links(root)
    path = root / "models" / "routing-policy.json"
    reject_path_links(path)
    payload = load_json_object(path, max_bytes=65536)
    expected = {
        "schema_version", "mode", "eligibility", "scoring", "fallback", "residency",
        "control_lane", "adaptive_routing", "challenger", "capacity",
    }
    if set(payload) != expected or payload["schema_version"] != "1.2" or payload["mode"] != "capability_and_availability":
        raise ValueError("unsupported model routing policy contract")
    scoring = payload["scoring"]
    eligibility = payload["eligibility"]
    if (
        type(scoring) is not dict
        or set(scoring) != {"trait_weight", "privacy_weights", "cost_weights", "latency_weights", "cold_cost_weight"}
        or type(eligibility) is not dict
        or set(eligibility) != {"unavailable_is_ineligible", "required_traits_must_all_match", "minimum_context_must_match", "sensitive_privacy"}
    ):
        raise ValueError("model routing policy fields are incomplete or unsupported")
    if eligibility["required_traits_must_all_match"] is not True or eligibility["minimum_context_must_match"] is not True:
        raise ValueError("unsupported model eligibility contract")
    fallback = payload["fallback"]
    if (
        type(fallback) is not dict
        or set(fallback) != {"when_no_eligible_model", "silent_privacy_downgrade", "silent_context_downgrade", "auto_download"}
        or fallback["when_no_eligible_model"] != "return_explicit_fallback_required"
        or any(fallback[key] is not False for key in ("silent_privacy_downgrade", "silent_context_downgrade", "auto_download"))
    ):
        raise ValueError("unsupported model fallback contract")
    privacy = eligibility["sensitive_privacy"]
    if type(privacy) is not list or not 1 <= len(privacy) <= 64:
        raise ValueError("model sensitive privacy requires a bounded list")
    residency = payload["residency"]
    if type(residency) is not dict or set(residency) != {"resident_bonus", "warm_bonus", "cold_penalty", "queue_penalty"}:
        raise ValueError("model residency routing controls are incomplete or unsupported")
    control = payload["control_lane"]
    if type(control) is not dict or set(control) != {"deterministic_first", "requires_certified_profile", "max_queue_depth"}:
        raise ValueError("model control-lane routing controls are incomplete or unsupported")
    adaptive = payload["adaptive_routing"]
    if type(adaptive) is not dict or set(adaptive) != {
        "phase", "max_candidate_projection", "affinity_weight", "quality_weight",
        "availability_weight", "pressure_penalty", "requires_stable_evidence",
    }:
        raise ValueError("adaptive model routing controls are incomplete or unsupported")
    challenger = payload["challenger"]
    if type(challenger) is not dict or set(challenger) != {
        "discovery_mode", "calibration_mode", "anneal_mode", "freeze_mode", "certify_mode",
        "publish_mode", "score_margin", "sample_rate", "max_challengers",
    } or challenger["max_challengers"] != 1:
        raise ValueError("challenger routing controls are incomplete or unsupported")
    capacity = payload["capacity"]
    if type(capacity) is not dict or set(capacity) != {
        "dropless", "fallback_requires_explicit_request", "exclusive_heavy_models", "max_route_queue_depth",
    } or capacity["exclusive_heavy_models"] is not True:
        raise ValueError("model capacity routing controls are incomplete or unsupported")
    policy = ModelRoutingPolicy(
        trait_weight=scoring["trait_weight"], privacy_weights=scoring["privacy_weights"],
        cost_weights=scoring["cost_weights"], latency_weights=scoring["latency_weights"],
        cold_cost_weight=scoring["cold_cost_weight"], sensitive_privacy=tuple(privacy),
        unavailable_is_ineligible=eligibility["unavailable_is_ineligible"],
        resident_bonus=residency["resident_bonus"], warm_bonus=residency["warm_bonus"],
        cold_penalty=residency["cold_penalty"], queue_penalty=residency["queue_penalty"],
        deterministic_first=control["deterministic_first"], control_requires_certified=control["requires_certified_profile"],
        max_control_queue_depth=control["max_queue_depth"], route_phase=adaptive["phase"],
        max_candidate_projection=adaptive["max_candidate_projection"], affinity_weight=adaptive["affinity_weight"],
        quality_weight=adaptive["quality_weight"], availability_weight=adaptive["availability_weight"],
        pressure_penalty=adaptive["pressure_penalty"], requires_stable_route_evidence=adaptive["requires_stable_evidence"],
        challenger_discovery_mode=challenger["discovery_mode"], challenger_calibration_mode=challenger["calibration_mode"],
        challenger_anneal_mode=challenger["anneal_mode"], challenger_freeze_mode=challenger["freeze_mode"],
        challenger_certify_mode=challenger["certify_mode"], challenger_publish_mode=challenger["publish_mode"],
        challenger_score_margin=challenger["score_margin"], challenger_sample_rate=challenger["sample_rate"],
        capacity_dropless=capacity["dropless"], capacity_fallback_requires_explicit=capacity["fallback_requires_explicit_request"],
        max_route_queue_depth=capacity["max_route_queue_depth"],
    )
    _validate_routing_policy(policy)
    return policy


def load_model_routing_policy_binding(root: Path) -> ModelRoutingPolicyBinding:
    policy = load_model_routing_policy(root)
    return bind_model_routing_policy(policy, model_routing_policy_sha256(root))


def _validate_routing_policy(policy: ModelRoutingPolicy) -> None:
    if type(policy) is not ModelRoutingPolicy:
        raise ValueError("typed model routing policy is required")

    def weight(value: object, *, nonnegative: bool = False) -> float:
        if type(value) not in (int, float) or type(value) is bool or abs(float(value)) > 1e100 or not math.isfinite(float(value)):
            raise ValueError("model routing weights must be bounded finite numbers")
        number = float(value)
        if nonnegative and number < 0:
            raise ValueError("model routing weights must be nonnegative")
        return number

    weight(policy.trait_weight)
    weight(policy.cold_cost_weight, nonnegative=True)
    for name in ("resident_bonus", "warm_bonus", "cold_penalty", "queue_penalty", "affinity_weight", "quality_weight", "availability_weight", "pressure_penalty"):
        weight(getattr(policy, name), nonnegative=True)
    if policy.trait_weight <= 0:
        raise ValueError("model trait weight must be positive")
    for values in (policy.privacy_weights, policy.cost_weights, policy.latency_weights):
        if type(values) is not dict or len(values) > 64:
            raise ValueError("model policy weights require bounded objects")
        bounded_strings(values.keys(), max_items=64, max_item_bytes=256, max_bytes=16384)
        for value in values.values():
            weight(value)
    if type(policy.sensitive_privacy) is not tuple or not policy.sensitive_privacy:
        raise ValueError("model sensitive privacy requires a bounded immutable sequence")
    bounded_strings(policy.sensitive_privacy, max_items=64, max_item_bytes=256, max_bytes=16384)
    for name in ("unavailable_is_ineligible", "deterministic_first", "control_requires_certified", "requires_stable_route_evidence", "capacity_dropless", "capacity_fallback_requires_explicit"):
        if type(getattr(policy, name)) is not bool:
            raise ValueError(f"model routing flag {name} must be boolean")
    if policy.capacity_dropless is not True:
        raise ValueError("model capacity policy must remain dropless")
    if policy.capacity_fallback_requires_explicit is not True:
        raise ValueError("model capacity fallback must require explicit call-site intent")
    if policy.route_phase not in {"discovery", "calibration", "anneal", "freeze", "certify", "publish"}:
        raise ValueError("unsupported model route phase")
    if type(policy.max_candidate_projection) is not int or not 1 <= policy.max_candidate_projection <= 16:
        raise ValueError("model candidate projection bound is invalid")
    if type(policy.max_control_queue_depth) is not int or not 0 <= policy.max_control_queue_depth <= 1_000_000:
        raise ValueError("model control-lane queue bound is invalid")
    if type(policy.max_route_queue_depth) is not int or not 1 <= policy.max_route_queue_depth <= 1_000_000:
        raise ValueError("model route queue bound is invalid")
    for name in (
        "challenger_discovery_mode", "challenger_calibration_mode", "challenger_anneal_mode",
        "challenger_freeze_mode", "challenger_certify_mode", "challenger_publish_mode",
    ):
        if getattr(policy, name) not in {"none", "threshold", "sample", "always"}:
            raise ValueError("unsupported model challenger mode")
    if not 0.0 <= weight(policy.challenger_score_margin, nonnegative=True) <= 1e6:
        raise ValueError("challenger score margin is invalid")
    if not 0.0 <= weight(policy.challenger_sample_rate, nonnegative=True) <= 1.0:
        raise ValueError("challenger sample rate is invalid")


def _challenger_mode(policy: ModelRoutingPolicy) -> str:
    return {
        "discovery": policy.challenger_discovery_mode,
        "calibration": policy.challenger_calibration_mode,
        "anneal": policy.challenger_anneal_mode,
        "freeze": policy.challenger_freeze_mode,
        "certify": policy.challenger_certify_mode,
        "publish": policy.challenger_publish_mode,
    }[policy.route_phase]



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
    runtime_hints: Mapping[str, ModelRuntimeHint] | None = None,
    control_lane: bool = False,
    deterministic_unresolved: bool = True,
) -> tuple[ModelRoute, ...]:
    policy = DEFAULT_ROUTING_POLICY if policy is None else policy
    _validate_routing_policy(policy)
    if type(min_context_tokens) is not int or not 1 <= min_context_tokens <= 2**31:
        raise ValueError("minimum model context must be a bounded positive integer")
    if type(sensitive) is not bool:
        raise ValueError("sensitive model routing must be boolean")
    if type(control_lane) is not bool or type(deterministic_unresolved) is not bool:
        raise ValueError("control-lane routing flags must be boolean")
    if control_lane and policy.deterministic_first and not deterministic_unresolved:
        return (ModelRoute(None, 0.0, ("deterministic route already resolved; tiny control model not invoked",), True),)
    hints = {} if runtime_hints is None else dict(runtime_hints)
    if len(hints) > MAX_MODEL_CANDIDATES:
        raise ValueError("model runtime hint budget exceeded")
    for key, hint in hints.items():
        if type(key) is not str or type(hint) is not ModelRuntimeHint or key != hint.model_id:
            raise ValueError("model runtime hints require exact typed model identities")
        validate_model_runtime_hint(hint)
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
        hint = hints.get(model.model_id)
        if hint is not None and hint.health == "unavailable":
            continue
        if control_lane:
            if hint is None or not hint.control_eligible:
                continue
            if policy.control_requires_certified and not hint.certified:
                continue
            if hint.queue_depth > policy.max_control_queue_depth:
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
        runtime_adjustment = 0.0
        runtime_explanation = "runtime=unobserved"
        if hint is not None:
            if hint.residency == "resident":
                runtime_adjustment += policy.resident_bonus
            elif hint.residency == "warm":
                runtime_adjustment += policy.warm_bonus
            elif hint.residency in {"cold", "exclusive_cold"}:
                runtime_adjustment -= policy.cold_penalty
            runtime_adjustment -= policy.queue_penalty * hint.queue_depth
            if hint.health == "degraded":
                runtime_adjustment -= policy.cold_penalty
            runtime_explanation = f"runtime={hint.residency}/{hint.health};queue={hint.queue_depth};certified={str(hint.certified).lower()}"
        score = round(
            policy.trait_weight * len(matched)
            + privacy
            - cost
            - latency
            - policy.cold_cost_weight * model.cold_cost
            + runtime_adjustment,
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
                    runtime_explanation,
                    f"control_lane={str(control_lane).lower()}",
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


def route_models(
    task_traits: Iterable[str],
    models: Iterable[ModelCapability],
    *,
    request_id: str,
    task_class: str,
    subject_ids: Iterable[str],
    policy_binding: ModelRoutingPolicyBinding,
    min_context_tokens: int = 1,
    sensitive: bool = False,
    runtime_hints: Mapping[str, ModelRuntimeHint] | None = None,
    route_signals: Mapping[str, object] | None = None,
    capacity_decisions: Mapping[str, object] | None = None,
    allow_capacity_fallback: bool = False,
    control_lane: bool = False,
    deterministic_unresolved: bool = True,
):
    """Build a hierarchical model route decision under deterministic PX policy.

    ``task_class``/``subject_ids`` form the outer admitted route.  The concrete
    model is the inner route.  Adaptive signals and capacity decisions are
    bounded evidence only; neither can grant execution or learning authority.
    """
    from .model_capacity import ModelCapacityDecision
    from .model_route_state import (
        AdaptiveRouteSignal,
        RouteCandidateRecord,
        build_route_decision,
        stable_sample,
    )

    if type(policy_binding) is not ModelRoutingPolicyBinding:
        raise ValueError("route_models requires a bound routing policy")
    policy_binding.__post_init__()
    policy = policy_binding.policy
    policy_sha256 = policy_binding.source_sha256
    policy_semantic_sha256 = policy_binding.semantic_sha256
    if type(allow_capacity_fallback) is not bool:
        raise ValueError("allow_capacity_fallback must be boolean")
    ranked = rank_models(
        task_traits,
        models,
        min_context_tokens=min_context_tokens,
        sensitive=sensitive,
        policy=policy,
        runtime_hints=runtime_hints,
        control_lane=control_lane,
        deterministic_unresolved=deterministic_unresolved,
    )
    if ranked and ranked[0].model_id is None:
        state = "deterministic_resolved" if control_lane and policy.deterministic_first and not deterministic_unresolved else "fallback_required"
        return build_route_decision(
            request_id=request_id, task_class=task_class, subject_ids=subject_ids,
            policy_sha256=policy_sha256, policy_semantic_sha256=policy_semantic_sha256, phase=policy.route_phase,
            candidates=(RouteCandidateRecord("px.no-model", 0.0, 0.0, 1, "unknown", (), ranked[0].explanation),),
            primary_model_id=None, challenger_model_id=None, dispatch_state=state,
            wait_reason=None, fallback_used=False,
        )

    signals = {} if route_signals is None else dict(route_signals)
    capacities = {} if capacity_decisions is None else dict(capacity_decisions)
    if len(signals) > MAX_MODEL_CANDIDATES or len(capacities) > MAX_MODEL_CANDIDATES:
        raise ValueError("model route evidence map budget exceeded")
    for key, signal in signals.items():
        if type(key) is not str or type(signal) is not AdaptiveRouteSignal or key != signal.model_id:
            raise ValueError("route signals require exact typed model identities")
    for key, decision in capacities.items():
        if type(key) is not str or type(decision) is not ModelCapacityDecision or key != decision.model_id:
            raise ValueError("capacity decisions require exact typed model identities")

    projected: list[tuple[float, ModelRoute, AdaptiveRouteSignal | None, ModelCapacityDecision | None, tuple[str, ...]]] = []
    for route in ranked:
        assert route.model_id is not None
        signal = signals.get(route.model_id)
        capacity = capacities.get(route.model_id)
        hint = ({} if runtime_hints is None else runtime_hints).get(route.model_id)
        signal_applicable = signal is not None and (not policy.requires_stable_route_evidence or signal.maturity == "stable")
        if signal_applicable:
            if hint is None or hint.fabric_generation_id is None:
                raise ValueError("stable adaptive route evidence requires exact runtime generation identity")
            if signal.model_generation_sha256 != hint.fabric_generation_id:
                raise ValueError("adaptive route evidence model generation does not match runtime hint")
        if capacity is not None and capacity.state == "deny":
            adjustment = 0.0
        else:
            adjustment = 0.0
            if signal_applicable and signal is not None:
                adjustment += policy.affinity_weight * signal.affinity
                adjustment += policy.quality_weight * signal.quality
                adjustment += policy.availability_weight * signal.availability
                adjustment -= policy.pressure_penalty * signal.pressure
            if capacity is not None and capacity.state == "admit":
                adjustment -= policy.pressure_penalty * capacity.pressure
        adjusted = round(route.score + adjustment, 6)
        evidence_items = list(signal.evidence_sha256 if signal is not None else ())
        if capacity is not None:
            evidence_items.append(capacity.decision_sha256)
        evidence = tuple(sorted(set(evidence_items)))
        projected.append((adjusted, route, signal, capacity, evidence))
    projected.sort(key=lambda row: (-row[0], row[1].model_id or ""))

    eligible_all = [row for row in projected if row[3] is None or row[3].state != "deny"]
    selection_pool = eligible_all[: policy.max_candidate_projection]
    record_pool = selection_pool if selection_pool else projected[: policy.max_candidate_projection]
    records = []
    for rank, (adjusted, route, signal, capacity, evidence) in enumerate(record_pool, 1):
        state = capacity.state if capacity is not None else "unknown"
        reasons = list(route.explanation)
        if signal is not None:
            reasons.append(f"route_evidence={signal.maturity};affinity={signal.affinity:.6f};quality={signal.quality:.6f};availability={signal.availability:.6f};pressure={signal.pressure:.6f}")
        if capacity is not None:
            reasons.append(f"capacity={capacity.state};pressure={capacity.pressure:.6f}")
        records.append(RouteCandidateRecord(route.model_id or "px.no-model", route.score, adjusted, rank, state, evidence, tuple(reasons)))

    eligible = selection_pool
    if not eligible:
        return build_route_decision(
            request_id=request_id, task_class=task_class, subject_ids=subject_ids,
            policy_sha256=policy_sha256, policy_semantic_sha256=policy_semantic_sha256, phase=policy.route_phase, candidates=tuple(records),
            primary_model_id=None, challenger_model_id=None, dispatch_state="fallback_required",
            wait_reason=None, fallback_used=False,
        )

    best = eligible[0]
    primary = best
    fallback_used = False
    if best[3] is not None and best[3].state == "wait":
        if allow_capacity_fallback:
            admitted = [row for row in eligible[1:] if row[3] is None or row[3].state == "admit"]
            if admitted:
                primary = admitted[0]
                fallback_used = True
            else:
                return build_route_decision(
                    request_id=request_id, task_class=task_class, subject_ids=subject_ids,
                    policy_sha256=policy_sha256, policy_semantic_sha256=policy_semantic_sha256, phase=policy.route_phase, candidates=tuple(records),
                    primary_model_id=best[1].model_id, challenger_model_id=None, dispatch_state="wait",
                    wait_reason="preferred_route_capacity_wait", fallback_used=False,
                )
        else:
            return build_route_decision(
                request_id=request_id, task_class=task_class, subject_ids=subject_ids,
                policy_sha256=policy_sha256, policy_semantic_sha256=policy_semantic_sha256, phase=policy.route_phase, candidates=tuple(records),
                primary_model_id=best[1].model_id, challenger_model_id=None, dispatch_state="wait",
                wait_reason="preferred_route_capacity_wait", fallback_used=False,
            )

    primary_id = primary[1].model_id
    admitted = [row for row in eligible if row[1].model_id != primary_id and (row[3] is None or row[3].state == "admit")]
    challenger_id = None
    if admitted:
        second = admitted[0]
        mode = _challenger_mode(policy)
        margin = primary[0] - second[0]
        if mode == "always":
            challenger_id = second[1].model_id
        elif mode == "threshold" and margin <= policy.challenger_score_margin:
            challenger_id = second[1].model_id
        elif mode == "sample" and stable_sample(f"{policy_sha256}:{policy_semantic_sha256}:{request_id}", rate=policy.challenger_sample_rate):
            challenger_id = second[1].model_id

    return build_route_decision(
        request_id=request_id, task_class=task_class, subject_ids=subject_ids,
        policy_sha256=policy_sha256, policy_semantic_sha256=policy_semantic_sha256, phase=policy.route_phase, candidates=tuple(records),
        primary_model_id=primary_id, challenger_model_id=challenger_id, dispatch_state="dispatch",
        wait_reason=None, fallback_used=fallback_used,
    )


def validate_model_runtime_hint(hint: ModelRuntimeHint) -> None:
    if type(hint) is not ModelRuntimeHint:
        raise ValueError("typed model runtime hint is required")
    for field in ("model_id", "residency", "health"):
        value = getattr(hint, field)
        if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 256:
            raise ValueError(f"model runtime hint {field} must be bounded nonempty text")
    if hint.residency not in {"resident", "warm", "cold", "exclusive_cold"}:
        raise ValueError("unsupported model runtime residency")
    if hint.health not in {"healthy", "degraded", "unavailable", "unknown"}:
        raise ValueError("unsupported model runtime health state")
    if type(hint.certified) is not bool or type(hint.control_eligible) is not bool:
        raise ValueError("model runtime certification/control flags must be boolean")
    if type(hint.queue_depth) is not int or not 0 <= hint.queue_depth <= 1_000_000:
        raise ValueError("model runtime queue depth must be a bounded nonnegative integer")
    if hint.profile_id is not None and (type(hint.profile_id) is not str or not hint.profile_id.strip() or len(hint.profile_id.encode("utf-8")) > 256):
        raise ValueError("model runtime profile ID must be bounded text or null")
    if hint.fabric_generation_id is not None:
        value = hint.fabric_generation_id
        if type(value) is not str or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError("model fabric generation must be lowercase SHA-256 or null")


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
