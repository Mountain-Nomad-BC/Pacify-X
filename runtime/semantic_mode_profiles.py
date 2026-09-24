"""Composable semantic operating modes with explicit conflict rules."""
from __future__ import annotations
from .semantic_integration_types import IntegrationEffect, ModeProfile

# PROCESS is intentionally present in read/planning modes where PX-owned language
# services may need process custody.  Exposure is still not process authority.
_MODES = {
    "planning": ModeProfile("planning", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.PROCESS), mutually_exclusive=("editing",)),
    "editing": ModeProfile("editing", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.WRITE, IntegrationEffect.PROCESS), mutually_exclusive=("planning",)),
    "query-projects": ModeProfile("query-projects", (IntegrationEffect.READ, IntegrationEffect.PROCESS), cross_project=True),
    "memory-aware": ModeProfile("memory-aware", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.PROCESS), memory_enabled=True),
    "no-memory": ModeProfile("no-memory", tuple(IntegrationEffect), memory_enabled=False, excluded_operations=("semantic.memory.integrity", "semantic.memory.plan_relocation", "semantic.memory.apply_relocation")),
    "one-shot": ModeProfile("one-shot", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.PROCESS)),
}


def mode_profile(name: str) -> ModeProfile:
    try:
        return _MODES[name]
    except KeyError as exc:
        raise KeyError(f"unknown semantic integration mode {name!r}") from exc


def validate_modes(names: tuple[str, ...]) -> tuple[ModeProfile, ...]:
    if type(names) is not tuple:
        raise TypeError("modes must be a tuple")
    if len(set(names)) != len(names):
        raise ValueError("duplicate modes are not allowed")
    profiles = tuple(mode_profile(name) for name in names)
    selected = set(names)
    for profile in profiles:
        conflict = selected.intersection(profile.mutually_exclusive)
        if conflict:
            raise ValueError(f"mode {profile.name!r} conflicts with {sorted(conflict)!r}")
    return profiles


def mode_names() -> tuple[str, ...]:
    return tuple(sorted(_MODES))
