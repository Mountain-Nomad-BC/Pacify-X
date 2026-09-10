"""Validated loading of bounded bootstrap configuration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from .archive_io import reject_path_links
from .json_io import read_bounded_bytes, validate_json_value

MAX_STARTUP_METADATA_BYTES = 65536
MAX_STARTUP_INTEGER = 2**31 - 1
DEFERRED_CAPABILITIES = frozenset(
    {
        "repository_graph",
        "embeddings",
        "browser",
        "network",
        "tool_installation",
        "service_start",
        "full_policy_text",
        "skill_packages",
    }
)


def load_bounded_toml(path: Path) -> dict[str, object]:
    """Acquire one bounded original-path image before parsing startup metadata."""
    reject_path_links(path)
    if not path.is_file():
        raise ValueError("startup metadata requires a regular file")
    raw = read_bounded_bytes(path, max_bytes=MAX_STARTUP_METADATA_BYTES)
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError) as error:
        raise ValueError("invalid startup metadata TOML") from error
    validate_json_value(data, max_depth=8, max_nodes=1024)
    return data


def _table(value: object, fields: set[str] | frozenset[str], name: str) -> dict:
    if type(value) is not dict or len(value) != len(fields) or set(value) != fields:
        raise ValueError(f"{name} requires exactly its declared fields")
    return value


def _metadata_text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 256
        or len(value.encode("utf-8")) > 256
        or any(ord(c) < 32 for c in value)
    ):
        raise ValueError(f"{name} must be bounded nonempty text")
    return value


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
    if type(value) is not int or not 1 <= value <= MAX_STARTUP_INTEGER:
        raise ValueError(f"startup_budget.{name} must be a bounded positive integer")
    return value


def load_startup_config(path: Path) -> BootstrapConfig:
    """Load startup TOML and reject unsafe or ambiguous settings."""
    from .admission_controller import KNOWN_EFFECTS

    data = _table(
        load_bounded_toml(path),
        {
            "bootstrap",
            "trusted_roots",
            "startup_budget",
            "deferred_by_default",
            "effects",
            "lifecycle",
        },
        "startup",
    )
    bootstrap = _table(
        data["bootstrap"],
        {"id", "version", "mode", "fail_closed", "model_agnostic"},
        "bootstrap",
    )
    roots = _table(
        data["trusted_roots"],
        {"require_explicit_project_root", "allow_external_paths"},
        "trusted_roots",
    )
    budget = _table(
        data["startup_budget"],
        set(StartupBudget.__dataclass_fields__),
        "startup_budget",
    )
    deferred = _table(
        data["deferred_by_default"], DEFERRED_CAPABILITIES, "deferred_by_default"
    )
    effects = _table(
        data["effects"],
        {"default", "approval_required", "evidence_required"},
        "effects",
    )
    lifecycle = _table(
        data["lifecycle"], set(LifecycleConfig.__dataclass_fields__), "lifecycle"
    )
    for field in ("id", "version", "mode"):
        _metadata_text(bootstrap[field], "bootstrap." + field)
    if type(effects["default"]) is not str or effects["default"] not in KNOWN_EFFECTS:
        raise ValueError("effects.default must use the admitted effect vocabulary")
    for field in ("approval_required", "evidence_required"):
        values = effects[field]
        if type(values) is not list or len(values) > len(KNOWN_EFFECTS):
            raise ValueError(f"effects.{field} must be a bounded effect list")
        if any(
            type(value) is not str or value not in KNOWN_EFFECTS for value in values
        ):
            raise ValueError(f"effects.{field} contains an unknown effect")
        if len(set(values)) != len(values):
            raise ValueError(f"effects.{field} contains duplicate effects")
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
    if lifecycle["retry_requires_new_evidence"] is not True:
        raise ValueError("lifecycle.retry_requires_new_evidence must be true")
    max_retries = lifecycle.get("max_retries")
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or not 0 <= max_retries <= MAX_STARTUP_INTEGER
    ):
        raise ValueError("lifecycle.max_retries must be a non-negative integer")
    enabled_deferred = frozenset(
        name for name, value in deferred.items() if value is True
    )
    if set(deferred) != enabled_deferred:
        raise ValueError("all deferred_by_default entries must be true")
    return BootstrapConfig(
        bootstrap_id=bootstrap["id"],
        version=bootstrap["version"],
        mode=bootstrap["mode"],
        fail_closed=True,
        model_agnostic=True,
        require_explicit_project_root=True,
        allow_external_paths=False,
        budget=StartupBudget(
            max_initial_registry_records=_positive(
                budget, "max_initial_registry_records"
            ),
            max_initial_policy_summaries=_positive(
                budget, "max_initial_policy_summaries"
            ),
            max_active_capabilities=_positive(budget, "max_active_capabilities"),
            max_context_items=_positive(budget, "max_context_items"),
            max_context_bytes=_positive(budget, "max_context_bytes"),
            max_planning_seconds=_positive(budget, "max_planning_seconds"),
        ),
        deferred_by_default=enabled_deferred,
        default_effect=effects["default"],
        approval_required=frozenset(effects["approval_required"]),
        evidence_required=frozenset(effects["evidence_required"]),
        lifecycle=LifecycleConfig(
            checkpoint_after_each_step=True,
            unload_after_step=True,
            max_retries=max_retries,
            retry_requires_new_evidence=True,
        ),
    )
