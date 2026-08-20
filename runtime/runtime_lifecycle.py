"""Correlated runtime lifecycle hooks backed by the operational event bus."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable, TypeVar
import uuid

from .instrumentation_sdk import SDK_VERSION, build_operation_event
from .operational_event_bus import OperationalEventBus


T = TypeVar("T")


def _digest(value: object) -> str:
    try:
        data = json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    except (TypeError, ValueError):
        data = type(value).__name__.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class RuntimeLifecycle:
    """Emit one correlated trace across runtime planning and execution stages."""

    def __init__(
        self,
        engine_root: Path,
        bus: OperationalEventBus,
        *,
        project_id: str,
        actor_id: str,
        session_id: str,
        correlation_id: str | None = None,
        task_id: str | None = None,
        orchestration_id: str | None = None,
    ) -> None:
        self.engine_root = engine_root.resolve(strict=True)
        self.bus = bus
        self.project_id = project_id
        self.actor_id = actor_id
        self.session_id = session_id
        self.correlation_id = correlation_id or f"corr-{uuid.uuid4().hex}"
        self.task_id = task_id
        self.orchestration_id = orchestration_id
        head = bus.head()
        if not head["valid"]:
            raise ValueError("cannot instrument over degraded operational ancestry")
        self._previous = head["event_sha256"]

    def emit(
        self,
        operation_name: str,
        lifecycle: str,
        result: str,
        *,
        declared_effects: tuple[str, ...] = (),
        observed_effects: tuple[str, ...] = (),
        input_sha256: str | None = None,
        output_sha256: str | None = None,
    ) -> dict[str, object]:
        event = build_operation_event(
            self.engine_root,
            {
                "sdk_version": SDK_VERSION,
                "schema_version": "px.operation-event/1",
                "event_id": f"evt-{uuid.uuid4().hex}",
                "correlation_id": self.correlation_id,
                "parent_correlation_id": None,
                "actor": {
                    "actor_id": self.actor_id,
                    "actor_kind": "runtime",
                    "session_id": self.session_id,
                    "harness": "pacify-x-runtime",
                    "accountable_owner": self.actor_id,
                },
                "work": {
                    "project_id": self.project_id,
                    "task_id": self.task_id,
                    "claim_id": None,
                    "orchestration_id": self.orchestration_id,
                },
                "source": {
                    "route_id": "runtime.project-control-plane",
                    "component": "runtime.runtime_lifecycle",
                    "host_id": None,
                    "coverage_tier": "C",
                },
                "operation": {
                    "name": operation_name,
                    "lifecycle": lifecycle,
                    "result": result,
                },
                "effects": {
                    "declared": list(declared_effects),
                    "observed": list(observed_effects),
                    "scope_refs": [f"project:{self.project_id}"],
                },
                "provider": None,
                "time": {
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "started_at": None,
                    "duration_ms": None,
                    "freshness": "live",
                },
                "integrity": {
                    "input_sha256": input_sha256,
                    "output_sha256": output_sha256,
                    "previous_event_sha256": self._previous,
                },
                "capture": {
                    "classification": "metadata_only",
                    "payload_included": False,
                },
            },
        )
        receipt = self.bus.publish(event)
        self._previous = str(receipt["event_sha256"])
        return receipt

    def run_verified_tool(
        self,
        tool_id: str,
        execute: Callable[[], T],
        verify: Callable[[T], bool],
        *,
        approved: bool,
        declared_effects: tuple[str, ...] = ("read",),
    ) -> T:
        """Run one admitted tool and retain every stage without content capture."""
        input_sha256 = _digest({"tool_id": tool_id, "task_id": self.task_id})
        self.emit("plan", "admitted", "pending")
        self.emit("orchestration", "started", "pending")
        self.emit("workflow", "started", "pending")
        self.emit("task", "started", "pending")
        if not approved:
            self.emit("approval", "denied", "denied")
            self.emit("task", "denied", "denied")
            raise PermissionError("tool execution was not approved")
        self.emit("approval", "completed", "success")
        self.emit(
            f"tool.{tool_id}",
            "started",
            "pending",
            declared_effects=declared_effects,
            input_sha256=input_sha256,
        )
        try:
            value = execute()
        except BaseException:
            self.emit(
                f"tool.{tool_id}",
                "failed",
                "failure",
                declared_effects=declared_effects,
                input_sha256=input_sha256,
            )
            self.emit("task", "failed", "failure")
            raise
        output_sha256 = _digest(value)
        self.emit(
            f"tool.{tool_id}",
            "completed",
            "success",
            declared_effects=declared_effects,
            observed_effects=declared_effects,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
        )
        self.emit("verification", "started", "pending", output_sha256=output_sha256)
        if not verify(value):
            self.emit("verification", "failed", "failure", output_sha256=output_sha256)
            self.emit("task", "failed", "failure")
            raise ValueError("tool outcome verification failed")
        self.emit("verification", "completed", "success", output_sha256=output_sha256)
        self.emit("task", "completed", "success", output_sha256=output_sha256)
        self.emit("workflow", "completed", "success", output_sha256=output_sha256)
        self.emit("orchestration", "completed", "success", output_sha256=output_sha256)
        self.emit("plan", "completed", "success", output_sha256=output_sha256)
        return value
