from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.operational_event_bus import OperationalEventBus
from runtime.runtime_lifecycle import RuntimeLifecycle


ROOT = Path(__file__).resolve().parents[1]


def _lifecycle(tmp_path: Path) -> tuple[OperationalEventBus, RuntimeLifecycle]:
    bus = OperationalEventBus(ROOT, tmp_path / "bus", tmp_path)
    lifecycle = RuntimeLifecycle(
        ROOT,
        bus,
        project_id="pacify-x",
        actor_id="agent-test",
        session_id="session-test",
        correlation_id="corr-runtime-tracer",
        task_id="task-O03",
        orchestration_id="orchestration-O03",
    )
    return bus, lifecycle


def test_trace_crosses_plan_task_tool_verification_and_receipts(tmp_path: Path) -> None:
    bus, lifecycle = _lifecycle(tmp_path)
    result = lifecycle.run_verified_tool(
        "readiness", lambda: {"ready": True}, lambda value: value["ready"], approved=True
    )
    assert result == {"ready": True}
    replay = bus.replay()
    assert replay["valid"] is True
    names = [item["event"]["operation"]["name"] for item in replay["events"]]
    assert names == [
        "plan",
        "orchestration",
        "workflow",
        "task",
        "approval",
        "tool.readiness",
        "tool.readiness",
        "verification",
        "verification",
        "task",
        "workflow",
        "orchestration",
        "plan",
    ]
    assert {item["event"]["correlation_id"] for item in replay["events"]} == {
        "corr-runtime-tracer"
    }
    assert len(tuple((tmp_path / "bus/receipts").glob("*.json"))) == len(names)


def test_failure_is_correlated_without_exception_content(tmp_path: Path) -> None:
    bus, lifecycle = _lifecycle(tmp_path)

    def fail() -> object:
        raise RuntimeError("credential=do-not-record")

    with pytest.raises(RuntimeError, match="do-not-record"):
        lifecycle.run_verified_tool("failing", fail, lambda _value: True, approved=True)
    rendered = json.dumps(bus.replay())
    assert "credential" not in rendered
    assert '"lifecycle": "failed"' in rendered


def test_denied_approval_never_invokes_tool(tmp_path: Path) -> None:
    bus, lifecycle = _lifecycle(tmp_path)
    invoked = False

    def tool() -> int:
        nonlocal invoked
        invoked = True
        return 1

    with pytest.raises(PermissionError):
        lifecycle.run_verified_tool("denied", tool, lambda _value: True, approved=False)
    assert invoked is False
    operations = [
        item["event"]["operation"] for item in bus.replay()["events"]
    ]
    assert any(item == {"name": "approval", "lifecycle": "denied", "result": "denied"} for item in operations)
    assert not any(item["name"].startswith("tool.") for item in operations)

