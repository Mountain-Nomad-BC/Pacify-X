"""Project-scoped fleet readiness, inbox, and durable agent-session controls."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Mapping, Sequence
import uuid

from .file_lock import FileLock
from .instrumentation_sdk import SDK_VERSION, build_operation_event
from .operational_event_bus import OperationalEventBus
from .wal_transaction import JsonArtifact, JsonWal


SESSION_SCHEMA_VERSION = "px.agent-session/1.0"
REGISTRY_SCHEMA_VERSION = "px.agent-session-registry/1.0"
SESSION_STATES = frozenset(
    {"active", "waiting", "verifying", "blocked", "recovering", "stale"}
)
SESSION_TRANSITIONS = {
    "active": frozenset({"waiting", "verifying", "blocked", "stale"}),
    "waiting": frozenset({"active", "verifying", "blocked", "stale"}),
    "verifying": frozenset({"active", "waiting", "blocked", "stale"}),
    "blocked": frozenset({"recovering", "stale"}),
    "recovering": frozenset(
        {"active", "waiting", "verifying", "blocked", "stale"}
    ),
    "stale": frozenset({"recovering"}),
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def _stable(value: object) -> str:
    rendered = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _required_text(value: object, field: str) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _parse_timestamp(value: object, field: str = "timestamp") -> datetime:
    text = _required_text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{field} must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _timestamp(value: object, field: str = "timestamp") -> str:
    return _parse_timestamp(value, field).isoformat()


def _finite_cost(value: object) -> float:
    try:
        cost = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("reserved cost must be a finite number") from error
    if not math.isfinite(cost):
        raise ValueError("reserved cost must be a finite number")
    return cost


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
    if (
        heartbeat_max_age_seconds < 1
        or not math.isfinite(float(total_cost_cap))
        or total_cost_cap < 0
    ):
        raise ValueError("heartbeat and cost bounds must be non-negative")
    required = set(map(str, required_permissions))
    identity_counts: dict[str, int] = {}
    for agent in agents:
        identity = str(agent.get("agent_id", "")).strip()
        if identity:
            identity_counts[identity] = identity_counts.get(identity, 0) + 1
    total_cost = 0.0
    rows: list[dict[str, object]] = []
    for agent in agents:
        identity = str(agent.get("agent_id", "")).strip()
        errors: list[str] = []
        if not identity or identity_counts.get(identity, 0) > 1:
            errors.append("identity missing or duplicated")
        if agent.get("project_id") != project_id:
            errors.append("cross-project agent rejected")
        raw_permissions = agent.get("permissions")
        if not isinstance(raw_permissions, (list, tuple, set, frozenset)):
            permissions: set[str] = set()
            errors.append("permissions declaration missing or invalid")
        else:
            permissions = {str(item).strip() for item in raw_permissions if str(item).strip()}
        missing = sorted(required - permissions)
        if missing:
            errors.append(f"required permissions missing: {missing}")
        if not str(agent.get("owner_id", "")).strip():
            errors.append("accountable owner missing")
        try:
            heartbeat_age = int(
                agent.get("heartbeat_age_seconds", heartbeat_max_age_seconds + 1)
            )
            if heartbeat_age < 0:
                errors.append("heartbeat age cannot be negative")
            elif heartbeat_age > heartbeat_max_age_seconds:
                errors.append("heartbeat stale")
        except (TypeError, ValueError):
            heartbeat_age = heartbeat_max_age_seconds + 1
            errors.append("heartbeat age is invalid")
        try:
            cost = _finite_cost(agent.get("reserved_cost"))
            if cost < 0:
                errors.append("reserved cost cannot be negative")
            else:
                total_cost += cost
        except ValueError:
            cost = 0.0
            errors.append("reserved cost is invalid")
        rows.append(
            {
                "agent_id": identity,
                "ready": not errors,
                "errors": errors,
                "heartbeat_age_seconds": heartbeat_age,
                "reserved_cost": cost,
            }
        )
    if total_cost > float(total_cost_cap):
        for row in rows:
            row["ready"] = False
            row["errors"].append("fleet cost cap exceeded")
    result = {
        "valid": bool(rows) and all(bool(row["ready"]) for row in rows),
        "project_id": project_id,
        "agents": rows,
        "agent_count": len(rows),
        "total_reserved_cost": total_cost,
        "total_cost_cap": float(total_cost_cap),
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


def _seal(value: Mapping[str, object], digest_field: str) -> dict[str, object]:
    sealed = dict(value)
    sealed.pop(digest_field, None)
    sealed[digest_field] = _stable(sealed)
    return sealed


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class AgentSessionCoordinator:
    """Project-scoped durable heartbeat and lifecycle projection.

    The operational event bus is the canonical history.  This class keeps a
    hash-sealed current-state projection and can reconcile a projection that
    lagged a successfully published canonical event during a process crash.
    Readiness and lifecycle state are observations only; every returned record
    retains ``authority_granted: false``.
    """

    _STATE_FIELDS = {
        "schema_version",
        "agent_id",
        "session_id",
        "project_id",
        "owner_id",
        "permissions",
        "reserved_cost",
        "lifecycle",
        "heartbeat_at",
        "heartbeat_sequence",
        "state_revision",
        "restart_count",
        "task_id",
        "claim_id",
        "orchestration_id",
        "last_event_id",
        "last_event_sha256",
        "last_bus_revision",
        "authority_granted",
        "record_sha256",
    }
    _REGISTRY_FIELDS = {"schema_version", "agents", "registry_sha256"}
    _EFFECT_PERMISSIONS = frozenset(
        {"read", "write", "network", "process", "model", "ui", "approval", "destructive"}
    )

    def __init__(
        self,
        engine_root: Path,
        bus: OperationalEventBus,
        store_root: Path,
        allowed_root: Path,
        *,
        heartbeat_max_age_seconds: int = 120,
        total_cost_cap: float = 100.0,
    ) -> None:
        self.engine_root = engine_root.resolve(strict=True)
        self.allowed_root = allowed_root.resolve(strict=True)
        self.root = store_root.resolve()
        if not _inside(self.root, self.allowed_root):
            raise ValueError("agent session store must stay below allowed root")
        if heartbeat_max_age_seconds < 1:
            raise ValueError("heartbeat freshness bound must be positive")
        if not math.isfinite(float(total_cost_cap)) or total_cost_cap < 0:
            raise ValueError("fleet cost cap must be finite and non-negative")
        self.bus = bus
        self.heartbeat_max_age_seconds = int(heartbeat_max_age_seconds)
        self.total_cost_cap = float(total_cost_cap)
        self.wal = JsonWal(self.root / ".wal", self.allowed_root)

    @property
    def _registry_path(self) -> Path:
        return self.root / "registry.json"

    @property
    def _lock_path(self) -> Path:
        return self.root / ".sessions.lock"

    @staticmethod
    def _session_key(project_id: str, agent_id: str, session_id: str) -> str:
        source = "\0".join((project_id, agent_id, session_id)).encode("utf-8")
        return hashlib.sha256(source).hexdigest()

    def _state_path(self, project_id: str, agent_id: str, session_id: str) -> Path:
        key = self._session_key(project_id, agent_id, session_id)
        return self.root / "sessions" / key[:2] / f"{key}.json"

    @staticmethod
    def _empty_registry() -> dict[str, object]:
        return _seal(
            {"schema_version": REGISTRY_SCHEMA_VERSION, "agents": {}},
            "registry_sha256",
        )

    def _read_registry(self) -> dict[str, object]:
        if not self._registry_path.exists():
            return self._empty_registry()
        if not self._registry_path.is_file() or self._registry_path.is_symlink():
            raise ValueError("agent session registry is not a regular file")
        try:
            value = json.loads(self._registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("agent session registry is unreadable") from error
        if not isinstance(value, dict) or set(value) != self._REGISTRY_FIELDS:
            raise ValueError("agent session registry fields are invalid")
        if value.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise ValueError("agent session registry schema is unsupported")
        if value != _seal(value, "registry_sha256"):
            raise ValueError("agent session registry digest mismatch")
        agents = value.get("agents")
        if not isinstance(agents, dict):
            raise ValueError("agent session registry agents are invalid")
        for agent_id, record in agents.items():
            if (
                not isinstance(agent_id, str)
                or not agent_id
                or not isinstance(record, dict)
                or set(record) != {"project_id", "session_id", "state_path"}
                or not all(isinstance(record.get(field), str) and record[field] for field in record)
            ):
                raise ValueError("agent session registry entry is invalid")
            relative = Path(record["state_path"])
            target = (self.root / relative).resolve()
            if relative.is_absolute() or not _inside(target, self.root):
                raise ValueError("agent session registry path escapes custody")
        return value

    @classmethod
    def _validate_state(cls, value: object) -> dict[str, object]:
        if not isinstance(value, dict) or set(value) != cls._STATE_FIELDS:
            raise ValueError("agent session state fields are invalid")
        if value.get("schema_version") != SESSION_SCHEMA_VERSION:
            raise ValueError("agent session state schema is unsupported")
        if value != _seal(value, "record_sha256"):
            raise ValueError("agent session state digest mismatch")
        for field in (
            "agent_id",
            "session_id",
            "project_id",
            "owner_id",
            "task_id",
            "claim_id",
            "orchestration_id",
            "last_event_id",
        ):
            _required_text(value.get(field), field)
        permissions = value.get("permissions")
        if (
            not isinstance(permissions, list)
            or not permissions
            or permissions != sorted(set(permissions))
            or not all(isinstance(item, str) and item.strip() for item in permissions)
        ):
            raise ValueError("agent session permissions are invalid")
        cost = _finite_cost(value.get("reserved_cost"))
        if cost < 0:
            raise ValueError("agent session reserved cost is invalid")
        if value.get("lifecycle") not in SESSION_STATES:
            raise ValueError("agent session lifecycle is invalid")
        _parse_timestamp(value.get("heartbeat_at"), "heartbeat_at")
        if (
            not isinstance(value.get("heartbeat_sequence"), int)
            or int(value["heartbeat_sequence"]) < 1
            or not isinstance(value.get("state_revision"), int)
            or int(value["state_revision"]) < 1
            or not isinstance(value.get("restart_count"), int)
            or int(value["restart_count"]) < 0
            or not isinstance(value.get("last_bus_revision"), int)
            or int(value["last_bus_revision"]) < 1
            or value.get("authority_granted") is not False
            or not _SHA256.fullmatch(str(value.get("last_event_sha256", "")))
        ):
            raise ValueError("agent session counters or authority fields are invalid")
        return dict(value)

    def _read_state(self, project_id: str, agent_id: str, session_id: str) -> dict[str, object]:
        path = self._state_path(project_id, agent_id, session_id)
        if not path.is_file() or path.is_symlink():
            raise ValueError("agent session state is missing or not a regular file")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("agent session state is unreadable") from error
        state = self._validate_state(value)
        if (
            state["project_id"] != project_id
            or state["agent_id"] != agent_id
            or state["session_id"] != session_id
        ):
            raise ValueError("agent session identity or project differs from state")
        return state

    @staticmethod
    def _projection_payload(state: Mapping[str, object]) -> dict[str, object]:
        omitted = {"last_event_id", "last_event_sha256", "last_bus_revision", "record_sha256"}
        return {key: deepcopy(value) for key, value in state.items() if key not in omitted}

    @staticmethod
    def _scope_value(scopes: Sequence[object], prefix: str) -> str:
        matches = [str(item)[len(prefix):] for item in scopes if str(item).startswith(prefix)]
        if len(matches) != 1 or not matches[0]:
            raise ValueError(f"canonical agent event has invalid {prefix[:-1]} scope")
        return matches[0]

    def _state_from_envelope(self, envelope: Mapping[str, object]) -> dict[str, object]:
        try:
            event = envelope["event"]
            assert isinstance(event, Mapping)
            actor = event["actor"]
            work = event["work"]
            effects = event["effects"]
            integrity = event["integrity"]
            assert all(isinstance(item, Mapping) for item in (actor, work, effects, integrity))
            scopes = effects["scope_refs"]
            assert isinstance(scopes, list)
            permission_prefix = "permission:"
            permissions = sorted(
                str(item)[len(permission_prefix):]
                for item in scopes
                if str(item).startswith(permission_prefix)
            )
            state = {
                "schema_version": SESSION_SCHEMA_VERSION,
                "agent_id": str(actor["actor_id"]),
                "session_id": str(actor["session_id"]),
                "project_id": str(work["project_id"]),
                "owner_id": str(actor["accountable_owner"]),
                "permissions": permissions,
                "reserved_cost": float(self._scope_value(scopes, "reserved-cost:")),
                "lifecycle": self._scope_value(scopes, "state:"),
                "heartbeat_at": self._scope_value(scopes, "heartbeat-at:"),
                "heartbeat_sequence": int(self._scope_value(scopes, "heartbeat-sequence:")),
                "state_revision": int(self._scope_value(scopes, "state-revision:")),
                "restart_count": int(self._scope_value(scopes, "restart-count:")),
                "task_id": str(work["task_id"]),
                "claim_id": str(work["claim_id"]),
                "orchestration_id": str(work["orchestration_id"]),
                "last_event_id": str(event["event_id"]),
                "last_event_sha256": str(envelope["event_sha256"]),
                "last_bus_revision": int(envelope["revision"]),
                "authority_granted": False,
            }
        except (AssertionError, KeyError, TypeError, ValueError) as error:
            raise ValueError("canonical agent event cannot reconstruct session state") from error
        expected = integrity.get("output_sha256")
        if expected != _stable(self._projection_payload(state)):
            raise ValueError("canonical agent event projection digest mismatch")
        return self._validate_state(_seal(state, "record_sha256"))

    def _validate_canonical_advance(
        self,
        previous: Mapping[str, object],
        candidate: Mapping[str, object],
        envelope: Mapping[str, object],
    ) -> None:
        immutable = (
            "schema_version",
            "agent_id",
            "session_id",
            "project_id",
            "owner_id",
            "permissions",
            "reserved_cost",
            "task_id",
            "claim_id",
            "orchestration_id",
            "authority_granted",
        )
        if any(candidate[field] != previous[field] for field in immutable):
            raise ValueError("canonical agent event changes immutable session identity")
        if int(candidate["state_revision"]) != int(previous["state_revision"]) + 1:
            raise ValueError("canonical agent event skips session state revision")
        try:
            event = envelope["event"]
            assert isinstance(event, Mapping)
            operation = event["operation"]
            integrity = event["integrity"]
            assert isinstance(operation, Mapping) and isinstance(integrity, Mapping)
            name = str(operation["name"])
        except (AssertionError, KeyError, TypeError) as error:
            raise ValueError("canonical agent event operation is invalid") from error
        if integrity.get("input_sha256") != _stable(self._projection_payload(previous)):
            raise ValueError("canonical agent event input state digest mismatch")
        current = str(previous["lifecycle"])
        target = str(candidate["lifecycle"])
        sequence_delta = int(candidate["heartbeat_sequence"]) - int(previous["heartbeat_sequence"])
        restart_delta = int(candidate["restart_count"]) - int(previous["restart_count"])
        if name == "agent.session.heartbeat":
            valid = target == current and sequence_delta == 1 and restart_delta == 0
        elif name == "agent.session.restart":
            valid = (
                target == "recovering"
                and target in SESSION_TRANSITIONS[current]
                and sequence_delta == 1
                and restart_delta == 1
            )
        elif name == f"agent.session.transition.{target}":
            valid = (
                target in SESSION_TRANSITIONS[current]
                and sequence_delta == (0 if target == "stale" else 1)
                and restart_delta == 0
            )
        else:
            valid = False
        if not valid:
            raise ValueError("canonical agent event has an illegal lifecycle advance")
        if target == "stale":
            if candidate["heartbeat_at"] != previous["heartbeat_at"]:
                raise ValueError("stale transition cannot forge a fresh heartbeat")
        elif _parse_timestamp(candidate["heartbeat_at"], "heartbeat_at") <= _parse_timestamp(
            previous["heartbeat_at"], "heartbeat_at"
        ):
            raise ValueError("canonical agent heartbeat does not advance time")

    def _session_events(self, project_id: str, agent_id: str, session_id: str) -> list[dict[str, object]]:
        replay = self.bus.replay(limit=10_000)
        if not replay["valid"]:
            raise ValueError("cannot reconstruct agent session over degraded event ancestry")
        matches: list[dict[str, object]] = []
        for raw in replay["events"]:
            if not isinstance(raw, dict) or not isinstance(raw.get("event"), dict):
                continue
            event = raw["event"]
            actor = event.get("actor")
            work = event.get("work")
            source = event.get("source")
            if (
                isinstance(actor, Mapping)
                and isinstance(work, Mapping)
                and isinstance(source, Mapping)
                and actor.get("actor_id") == agent_id
                and actor.get("session_id") == session_id
                and work.get("project_id") == project_id
                and source.get("route_id") == "runtime.agent"
            ):
                matches.append(raw)
        return matches

    def _persist_state(
        self,
        state: Mapping[str, object],
        *,
        registry: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        artifacts = [
            JsonArtifact(
                "state",
                self._state_path(
                    str(state["project_id"]), str(state["agent_id"]), str(state["session_id"])
                ),
                dict(state),
            )
        ]
        if registry is not None:
            artifacts.insert(0, JsonArtifact("state", self._registry_path, dict(registry)))
        return self.wal.commit(
            artifacts,
            transaction_id=f"agent-session-{uuid.uuid4().hex}",
        )

    def _event_for_state(
        self,
        state: Mapping[str, object],
        *,
        operation_name: str,
        observed_at: str,
        previous_event_sha256: str | None,
        input_sha256: str | None,
    ) -> dict[str, object]:
        lifecycle = str(state["lifecycle"])
        event_lifecycle = (
            "admitted"
            if operation_name == "agent.session.register"
            else "waiting"
            if lifecycle in {"waiting", "blocked"}
            else "failed"
            if lifecycle == "stale"
            else "progress"
        )
        result = "failure" if lifecycle == "stale" else "pending"
        permissions = list(state["permissions"])
        scopes = [
            f"project:{state['project_id']}",
            f"agent:{state['agent_id']}",
            f"session:{state['session_id']}",
            f"owner:{state['owner_id']}",
            f"reserved-cost:{state['reserved_cost']}",
            f"state:{lifecycle}",
            f"heartbeat-at:{state['heartbeat_at']}",
            f"heartbeat-sequence:{state['heartbeat_sequence']}",
            f"state-revision:{state['state_revision']}",
            f"restart-count:{state['restart_count']}",
            *(f"permission:{item}" for item in permissions),
        ]
        head = self.bus.head()
        if not head["valid"]:
            raise ValueError("cannot publish agent state over degraded event ancestry")
        bus_previous = head["event_sha256"]
        if bus_previous != previous_event_sha256:
            raise ValueError("agent event ancestry changed before publication")
        return build_operation_event(
            self.engine_root,
            {
                "sdk_version": SDK_VERSION,
                "schema_version": "px.operation-event/1",
                "event_id": f"evt-agent-{uuid.uuid4().hex}",
                "correlation_id": str(state["orchestration_id"]),
                "parent_correlation_id": str(state["claim_id"]),
                "actor": {
                    "actor_id": str(state["agent_id"]),
                    "actor_kind": "agent",
                    "session_id": str(state["session_id"]),
                    "harness": "pacify-x-agent-session",
                    "accountable_owner": str(state["owner_id"]),
                },
                "work": {
                    "project_id": str(state["project_id"]),
                    "task_id": str(state["task_id"]),
                    "claim_id": str(state["claim_id"]),
                    "orchestration_id": str(state["orchestration_id"]),
                },
                "source": {
                    "route_id": "runtime.agent",
                    "component": "runtime.agent_fleet_controls",
                    "host_id": None,
                    "coverage_tier": "C",
                },
                "operation": {
                    "name": operation_name,
                    "lifecycle": event_lifecycle,
                    "result": result,
                },
                "effects": {
                    "declared": sorted(set(permissions) & self._EFFECT_PERMISSIONS),
                    "observed": [],
                    "scope_refs": list(dict.fromkeys(scopes)),
                },
                "provider": None,
                "time": {
                    "observed_at": observed_at,
                    "started_at": None,
                    "duration_ms": None,
                    "freshness": "stale" if lifecycle == "stale" else "live",
                },
                "integrity": {
                    "input_sha256": input_sha256,
                    "output_sha256": _stable(self._projection_payload(state)),
                    "previous_event_sha256": previous_event_sha256,
                },
                "capture": {"classification": "metadata_only", "payload_included": False},
            },
        )

    def _publish_and_persist(
        self,
        state: Mapping[str, object],
        *,
        operation_name: str,
        observed_at: str,
        previous_state: Mapping[str, object] | None,
        registry: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        head = self.bus.head()
        if not head["valid"]:
            raise ValueError("cannot publish agent state over degraded event ancestry")
        previous_event = head["event_sha256"]
        event = self._event_for_state(
            state,
            operation_name=operation_name,
            observed_at=observed_at,
            previous_event_sha256=previous_event,
            input_sha256=(
                _stable(self._projection_payload(previous_state))
                if previous_state is not None
                else None
            ),
        )
        receipt = self.bus.publish(event)
        committed_state = _seal(
            {
                **dict(state),
                "last_event_id": event["event_id"],
                "last_event_sha256": receipt["event_sha256"],
                "last_bus_revision": receipt["revision"],
            },
            "record_sha256",
        )
        self._validate_state(committed_state)
        self._persist_state(committed_state, registry=registry)
        return committed_state

    def register_session(
        self,
        participant: Mapping[str, object],
        *,
        session_id: str,
        task_id: str,
        claim_id: str,
        orchestration_id: str,
        observed_at: str,
        required_permissions: Sequence[str] = (),
    ) -> dict[str, object]:
        """Admit one unique participant and durably publish its active session."""
        project_id = _required_text(participant.get("project_id"), "project_id")
        agent_id = _required_text(participant.get("agent_id"), "agent_id")
        owner_id = _required_text(participant.get("owner_id"), "owner_id")
        session_id = _required_text(session_id, "session_id")
        task_id = _required_text(task_id, "task_id")
        claim_id = _required_text(claim_id, "claim_id")
        orchestration_id = _required_text(orchestration_id, "orchestration_id")
        observed = _timestamp(observed_at, "observed_at")
        raw_permissions = participant.get("permissions")
        if not isinstance(raw_permissions, (list, tuple, set, frozenset)):
            raise ValueError("permissions declaration missing or invalid")
        permissions = sorted({str(item).strip() for item in raw_permissions if str(item).strip()})
        if not permissions:
            raise ValueError("at least one declared permission is required")
        reserved_cost = _finite_cost(participant.get("reserved_cost"))
        readiness_participant = {
            **dict(participant),
            "agent_id": agent_id,
            "project_id": project_id,
            "owner_id": owner_id,
            "permissions": permissions,
            "reserved_cost": reserved_cost,
        }
        readiness = evaluate_fleet_readiness(
            project_id,
            [readiness_participant],
            required_permissions=required_permissions,
            heartbeat_max_age_seconds=self.heartbeat_max_age_seconds,
            total_cost_cap=self.total_cost_cap,
        )
        if not readiness["valid"]:
            raise ValueError("agent readiness rejected: " + "; ".join(readiness["agents"][0]["errors"]))
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self._lock_path, timeout_seconds=10):
            self.wal.recover()
            registry = self._read_registry()
            agents = dict(registry["agents"])
            if agent_id in agents:
                raise ValueError("duplicate stable agent identity")
            path = self._state_path(project_id, agent_id, session_id)
            if path.exists():
                raise ValueError("duplicate agent session identity")
            observed_time = _parse_timestamp(observed, "observed_at")
            fleet = [readiness_participant]
            for existing_agent_id, identity in agents.items():
                if identity["project_id"] != project_id:
                    continue
                existing = self._read_state(
                    project_id, str(existing_agent_id), str(identity["session_id"])
                )
                heartbeat_age = max(
                    0,
                    int(
                        (
                            observed_time
                            - _parse_timestamp(existing["heartbeat_at"], "heartbeat_at")
                        ).total_seconds()
                    ),
                )
                fleet.append(
                    {
                        "agent_id": existing["agent_id"],
                        "project_id": existing["project_id"],
                        "owner_id": existing["owner_id"],
                        "permissions": existing["permissions"],
                        "heartbeat_age_seconds": heartbeat_age,
                        "reserved_cost": existing["reserved_cost"],
                    }
                )
            fleet_readiness = evaluate_fleet_readiness(
                project_id,
                fleet,
                required_permissions=required_permissions,
                heartbeat_max_age_seconds=self.heartbeat_max_age_seconds,
                total_cost_cap=self.total_cost_cap,
            )
            if not fleet_readiness["valid"]:
                errors = sorted(
                    {
                        error
                        for row in fleet_readiness["agents"]
                        for error in row["errors"]
                    }
                )
                raise ValueError("fleet readiness rejected: " + "; ".join(errors))
            provisional = {
                "schema_version": SESSION_SCHEMA_VERSION,
                "agent_id": agent_id,
                "session_id": session_id,
                "project_id": project_id,
                "owner_id": owner_id,
                "permissions": permissions,
                "reserved_cost": reserved_cost,
                "lifecycle": "active",
                "heartbeat_at": observed,
                "heartbeat_sequence": 1,
                "state_revision": 1,
                "restart_count": 0,
                "task_id": task_id,
                "claim_id": claim_id,
                "orchestration_id": orchestration_id,
                "authority_granted": False,
            }
            relative = path.resolve().relative_to(self.root).as_posix()
            agents[agent_id] = {
                "project_id": project_id,
                "session_id": session_id,
                "state_path": relative,
            }
            next_registry = _seal(
                {"schema_version": REGISTRY_SCHEMA_VERSION, "agents": agents},
                "registry_sha256",
            )
            return self._publish_and_persist(
                provisional,
                operation_name="agent.session.register",
                observed_at=observed,
                previous_state=None,
                registry=next_registry,
            )

    def reconstruct_session(
        self, project_id: str, agent_id: str, session_id: str
    ) -> dict[str, object]:
        """Verify durable state and roll it forward from newer canonical events."""
        project_id = _required_text(project_id, "project_id")
        agent_id = _required_text(agent_id, "agent_id")
        session_id = _required_text(session_id, "session_id")
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self._lock_path, timeout_seconds=10):
            self.wal.recover()
            registry = self._read_registry()
            identity = registry["agents"].get(agent_id)
            if not isinstance(identity, Mapping):
                raise ValueError("agent identity is not registered")
            if identity.get("project_id") != project_id or identity.get("session_id") != session_id:
                raise ValueError("cross-project or mismatched agent session rejected")
            state = self._read_state(project_id, agent_id, session_id)
            events = self._session_events(project_id, agent_id, session_id)
            if not events:
                raise ValueError("agent session has no canonical operational event")
            event_ids = [str(item["event"]["event_id"]) for item in events]
            if state["last_event_id"] not in event_ids:
                raise ValueError("agent state references an unavailable canonical event")
            state_index = event_ids.index(str(state["last_event_id"]))
            recorded = self._state_from_envelope(events[state_index])
            if recorded != state:
                raise ValueError("agent state differs from its canonical event")
            latest = state
            for envelope in events[state_index + 1 :]:
                candidate = self._state_from_envelope(envelope)
                self._validate_canonical_advance(latest, candidate, envelope)
                latest = candidate
            if int(latest["last_bus_revision"]) < int(state["last_bus_revision"]):
                raise ValueError("canonical event ancestry is behind agent state")
            if int(latest["last_bus_revision"]) > int(state["last_bus_revision"]):
                self._persist_state(latest)
                state = latest
            return deepcopy(state)

    def session_status(
        self,
        project_id: str,
        agent_id: str,
        session_id: str,
        *,
        observed_at: str,
    ) -> dict[str, object]:
        """Return a freshness-aware view without silently granting or revoking authority."""
        state = self.reconstruct_session(project_id, agent_id, session_id)
        observed = _parse_timestamp(observed_at, "observed_at")
        heartbeat = _parse_timestamp(state["heartbeat_at"], "heartbeat_at")
        age = max(0.0, (observed - heartbeat).total_seconds())
        effective = "stale" if age > self.heartbeat_max_age_seconds else state["lifecycle"]
        return {
            **state,
            "effective_lifecycle": effective,
            "heartbeat_age_seconds": age,
            "heartbeat_fresh": effective != "stale",
            "authority_granted": False,
        }

    def _advance(
        self,
        project_id: str,
        agent_id: str,
        session_id: str,
        *,
        observed_at: str,
        target: str,
        operation_name: str,
        increment_restart: bool = False,
        heartbeat_only: bool = False,
    ) -> dict[str, object]:
        observed = _timestamp(observed_at, "observed_at")
        state = self.reconstruct_session(project_id, agent_id, session_id)
        age = max(
            0.0,
            (
                _parse_timestamp(observed, "observed_at")
                - _parse_timestamp(state["heartbeat_at"], "heartbeat_at")
            ).total_seconds(),
        )
        current = str(state["lifecycle"])
        if heartbeat_only:
            if current == "stale" or age > self.heartbeat_max_age_seconds:
                raise ValueError("stale agent must enter recovering before heartbeat renewal")
            target = current
        else:
            if target not in SESSION_STATES:
                raise ValueError("unsupported agent session lifecycle")
            if target not in SESSION_TRANSITIONS[current]:
                raise ValueError(f"illegal agent session transition: {current} -> {target}")
            if age > self.heartbeat_max_age_seconds and target not in {"stale", "recovering"}:
                raise ValueError("stale heartbeat refuses non-recovery transition")
            if target == "stale" and age <= self.heartbeat_max_age_seconds:
                raise ValueError("fresh heartbeat cannot be marked stale")
        next_state = {
            **state,
            "lifecycle": target,
            "heartbeat_at": state["heartbeat_at"] if target == "stale" else observed,
            "heartbeat_sequence": int(state["heartbeat_sequence"]) + (0 if target == "stale" else 1),
            "state_revision": int(state["state_revision"]) + 1,
            "restart_count": int(state["restart_count"]) + (1 if increment_restart else 0),
        }
        for field in ("last_event_id", "last_event_sha256", "last_bus_revision", "record_sha256"):
            next_state.pop(field, None)
        with FileLock(self._lock_path, timeout_seconds=10):
            # Re-read under the mutation lock so concurrent state transitions
            # cannot be overwritten by an older projection.
            current_state = self._read_state(project_id, agent_id, session_id)
            if current_state["record_sha256"] != state["record_sha256"]:
                raise ValueError("agent session changed during transition")
            return self._publish_and_persist(
                next_state,
                operation_name=operation_name,
                observed_at=observed,
                previous_state=state,
            )

    def heartbeat_session(
        self, project_id: str, agent_id: str, session_id: str, *, observed_at: str
    ) -> dict[str, object]:
        return self._advance(
            project_id,
            agent_id,
            session_id,
            observed_at=observed_at,
            target="active",
            operation_name="agent.session.heartbeat",
            heartbeat_only=True,
        )

    def transition_session(
        self,
        project_id: str,
        agent_id: str,
        session_id: str,
        target: str,
        *,
        observed_at: str,
    ) -> dict[str, object]:
        return self._advance(
            project_id,
            agent_id,
            session_id,
            observed_at=observed_at,
            target=target,
            operation_name=f"agent.session.transition.{target}",
        )

    def restart_session(
        self, project_id: str, agent_id: str, session_id: str, *, observed_at: str
    ) -> dict[str, object]:
        """Move a stale/blocked session to recovering with a fresh restart heartbeat."""
        return self._advance(
            project_id,
            agent_id,
            session_id,
            observed_at=observed_at,
            target="recovering",
            operation_name="agent.session.restart",
            increment_restart=True,
        )
