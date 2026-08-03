"""Deterministic, observe-only capability scheduling and recovery planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping
from pathlib import Path


NETWORK_RANK = {"none": 0, "local": 1, "private_remote": 2, "external": 3}
DEFAULT_WEIGHTS = {
    "priority": 0.34,
    "deadline_pressure": 0.20,
    "dependency_unblock": 0.16,
    "aging": 0.10,
    "success_rate": 0.08,
    "quality": 0.07,
    "cost_efficiency": 0.05,
}


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(slots=True)
class Resources:
    cpu_cores: float = 0.0
    ram_gb: float = 0.0
    gpu_count: int = 0
    vram_gb: float = 0.0
    disk_gb: float = 0.0
    network: str = "none"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "Resources":
        value = value or {}
        fields = cls.__dataclass_fields__
        return cls(**{name: value.get(name, field.default) for name, field in fields.items()})

    def fits(self, requested: "Resources") -> bool:
        return (
            self.cpu_cores >= requested.cpu_cores
            and self.ram_gb >= requested.ram_gb
            and self.gpu_count >= requested.gpu_count
            and self.vram_gb >= requested.vram_gb
            and self.disk_gb >= requested.disk_gb
            and NETWORK_RANK.get(self.network, -1) >= NETWORK_RANK.get(requested.network, 99)
        )

    def consume(self, requested: "Resources") -> None:
        for name in ("cpu_cores", "ram_gb", "gpu_count", "vram_gb", "disk_gb"):
            setattr(self, name, getattr(self, name) - getattr(requested, name))

    def release(self, requested: "Resources") -> None:
        for name in ("cpu_cores", "ram_gb", "gpu_count", "vram_gb", "disk_gb"):
            setattr(self, name, getattr(self, name) + getattr(requested, name))

    def record(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


@dataclass(slots=True)
class Task:
    id: str
    capability: str
    priority: int = 500
    state: str = "pending"
    dependencies: list[str] = field(default_factory=list)
    estimated_seconds: float = 1.0
    resources: Resources = field(default_factory=Resources)
    acceptance: dict[str, Any] = field(default_factory=dict)
    deadline: str | None = None
    risk: str = "low"
    approval_required: bool = False
    approved: bool = False
    idempotency_key: str | None = None
    compensation: str | None = None
    alternatives: list[str] = field(default_factory=list)
    budget: dict[str, Any] = field(default_factory=dict)
    attempt: int = 1
    privacy: str = "normal"
    created_index: int = 0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Task":
        fields = cls.__dataclass_fields__
        values = {name: value[name] for name in fields if name in value and name not in {"resources", "created_index"}}
        values["resources"] = Resources.from_mapping(value.get("resources"))
        return cls(**values)


class Scheduler:
    """Plans and simulates; it never invokes an executor or mutates canonical state."""

    def __init__(self, resources: Resources, policy: Mapping[str, Any] | None = None, *, now: datetime | None = None):
        self.total = resources
        self.available = Resources.from_mapping(resources.record())
        self.policy = dict(policy or {})
        self.now = now or datetime(2000, 1, 1, tzinfo=timezone.utc)
        self.tasks: dict[str, Task] = {}
        self.completed: set[str] = set()
        self.failed: set[str] = set()
        self.events: list[dict[str, Any]] = []
        self._counter = 0

    def add(self, task: Task) -> None:
        if task.id in self.tasks:
            raise ValueError(f"duplicate task id: {task.id}")
        if not task.id or not task.capability:
            raise ValueError("task id and capability are required")
        if not 0 <= int(task.priority) <= 1000:
            raise ValueError(f"priority outside 0..1000: {task.id}")
        self._counter += 1
        task.created_index = self._counter
        self.tasks[task.id] = task
        self.events.append({"event": "task_added", "task_id": task.id})

    def validate_dag(self) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError(f"dependency cycle at {task_id}")
            if task_id in visited:
                return
            visiting.add(task_id)
            for dependency in self.tasks[task_id].dependencies:
                if dependency not in self.tasks:
                    raise ValueError(f"missing dependency {dependency} for {task_id}")
                visit(dependency)
            visiting.remove(task_id)
            visited.add(task_id)

        for task_id in sorted(self.tasks):
            visit(task_id)

    def eligible(self, task: Task) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if task.state not in {"pending", "ready"}:
            reasons.append("state_not_schedulable")
        if any(dependency not in self.completed for dependency in task.dependencies):
            reasons.append("dependencies_incomplete")
        if task.approval_required and not task.approved:
            reasons.append("approval_required")
        if not self.available.fits(task.resources):
            reasons.append("resource_unavailable")
        if task.risk in {"high", "critical"} and not task.acceptance:
            reasons.append("acceptance_missing")
        if task.privacy in {"restricted", "secret"} and task.resources.network == "external":
            reasons.append("privacy_policy_denied")
        if self.policy.get("external_network") == "deny" and task.resources.network == "external":
            reasons.append("egress_policy_denied")
        maximum_cost = task.budget.get("maximum_cost")
        estimated_cost = task.budget.get("estimated_cost")
        if maximum_cost is not None and estimated_cost is not None and float(estimated_cost) > float(maximum_cost):
            reasons.append("budget_exhausted")
        if task.attempt > 1 and not task.idempotency_key and not task.compensation:
            reasons.append("retry_requires_idempotency_or_compensation")
        return not reasons, sorted(reasons)

    def score(self, task: Task) -> tuple[float, dict[str, float]]:
        downstream = sum(1 for candidate in self.tasks.values() if task.id in candidate.dependencies and candidate.state in {"pending", "ready"})
        maximum_downstream = max(1, len(self.tasks) - 1)
        deadline_pressure = 0.0
        if task.deadline:
            try:
                deadline = datetime.fromisoformat(task.deadline.replace("Z", "+00:00"))
                remaining = (deadline - self.now).total_seconds()
                deadline_pressure = _clamp(1.0 - remaining / max(task.estimated_seconds * 10.0, 1.0))
            except ValueError:
                deadline_pressure = 0.0
        factors = {
            "priority": _clamp(task.priority / 1000.0),
            "deadline_pressure": deadline_pressure,
            "dependency_unblock": _clamp(downstream / maximum_downstream),
            "aging": _clamp((self._counter - task.created_index) / max(1, self._counter)),
            "success_rate": _clamp(float(task.acceptance.get("expected_success", 0.5))),
            "quality": _clamp(float(task.acceptance.get("required_quality", 0.5))),
            "cost_efficiency": _clamp(float(task.budget.get("cost_efficiency", 0.5))),
        }
        weights = dict(DEFAULT_WEIGHTS)
        weights.update(self.policy.get("weights", {}))
        total_weight = sum(max(0.0, float(value)) for value in weights.values()) or 1.0
        score = sum(factors[name] * max(0.0, float(weights.get(name, 0.0))) for name in factors) / total_weight
        return round(score, 8), {name: round(value, 8) for name, value in factors.items()}

    def next_task(self) -> tuple[Task | None, dict[str, list[str]], dict[str, Any] | None]:
        eligible: list[tuple[float, int, str, dict[str, float]]] = []
        blocked: dict[str, list[str]] = {}
        for task in self.tasks.values():
            accepted, reasons = self.eligible(task)
            if accepted:
                score, factors = self.score(task)
                eligible.append((-score, task.created_index, task.id, factors))
            elif task.state in {"pending", "ready"}:
                blocked[task.id] = reasons
        if not eligible:
            return None, blocked, None
        eligible.sort()
        negated, _, task_id, factors = eligible[0]
        return self.tasks[task_id], blocked, {"score": -negated, "factors": factors}

    def simulate(self) -> dict[str, Any]:
        self.validate_dag()
        decisions: list[dict[str, Any]] = []
        while len(self.completed | self.failed) < len(self.tasks):
            task, blocked, score = self.next_task()
            if task is None:
                decisions.append({"event": "stalled", "blocked": blocked})
                break
            self.available.consume(task.resources)
            task.state = "running"
            dispatch = {"event": "would_dispatch", "task_id": task.id, **(score or {}), "resources": task.resources.record(), "idempotency_key": task.idempotency_key}
            decisions.append(dispatch)
            self.events.append(dispatch)
            self.available.release(task.resources)
            evidence = {"simulation": True, "acceptance_preserved": True, "executor_not_invoked": True}
            task.state = "succeeded"
            self.completed.add(task.id)
            finish = {"event": "simulated_completion", "task_id": task.id, "evidence": evidence}
            decisions.append(finish)
            self.events.append(finish)
        stalled = len(self.completed | self.failed) < len(self.tasks)
        return {
            "valid": not stalled,
            "observe_only": True,
            "completed": sorted(self.completed),
            "failed": sorted(self.failed),
            "events": decisions,
            "stalled": stalled,
            "decision_hash": _hash(self.events),
            "execution_authority": "none; dispatch events are plans only",
        }


def simulate_schedule(payload: Mapping[str, Any]) -> dict[str, Any]:
    workload = payload.get("workload", payload)
    tasks = workload.get("tasks") if isinstance(workload, Mapping) else None
    if not isinstance(tasks, list):
        return {"valid": False, "errors": ["workload.tasks must be a list"]}
    now_value = payload.get("now", "2000-01-01T00:00:00Z")
    try:
        now = datetime.fromisoformat(str(now_value).replace("Z", "+00:00"))
        scheduler = Scheduler(Resources.from_mapping(payload.get("resources", {})), payload.get("policy", {}), now=now)
        for value in tasks:
            if not isinstance(value, Mapping):
                raise ValueError("every task must be an object")
            scheduler.add(Task.from_mapping(value))
        return scheduler.simulate()
    except (KeyError, TypeError, ValueError) as error:
        return {"valid": False, "observe_only": True, "errors": [str(error)]}


def integration_healthcheck() -> dict[str, Any]:
    result = simulate_schedule({"resources": {"cpu_cores": 1}, "workload": {"tasks": [{"id": "a", "capability": "noop", "priority": 1, "resources": {"cpu_cores": 1}, "acceptance": {}}]}})
    return {"valid": result.get("valid") is True and result.get("observe_only") is True}


def _load(root: Path, relative: str) -> dict[str, Any]:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def list_scheduling_capabilities(root: Path) -> dict[str, Any]:
    records = _load(root, "registry/scheduling_capability_owners.json")["records"]
    return {"valid": True, "metadata_only": True, "count": len(records), "records": records}


def describe_scheduling_capability(root: Path, capability_id: str) -> dict[str, Any]:
    index = _load(root, "registry/scheduling_capabilities.json")["capabilities"]
    contract = next((item for item in index if item["id"] == capability_id), None)
    if contract is None:
        return {"valid": False, "errors": [f"unknown scheduling capability: {capability_id}"]}
    return {"valid": True, "owner": "orchestrate-capability-scheduling", "contract": contract}


def validate_scheduling_layer(root: Path) -> dict[str, Any]:
    capabilities = _load(root, "registry/scheduling_capabilities.json").get("capabilities", [])
    owners = _load(root, "registry/scheduling_capability_owners.json").get("records", [])
    workflows = _load(root, "orchestration/workflows/capability-scheduling.yaml").get("workflows", [])
    policies = _load(root, "registry/scheduling_policies.json").get("policies", [])
    schemas = list((root / "contracts" / "scheduling").glob("*.json"))
    actual = {"capabilities": len(capabilities), "owners": len(owners), "workflows": len(workflows), "policies": len(policies), "schemas": len(schemas)}
    expected = {"capabilities": 30, "owners": 30, "workflows": 5, "policies": 3, "schemas": 8}
    errors = [f"{name} denominator mismatch: {actual[name]} != {count}" for name, count in expected.items() if actual[name] != count]
    if {item["id"] for item in capabilities} != {item["id"] for item in owners}:
        errors.append("scheduling capability owner projection is not bijective")
    return {"valid": not errors, "counts": actual, "observe_only": True, "errors": errors}
