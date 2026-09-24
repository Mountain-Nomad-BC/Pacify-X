"""Explicit client-context profiles.

Profiles describe what may be exposed to a client.  They never grant execution
authority: effect grants, policy, repository claims, and executor ownership remain
separate PX controls.
"""
from __future__ import annotations
from .semantic_integration_types import ContextProfile, IntegrationEffect

_CONTEXTS = {
    "codex-host": ContextProfile("codex-host", "codex", tuple(IntegrationEffect), "R3", False, True, True),
    "chatgpt": ContextProfile("chatgpt", "chat", (IntegrationEffect.READ, IntegrationEffect.PLAN), "R1", False, True, True),
    "claude-code": ContextProfile("claude-code", "coding-agent", tuple(IntegrationEffect), "R3", False, True, True),
    "vscode": ContextProfile("vscode", "ide", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.WRITE, IntegrationEffect.PROCESS), "R3", True, False, True),
    # The resident tiny model is a governed internal operator: librarian/concierge/grunt.
    # PROCESS is exposed so it can invoke PX-owned read tooling (for example an admitted
    # LSP service).  WRITE remains absent; learning/map/graph updates must go through
    # separately admitted PX operations and their effect/authority gates.
    "local-model": ContextProfile("local-model", "local-model", (IntegrationEffect.READ, IntegrationEffect.PLAN, IntegrationEffect.PROCESS), "R1", False, True, True),
    "read-only-agent": ContextProfile("read-only-agent", "agent", (IntegrationEffect.READ,), "R0", False, True, True),
}


def context_profile(name: str) -> ContextProfile:
    try:
        return _CONTEXTS[name]
    except KeyError as exc:
        raise KeyError(f"unknown semantic integration context {name!r}") from exc


def context_names() -> tuple[str, ...]:
    return tuple(sorted(_CONTEXTS))
