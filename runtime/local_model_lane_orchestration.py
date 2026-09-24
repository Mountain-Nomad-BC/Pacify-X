"""Local-model lane orchestration: resident librarian lane versus on-demand usage lane.

PX owns this decision. The two local models have distinct, non-interchangeable roles:

* ``qwen35-4b-operator`` (``control`` lane) -- **resident, semi-autonomous librarian**.
  Retrieval, knowledge navigation, skill/action selection, context assembly, PX
  self-maintenance (index/graph/memory upkeep), and trigger/schedule-driven upkeep.
  Cancellation-correct, bounded, always available, CPU-first so it never competes with
  the deep worker for VRAM.

* ``qwen3-30b-a3b-deep`` (``deep`` lane) -- **on-demand usage worker**. Heavy coding,
  reasoning, synthesis. Loaded only when a task actually requires it, held under an
  exclusive resource lease, and unloaded/reconciled afterwards. Never resident by
  default and never autoloaded.

This module is the deterministic authority: it maps a task shape plus the current
resource/lifecycle state to exactly one lane decision, with a stated reason and the
evidence required to justify it. No model narrates its own promotion.

Binding: ``registry/workflow_execution_bindings.json`` ->
``runtime.local_model_lane_orchestration:plan_lane_decision``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

RESIDENT_LANE = "control"
USAGE_LANE = "deep"
LANES = (RESIDENT_LANE, USAGE_LANE)

# The resource scheduler models concurrency as light/heavy lanes. The resident librarian
# is always a light lane (bounded, never blocks a heavy run); the on-demand usage worker
# is the single heavy lane held under an exclusive lease.
SCHEDULER_LANE = {RESIDENT_LANE: "light", USAGE_LANE: "heavy"}

# Task shapes the resident librarian may own without escalation.
LIBRARIAN_OWNED_TRAITS = frozenset(
    {
        "px_internal_operator",
        "skill_query",
        "knowledge_query",
        "memory_query",
        "context_assembly",
        "workflow_dispatch_planning",
        "learning_trigger_planning",
        "graph_map_update_planning",
        "bounded_transformation",
        "code_intent",
        "retrieval_assist",
        "tool_selection",
        "classification",
        "route_classification",
        "query_normalization",
        "semantic_disambiguation",
        "index_maintenance",
        "graph_maintenance",
        "memory_maintenance",
    }
)

# Task shapes that require the on-demand usage worker.
USAGE_LANE_TRAITS = frozenset(
    {
        "deep_reasoning",
        "architecture",
        "difficult_coding",
        "long_synthesis",
        "complex_code",
        "reasoning",
        "long_context",
    }
)

# Triggers under which the resident librarian may act semi-autonomously. Each maps to
# a deterministic condition the scheduler can evaluate; the model itself never decides
# whether the trigger fired.
SCHEDULED_LIBRARIAN_TRIGGERS = (
    "project-map-stale",
    "nsai-index-stale",
    "knowledge-index-stale",
    "memory-review-due",
    "evidence-reconciliation-due",
    "capability-index-stale",
    "session-context-refresh",
)

MAX_TRAITS = 64
MAX_TEXT = 256


@dataclass(frozen=True, slots=True)
class LaneDecision:
    """One deterministic lane decision with its justification."""

    lane: str
    model_id: str
    profile_id: str
    residency: str
    requires_lease: bool
    autoload_allowed: bool
    reason: str
    trigger: str | None
    evidence: tuple[str, ...] = ()
    escalation: str | None = None

    def as_mapping(self) -> dict[str, object]:
        return {
            "lane": self.lane,
            "scheduler_lane": SCHEDULER_LANE[self.lane],
            "model_id": self.model_id,
            "profile_id": self.profile_id,
            "residency": self.residency,
            "requires_lease": self.requires_lease,
            "autoload_allowed": self.autoload_allowed,
            "reason": self.reason,
            "trigger": self.trigger,
            "evidence": list(self.evidence),
            "escalation": self.escalation,
        }


def _bounded_text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > MAX_TEXT:
        raise ValueError(f"{name} must be bounded nonempty text")
    return value.strip()


def _bounded_traits(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if type(value) not in (list, tuple):
        raise ValueError("task traits must be a bounded sequence")
    if len(value) > MAX_TRAITS:
        raise ValueError("task traits exceed the bounded count")
    return tuple(_bounded_text(item, "trait") for item in value)


def load_lane_models(root: Path) -> dict[str, dict[str, object]]:
    """Resolve each lane's model + profile from the canonical portfolio/profiles."""

    portfolio = json.loads((root / "models/model-portfolio.json").read_text(encoding="utf-8"))
    profiles = json.loads((root / "models/runtime-profiles.json").read_text(encoding="utf-8"))
    by_lane: dict[str, dict[str, object]] = {}
    profile_by_id = {row["profile_id"]: row for row in profiles["profiles"]}
    for model in portfolio["models"]:
        lane = model.get("lane")
        if lane not in LANES or lane in by_lane:
            continue
        profile = profile_by_id.get(model.get("default_profile_id"))
        if profile is None:
            continue
        by_lane[lane] = {
            "model_id": model["model_id"],
            "profile_id": profile["profile_id"],
            "residency": profile["residency"],
            "context_tokens": profile["context_tokens"],
            "max_output_tokens": profile["max_output_tokens"],
            "gpu_layers": profile["gpu_layers"],
            "exclusive_heavy": profile["exclusive_heavy"],
        }
    missing = [lane for lane in LANES if lane not in by_lane]
    if missing:
        raise ValueError(f"lane models are unresolved: {missing}")
    return by_lane


def plan_lane_decision(
    root: Path,
    *,
    traits: Iterable[str] = (),
    trigger: str | None = None,
    requested_depth: str | None = None,
    deep_available: bool = True,
    deep_lease_free: bool = True,
) -> LaneDecision:
    """Choose exactly one lane for a request, or fail closed.

    Deterministic precedence:

    1. An explicit deep signal (trait, or ``requested_depth == 'deep'``) escalates to the
       usage lane **only** when it is available and could hold a lease; otherwise PX
       reports the concrete blocker instead of silently downgrading.
    2. A scheduled/triggered maintenance or librarian-owned shape stays on the resident lane.
    3. Anything else defaults to the resident librarian lane (cheapest correct owner).
    """

    root = root.resolve(strict=True)
    task_traits = _bounded_traits(list(traits))
    if trigger is not None:
        trigger = _bounded_text(trigger, "trigger")
        if trigger not in SCHEDULED_LIBRARIAN_TRIGGERS:
            raise ValueError(f"unknown librarian trigger: {trigger}")
    if requested_depth is not None:
        requested_depth = _bounded_text(requested_depth, "requested_depth")
        if requested_depth not in {"shallow", "standard", "deep"}:
            raise ValueError("requested_depth must be 'shallow', 'standard', or 'deep'")
    for name, value in (("deep_available", deep_available), ("deep_lease_free", deep_lease_free)):
        if type(value) is not bool:
            raise ValueError(f"{name} must be boolean")

    models = load_lane_models(root)
    resident = models[RESIDENT_LANE]
    usage = models[USAGE_LANE]

    wants_deep = bool(set(task_traits) & USAGE_LANE_TRAITS) or requested_depth == "deep"
    if wants_deep:
        blockers = []
        if not deep_available:
            blockers.append("usage-lane-unavailable")
        if not deep_lease_free:
            blockers.append("usage-lane-lease-held")
        if blockers and requested_depth == "deep":
            # An explicitly deep request must not be silently downgraded.
            return LaneDecision(
                lane=USAGE_LANE,
                model_id=str(usage["model_id"]),
                profile_id=str(usage["profile_id"]),
                residency="cold",
                requires_lease=True,
                autoload_allowed=False,
                reason="explicit deep request cannot be served: " + ", ".join(blockers),
                trigger=trigger,
                evidence=tuple(blockers),
                escalation="blocked",
            )
        if not blockers:
            return LaneDecision(
                lane=USAGE_LANE,
                model_id=str(usage["model_id"]),
                profile_id=str(usage["profile_id"]),
                residency="cold",
                requires_lease=True,
                autoload_allowed=False,
                reason="task requires the on-demand usage worker",
                trigger=trigger,
                evidence=tuple(sorted(set(task_traits) & USAGE_LANE_TRAITS)) or ("requested_depth=deep",),
                escalation="usage-lane",
            )
        # A non-explicit deep-ish task may fall back to the resident lane, stated plainly.
        return LaneDecision(
            lane=RESIDENT_LANE,
            model_id=str(resident["model_id"]),
            profile_id=str(resident["profile_id"]),
            residency=str(resident["residency"]),
            requires_lease=False,
            autoload_allowed=True,
            reason="usage lane blocked; resident librarian lane handles the bounded request",
            trigger=trigger,
            evidence=tuple(blockers),
            escalation="fallback-to-resident",
        )

    if trigger is not None:
        return LaneDecision(
            lane=RESIDENT_LANE,
            model_id=str(resident["model_id"]),
            profile_id=str(resident["profile_id"]),
            residency=str(resident["residency"]),
            requires_lease=False,
            autoload_allowed=True,
            reason=f"scheduled librarian maintenance: {trigger}",
            trigger=trigger,
            evidence=("scheduled-trigger",),
        )

    owned = tuple(sorted(set(task_traits) & LIBRARIAN_OWNED_TRAITS))
    return LaneDecision(
        lane=RESIDENT_LANE,
        model_id=str(resident["model_id"]),
        profile_id=str(resident["profile_id"]),
        residency=str(resident["residency"]),
        requires_lease=False,
        autoload_allowed=True,
        reason="resident librarian lane owns this request",
        trigger=trigger,
        evidence=owned or ("default-resident-owner",),
    )


def validate_lane_orchestration(root: Path) -> dict[str, object]:
    """Executable validator for orchestration/workflows/local-model-lane-orchestration.yaml."""

    root = root.resolve(strict=True)
    errors: list[str] = []
    models = load_lane_models(root)
    resident, usage = models[RESIDENT_LANE], models[USAGE_LANE]
    if str(resident["residency"]) != "resident":
        errors.append("resident librarian lane must declare residency 'resident'")
    if str(usage["residency"]) in {"resident"}:
        errors.append("usage lane must be warm or cold, never resident")
    if not bool(usage["exclusive_heavy"]):
        errors.append("usage lane must hold an exclusive resource lease")
    # Both lanes must resolve to distinct, hash-bound models.
    if resident["model_id"] == usage["model_id"]:
        errors.append("resident and usage lanes must not share one model")
    # Deterministic decision smoke cases.
    cases = (
        {"traits": ["knowledge_query"], "expect": RESIDENT_LANE},
        {"traits": [], "trigger": "nsai-index-stale", "expect": RESIDENT_LANE},
        {"traits": ["deep_reasoning"], "expect": USAGE_LANE},
    )
    for case in cases:
        decision = plan_lane_decision(
            root,
            traits=case["traits"],
            trigger=case.get("trigger"),
        )
        if decision.lane != case["expect"]:
            errors.append(f"lane decision mismatch for {case['traits'] or case.get('trigger')}")
    return {
        "schema_version": "px.local-model-lane-orchestration/1.0",
        "valid": not errors,
        "lanes": {lane: models[lane] for lane in LANES},
        "triggers": list(SCHEDULED_LIBRARIAN_TRIGGERS),
        "errors": errors,
    }