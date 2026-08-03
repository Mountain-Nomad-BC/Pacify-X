"""Validated loading of bounded bootstrap configuration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class StartupBudget:
    max_initial_registry_records: int
    max_initial_policy_summaries: int
    max_active_capabilities: int
    max_context_items: int
    max_context_bytes: int
    max_planning_seconds: int


@dataclass(frozen=True, slots=True)
class LifecycleConfig:
    checkpoint_after_each_step: bool
    unload_after_step: bool
    max_retries: int
    retry_requires_new_evidence: bool


@dataclass(frozen=True, slots=True)
class BootstrapConfig:
    bootstrap_id: str
    version: str
    mode: str
    fail_closed: bool
    model_agnostic: bool
    require_explicit_project_root: bool
    allow_external_paths: bool
    budget: StartupBudget
    deferred_by_default: frozenset[str]
    default_effect: str
    approval_required: frozenset[str]
    evidence_required: frozenset[str]
    lifecycle: LifecycleConfig


def _positive(table: dict[str, object], name: str) -> int:
    value = table.get(name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"startup_budget.{name} must be a positive integer")
    return value


def load_startup_config(path: Path) -> BootstrapConfig:
    """Load startup TOML and reject unsafe or ambiguous settings."""
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    bootstrap = data.get("bootstrap", {})
    roots = data.get("trusted_roots", {})
    budget = data.get("startup_budget", {})
    deferred = data.get("deferred_by_default", {})
    effects = data.get("effects", {})
    lifecycle = data.get("lifecycle", {})
    if bootstrap.get("fail_closed") is not True:
        raise ValueError("bootstrap.fail_closed must be true")
    if bootstrap.get("model_agnostic") is not True:
        raise ValueError("bootstrap.model_agnostic must be true")
    if roots.get("require_explicit_project_root") is not True:
        raise ValueError("trusted_roots.require_explicit_project_root must be true")
    if roots.get("allow_external_paths") is not False:
        raise ValueError("trusted_roots.allow_external_paths must be false")
    if lifecycle.get("checkpoint_after_each_step") is not True:
        raise ValueError("lifecycle.checkpoint_after_each_step must be true")
    if lifecycle.get("unload_after_step") is not True:
        raise ValueError("lifecycle.unload_after_step must be true")
    max_retries = lifecycle.get("max_retries")
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("lifecycle.max_retries must be a non-negative integer")
    enabled_deferred = frozenset(name for name, value in deferred.items() if value is True)
    if set(deferred) != enabled_deferred:
        raise ValueError("all deferred_by_default entries must be true")
    return BootstrapConfig(
        bootstrap_id=str(bootstrap.get("id", "")),
        version=str(bootstrap.get("version", "")),
        mode=str(bootstrap.get("mode", "")),
        fail_closed=True,
        model_agnostic=True,
        require_explicit_project_root=True,
        allow_external_paths=False,
        budget=StartupBudget(
            max_initial_registry_records=_positive(budget, "max_initial_registry_records"),
            max_initial_policy_summaries=_positive(budget, "max_initial_policy_summaries"),
            max_active_capabilities=_positive(budget, "max_active_capabilities"),
            max_context_items=_positive(budget, "max_context_items"),
            max_context_bytes=_positive(budget, "max_context_bytes"),
            max_planning_seconds=_positive(budget, "max_planning_seconds"),
        ),
        deferred_by_default=enabled_deferred,
        default_effect=str(effects.get("default", "")),
        approval_required=frozenset(effects.get("approval_required", ())),
        evidence_required=frozenset(effects.get("evidence_required", ())),
        lifecycle=LifecycleConfig(
            checkpoint_after_each_step=True,
            unload_after_step=True,
            max_retries=max_retries,
            retry_requires_new_evidence=lifecycle.get("retry_requires_new_evidence") is True,
        ),
    )
