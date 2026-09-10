"""Bounded metadata-only framework startup."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
import shutil
import math
import time
from typing import Callable, Iterable, Mapping

from .config import (
    BootstrapConfig,
    load_startup_config,
    load_bounded_toml,
    MAX_STARTUP_METADATA_BYTES,
)
from .registry import load_skill_catalog, navigation_index
from .skill_navigator import CapabilitySummary
from .state_invariants import assert_coordination_startup
from .tooling import startup_candidates, bounded_tool_names, resolve_tool
from .world_state import load_world_state_for_startup
from .archive_io import reject_path_links
from .skill_inputs import (
    MAX_DESCRIPTORS,
    _text,
    _relative,
    _deadline,
    _file,
    load_metadata_object,
)
from .models import ModelCapability, MAX_MODEL_CANDIDATES, validate_model_capability


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
    world_state: Mapping[str, object] | None = None
    lazy_hydration: tuple[str, ...] = ()


def _probe(name: str, resolver: Callable[[str], str | None]) -> tuple[str, str | None]:
    return name, resolve_tool(name, resolver)


def _optional_metadata(
    root: Path, relative: str, default: dict, deadline: float
) -> dict:
    path = root / relative
    reject_path_links(path)
    return (
        load_metadata_object(root, relative, deadline=deadline)
        if path.exists()
        else default
    )


def _metadata_rows(value: object, maximum: int, name: str) -> list[dict]:
    if (
        type(value) is not list
        or len(value) > maximum
        or any(type(row) is not dict for row in value)
    ):
        raise ValueError(f"{name} requires a bounded array of objects")
    return value


def _policies(payload: dict, maximum: int) -> tuple[Mapping[str, object], ...]:
    if "policies" in payload:
        rows = _metadata_rows(payload["policies"], maximum, "policy summaries")
    else:
        ids = payload.get("startup_policy_ids")
        if type(ids) is not list or len(ids) > maximum:
            raise ValueError("policy metadata requires bounded startup identities")
        rows = [{"id": _text(identity, "policy identity")} for identity in ids]
    seen = set()
    for row in rows:
        identity = _text(row.get("id"), "policy identity")
        if identity in seen:
            raise ValueError("duplicate policy summary identity")
        seen.add(identity)
        if "summary" in row:
            _text(row["summary"], "policy summary", 4096)
        if "body" in row:
            _relative(row["body"])
    return tuple(rows)


def _models(payload: dict) -> tuple[Mapping[str, object], ...]:
    rows = _metadata_rows(payload.get("models"), MAX_MODEL_CANDIDATES, "models")
    seen = set()
    for row in rows:
        if set(row) != set(ModelCapability.__dataclass_fields__):
            raise ValueError("model metadata requires exactly its declared fields")
        model = ModelCapability(**row)
        validate_model_capability(model)
        if model.model_id in seen:
            raise ValueError("duplicate model metadata identity")
        seen.add(model.model_id)
    return tuple(rows)


def bounded_startup(
    root: Path,
    project_root: Path,
    *,
    tool_names: Iterable[str] | None = None,
    tool_resolver: Callable[[str], str | None] = shutil.which,
    max_probe_workers: int = 4,
    current_source_revision: str | None = None,
    max_startup_seconds: float = 60.0,
) -> StartupSnapshot:
    """Bound metadata and cooperative work; callbacks must settle in their owner.

    A callback or filesystem call can block inside Python/OS code. This library
    rejects elapsed work after it returns; physical termination belongs to the
    admitted process owner, not to an abandoned helper thread.
    """
    if type(max_probe_workers) is not int or not 1 <= max_probe_workers <= 8:
        raise ValueError("max_probe_workers must be an integer between 1 and 8")
    if (
        type(max_startup_seconds) not in (int, float)
        or not 0 < max_startup_seconds <= 300
        or not math.isfinite(max_startup_seconds)
    ):
        raise ValueError("startup duration must be positive, finite and bounded")
    if not callable(tool_resolver):
        raise ValueError("tool resolver must be callable")
    deadline = time.monotonic() + max_startup_seconds
    reject_path_links(root)
    reject_path_links(project_root)
    root = root.resolve()
    project_root = project_root.resolve()
    # Caller intake is admitted before metadata acquisition or resolver calls.
    names = (
        None
        if tool_names is None
        else bounded_tool_names(tool_names, deadline=deadline)
    )
    world = load_world_state_for_startup(
        root, current_source_revision=current_source_revision
    )
    config = load_startup_config(root / "bootstrap" / "startup.toml")
    _deadline(deadline)
    assert_coordination_startup(project_root)
    _deadline(deadline)
    maximum = min(MAX_DESCRIPTORS, config.budget.max_initial_registry_records)
    capabilities = tuple(navigation_index(root, max_records=maximum, deadline=deadline))
    policy_payload = _optional_metadata(
        root, "policies/policy_index.json", {"policies": []}, deadline
    )
    policy_summaries = _policies(
        policy_payload, min(256, config.budget.max_initial_policy_summaries)
    )
    models = _models(
        _optional_metadata(root, "registry/models.json", {"models": []}, deadline)
    )
    profile_path = project_root / ".engineering-bootstrap" / "project.toml"
    reject_path_links(profile_path)
    if profile_path.exists():
        _, info = _file(project_root, ".engineering-bootstrap/project.toml")
        if info.st_size > MAX_STARTUP_METADATA_BYTES:
            raise ValueError("project profile metadata byte budget exceeded")
        profile = load_bounded_toml(profile_path)
    else:
        profile = {"status": "unconfigured"}
    catalog_path = root / "registry" / "skill_catalog.toml"
    reject_path_links(catalog_path)
    skill_metadata = (
        tuple(
            load_skill_catalog(root, max_records=maximum, deadline=deadline)["skills"]
        )
        if catalog_path.exists()
        else ()
    )
    if names is None:
        names = startup_candidates(root, deadline=deadline)
    _deadline(deadline)

    def probe(name):
        _deadline(deadline)
        result = _probe(name, tool_resolver)
        _deadline(deadline)
        return result

    if names:
        with ThreadPoolExecutor(max_workers=min(max_probe_workers, len(names))) as pool:
            tools = tuple(sorted(pool.map(probe, names)))
    else:
        tools = ()
    _deadline(deadline)
    return StartupSnapshot(
        config,
        capabilities,
        policy_summaries,
        tools,
        models,
        profile,
        skill_metadata,
        (),
        world.get("world_state"),
        tuple(map(str, world.get("hydrate", ()))),
    )
