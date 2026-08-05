"""Conservative resource admission without spawning workers or tools."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping


@dataclass(frozen=True, slots=True)
class ResourcePolicy:
    max_agents: int = 2
    max_light_lanes: int = 2
    max_heavy_lanes: int = 1
    max_memory_percent: float = 85.0
    max_wsl_memory_percent: float = 85.0
    max_docker_memory_percent: float = 85.0
    max_gpu_percent: float = 90.0
    lost_worker_seconds: int = 120


@dataclass(frozen=True, slots=True)
class Admission:
    admitted: bool
    reason: str


class ResourceScheduler:
    def __init__(self, policy: ResourcePolicy = ResourcePolicy()) -> None:
        if (
            min(
                policy.max_agents,
                policy.max_light_lanes,
                policy.max_heavy_lanes,
                policy.lost_worker_seconds,
            )
            < 1
        ):
            raise ValueError("resource limits must be positive")
        self.policy = policy
        self._lanes: dict[str, str] = {}
        self._workers: dict[str, datetime] = {}
        self._ownership: dict[str, frozenset[str]] = {}
        self._assignments: dict[str, str] = {}

    def admit(
        self,
        work_id: str,
        lane: str,
        snapshot: Mapping[str, float | int],
        *,
        owned_paths: tuple[str, ...] = (),
    ) -> Admission:
        if lane not in {"light", "heavy"}:
            return Admission(False, "unknown lane")
        if work_id in self._lanes:
            return Admission(False, "work is already admitted")
        if float(snapshot.get("memory_percent", 0)) >= self.policy.max_memory_percent:
            return Admission(False, "memory pressure threshold reached")
        if float(snapshot.get("gpu_percent", 0)) >= self.policy.max_gpu_percent:
            return Admission(False, "GPU pressure threshold reached")
        if (
            float(snapshot.get("wsl_memory_percent", 0))
            >= self.policy.max_wsl_memory_percent
        ):
            return Admission(False, "WSL memory pressure threshold reached")
        if (
            float(snapshot.get("docker_memory_percent", 0))
            >= self.policy.max_docker_memory_percent
        ):
            return Admission(False, "Docker memory pressure threshold reached")
        normalized_paths = frozenset(
            path.replace("\\", "/").casefold().rstrip("/") for path in owned_paths
        )
        for owner, existing in self._ownership.items():
            if any(
                left == right
                or left.startswith(right + "/")
                or right.startswith(left + "/")
                for left in normalized_paths
                for right in existing
            ):
                return Admission(False, f"file ownership overlaps {owner}")
        limit = (
            self.policy.max_heavy_lanes
            if lane == "heavy"
            else self.policy.max_light_lanes
        )
        if sum(value == lane for value in self._lanes.values()) >= limit:
            return Admission(False, f"{lane} lane is serialized")
        if int(snapshot.get("agents", len(self._workers))) >= self.policy.max_agents:
            return Admission(False, "agent budget reached")
        self._lanes[work_id] = lane
        self._ownership[work_id] = normalized_paths
        return Admission(True, "resource policy admitted work")

    def release(self, work_id: str) -> bool:
        self._ownership.pop(work_id, None)
        for worker, assigned in tuple(self._assignments.items()):
            if assigned == work_id:
                self._assignments.pop(worker, None)
        return self._lanes.pop(work_id, None) is not None

    def heartbeat(self, worker_id: str, at: datetime | None = None) -> None:
        self._workers[worker_id] = at or datetime.now(timezone.utc)

    def assign_worker(self, worker_id: str, work_id: str) -> None:
        if work_id not in self._lanes:
            raise ValueError("work must be admitted before worker assignment")
        if (
            len(self._assignments) >= self.policy.max_agents
            and worker_id not in self._assignments
        ):
            raise ValueError("agent budget reached")
        self._assignments[worker_id] = work_id
        self.heartbeat(worker_id)

    def lost_workers(self, now: datetime | None = None) -> tuple[str, ...]:
        reference = now or datetime.now(timezone.utc)
        threshold = timedelta(seconds=self.policy.lost_worker_seconds)
        return tuple(
            sorted(
                worker
                for worker, last_seen in self._workers.items()
                if reference - last_seen > threshold
            )
        )

    def recover_lost(self, now: datetime | None = None) -> tuple[str, ...]:
        recovered: list[str] = []
        for worker in self.lost_workers(now):
            work_id = self._assignments.pop(worker, None)
            self._workers.pop(worker, None)
            if work_id is not None:
                self.release(work_id)
                recovered.append(work_id)
        return tuple(sorted(recovered))
