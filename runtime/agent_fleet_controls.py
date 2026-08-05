"""Project-scoped fleet readiness, inbox, and terminal adapter controls."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def evaluate_fleet_readiness(
    project_id: str,
    agents: Sequence[Mapping[str, object]],
    *,
    required_permissions: Sequence[str] = (),
    heartbeat_max_age_seconds: int = 120,
    total_cost_cap: float = 100.0,
) -> dict[str, object]:
    """Evaluate identities, scope, permissions, heartbeat, ownership, and cost."""
    if not project_id.strip():
        raise ValueError("project_id is required")
    if heartbeat_max_age_seconds < 1 or total_cost_cap < 0:
        raise ValueError("heartbeat and cost bounds must be non-negative")
    required = set(map(str, required_permissions))
    identities: set[str] = set()
    total_cost = 0.0
    rows: list[dict[str, object]] = []
    for agent in agents:
        identity = str(agent.get("agent_id", "")).strip()
        errors: list[str] = []
        if not identity or identity in identities:
            errors.append("identity missing or duplicated")
        identities.add(identity)
        if agent.get("project_id") != project_id:
            errors.append("cross-project agent rejected")
        permissions = set(map(str, agent.get("permissions", ())))
        missing = sorted(required - permissions)
        if missing:
            errors.append(f"required permissions missing: {missing}")
        if not str(agent.get("owner_id", "")).strip():
            errors.append("accountable owner missing")
        heartbeat_age = int(
            agent.get("heartbeat_age_seconds", heartbeat_max_age_seconds + 1)
        )
        if heartbeat_age > heartbeat_max_age_seconds:
            errors.append("heartbeat stale")
        cost = float(agent.get("reserved_cost", 0.0))
        if cost < 0:
            errors.append("reserved cost cannot be negative")
        total_cost += max(cost, 0.0)
        rows.append(
            {
                "agent_id": identity,
                "ready": not errors,
                "errors": errors,
                "heartbeat_age_seconds": heartbeat_age,
                "reserved_cost": cost,
            }
        )
    if total_cost > total_cost_cap:
        for row in rows:
            row["ready"] = False
            row["errors"].append("fleet cost cap exceeded")
    result = {
        "valid": bool(rows) and all(bool(row["ready"]) for row in rows),
        "project_id": project_id,
        "agents": rows,
        "agent_count": len(rows),
        "total_reserved_cost": total_cost,
        "total_cost_cap": total_cost_cap,
        "authority_granted": False,
    }
    result["readiness_sha256"] = _stable(result)
    return result


def admit_inbox_message(
    project_id: str,
    current_messages: Sequence[Mapping[str, object]],
    candidate: Mapping[str, object],
    *,
    allowed_senders: Sequence[str],
    max_messages: int = 100,
    max_bytes: int = 65_536,
) -> dict[str, object]:
    """Plan admission to a bounded inbox without mutating a store."""
    errors: list[str] = []
    if candidate.get("project_id") != project_id:
        errors.append("cross-project message rejected")
    sender = str(candidate.get("sender_id", "")).strip()
    if sender not in set(map(str, allowed_senders)):
        errors.append("sender is not allowed")
    message_id = str(candidate.get("message_id", "")).strip()
    if not message_id:
        errors.append("message identity missing")
    if any(str(item.get("message_id")) == message_id for item in current_messages):
        errors.append("duplicate message identity")
    encoded = json.dumps(candidate, sort_keys=True, ensure_ascii=False).encode("utf-8")
    existing_bytes = sum(
        len(json.dumps(item, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        for item in current_messages
    )
    if len(current_messages) + 1 > max_messages:
        errors.append("message count budget exceeded")
    if existing_bytes + len(encoded) > max_bytes:
        errors.append("inbox byte budget exceeded")
    return {
        "valid": not errors,
        "decision": "admit" if not errors else "reject",
        "project_id": project_id,
        "message_id": message_id,
        "sender_id": sender,
        "projected_message_count": len(current_messages) + (0 if errors else 1),
        "projected_bytes": existing_bytes + (0 if errors else len(encoded)),
        "errors": errors,
        "mutated": False,
        "authority_granted": False,
    }


def plan_terminal_session_action(
    adapter: Mapping[str, object],
    action: str,
    *,
    authority: Mapping[str, bool] | None = None,
) -> dict[str, object]:
    """Validate a terminal-session adapter and return a non-executing plan."""
    allowed_actions = {"inspect", "attach", "execute", "persist"}
    if action not in allowed_actions:
        raise ValueError("unsupported terminal session action")
    adapter_id = str(adapter.get("adapter_id", "")).strip()
    capabilities = set(map(str, adapter.get("capabilities", ())))
    permissions = dict(authority or {})
    required_authority = {
        "inspect": "read",
        "attach": "attach",
        "execute": "execute",
        "persist": "persist",
    }[action]
    errors = []
    if not adapter_id:
        errors.append("adapter identity missing")
    if action not in capabilities:
        errors.append("adapter does not declare the requested capability")
    if permissions.get(required_authority) is not True:
        errors.append(f"separate {required_authority} authority is required")
    if adapter.get("project_scoped") is not True:
        errors.append("adapter is not project scoped")
    return {
        "valid": not errors,
        "decision": "planned" if not errors else "denied",
        "adapter_id": adapter_id,
        "action": action,
        "required_authority": required_authority,
        "errors": errors,
        "executed": False,
        "attached": False,
        "persisted": False,
        "authority_granted": False,
    }
