"""Bounded metadata-only framework startup."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import shutil
import tomllib
from typing import Callable, Iterable, Mapping

from .config import BootstrapConfig, load_startup_config
from .registry import load_json, load_skill_catalog, navigation_index
from .skill_navigator import CapabilitySummary
from .state_invariants import assert_coordination_startup
from .tooling import startup_candidates


@dataclass(frozen=True, slots=True)
class StartupSnapshot:
    config: BootstrapConfig
    capabilities: tuple[CapabilitySummary, ...]
    policy_summaries: tuple[Mapping[str, object], ...]
    tools: tuple[tuple[str, str | None], ...]
    models: tuple[Mapping[str, object], ...]
    project_profile: Mapping[str, object]
    skill_catalog_metadata: tuple[Mapping[str, object], ...] = ()
    hydrated_skill_bodies: tuple[str, ...] = ()


def _probe(name: str, resolver: Callable[[str], str | None]) -> tuple[str, str | None]:
    try:
        return name, resolver(name)
    except OSError:
        return name, None


def bounded_startup(
    root: Path,
    project_root: Path,
    *,
    tool_names: Iterable[str] | None = None,
    tool_resolver: Callable[[str], str | None] = shutil.which,
    max_probe_workers: int = 4,
) -> StartupSnapshot:
    root = root.resolve()
    project_root = project_root.resolve()
    if max_probe_workers < 1 or max_probe_workers > 8:
        raise ValueError("max_probe_workers must be between 1 and 8")
    config = load_startup_config(root / "bootstrap" / "startup.toml")
    assert_coordination_startup(project_root)
    capabilities = tuple(navigation_index(root))
    if len(capabilities) > config.budget.max_initial_registry_records:
        raise ValueError("capability metadata exceeds startup budget")
    policy_path = root / "policies" / "policy_index.json"
    policy_payload = (
        load_json(policy_path) if policy_path.is_file() else {"policies": []}
    )
    raw_policies = policy_payload.get("policies")
    policy_summaries = (
        tuple(raw_policies)
        if isinstance(raw_policies, list)
        else tuple(
            {"id": policy_id}
            for policy_id in policy_payload.get("startup_policy_ids", ())
        )
    )
    if len(policy_summaries) > config.budget.max_initial_policy_summaries:
        raise ValueError("policy summaries exceed startup budget")
    model_path = root / "registry" / "models.json"
    models = (
        tuple(load_json(model_path).get("models", ())) if model_path.is_file() else ()
    )
    profile_path = project_root / ".engineering-bootstrap" / "project.toml"
    profile = (
        tomllib.loads(profile_path.read_text(encoding="utf-8"))
        if profile_path.is_file()
        else {"status": "unconfigured"}
    )
    names = (
        startup_candidates(root)
        if tool_names is None
        else tuple(sorted(set(tool_names)))
    )
    with ThreadPoolExecutor(
        max_workers=min(max_probe_workers, max(1, len(names)))
    ) as pool:
        tools = tuple(sorted(pool.map(lambda name: _probe(name, tool_resolver), names)))
    catalog_path = root / "registry" / "skill_catalog.toml"
    skill_metadata = (
        tuple(load_skill_catalog(root).get("skills", ()))
        if catalog_path.is_file()
        else ()
    )
    if len(skill_metadata) > config.budget.max_initial_registry_records:
        raise ValueError("skill metadata exceeds startup budget")
    return StartupSnapshot(
        config, capabilities, policy_summaries, tools, models, profile, skill_metadata
    )
