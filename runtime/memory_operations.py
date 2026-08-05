"""Bounded session, graph, attribution, and backend operations for the memory vault."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

from .memory_fabric import BackendResult, MemoryRecord, normalize_backend_result
from .memory_vault import MemoryVault, VaultWrite


T = TypeVar("T")
WORD = re.compile(r"[a-z0-9]+")


def _write_new(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(dict(payload), stream, indent=2)
        stream.write("\n")


@dataclass(frozen=True, slots=True)
class SessionEvent:
    event_id: int
    kind: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SummaryCheckpoint:
    session_id: str
    start_event_id: int
    end_event_id: int
    processed_event_count: int
    lifecycle: str
    summary: tuple[str, ...]
    source_sha256: str
    path: str


class SessionSummaryLedger:
    """Summarize only unprocessed event ranges; Stop checkpoints and SessionEnd finalizes."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _paths(self, session_id: str) -> tuple[Path, ...]:
        directory = self.root / re.sub(r"[^a-zA-Z0-9._-]", "-", session_id)
        return tuple(sorted(directory.glob("*.json"))) if directory.is_dir() else ()

    def last_event_id(self, session_id: str) -> int:
        paths = self._paths(session_id)
        return (
            int(json.loads(paths[-1].read_text(encoding="utf-8"))["end_event_id"])
            if paths
            else 0
        )

    def summarize(
        self, session_id: str, events: Sequence[SessionEvent], *, max_facts: int = 12
    ) -> SummaryCheckpoint | None:
        if max_facts < 1:
            raise ValueError("max facts must be positive")
        cursor = self.last_event_id(session_id)
        pending = tuple(
            sorted(
                (event for event in events if event.event_id > cursor),
                key=lambda item: item.event_id,
            )
        )
        if not pending:
            return None
        if any(
            left.event_id >= right.event_id for left, right in zip(pending, pending[1:])
        ):
            raise ValueError("session event IDs must be strictly increasing")
        lifecycle = "final" if pending[-1].kind == "SessionEnd" else "checkpoint"
        statements = []
        seen = set()
        for event in pending:
            if event.kind in {"Stop", "SessionEnd"}:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+|\r?\n+", event.content.strip()):
                normalized = " ".join(sentence.split())
                fingerprint = normalized.casefold()
                if normalized and fingerprint not in seen:
                    statements.append(normalized)
                    seen.add(fingerprint)
                if len(statements) >= max_facts:
                    break
            if len(statements) >= max_facts:
                break
        canonical = "\n".join(
            f"{event.event_id}\0{event.kind}\0{event.content}" for event in pending
        )
        paths = self._paths(session_id)
        sequence = len(paths) + 1
        path = (
            self.root
            / re.sub(r"[^a-zA-Z0-9._-]", "-", session_id)
            / f"{sequence:06d}-{lifecycle}.json"
        )
        payload = {
            "schema_version": "1.0",
            "session_id": session_id,
            "start_event_id": pending[0].event_id,
            "end_event_id": pending[-1].event_id,
            "processed_event_count": len(pending),
            "lifecycle": lifecycle,
            "summary": statements,
            "source_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        _write_new(path, payload)
        return SummaryCheckpoint(
            session_id,
            pending[0].event_id,
            pending[-1].event_id,
            len(pending),
            lifecycle,
            tuple(statements),
            str(payload["source_sha256"]),
            path.relative_to(self.root).as_posix(),
        )


@dataclass(frozen=True, slots=True)
class GraphNode:
    node_id: str
    text: str
    provenance: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GraphCluster:
    cluster_id: str
    member_ids: tuple[str, ...]
    novel_terms: tuple[str, ...]
    provenance: tuple[str, ...]
    fallback_used: bool


@dataclass(frozen=True, slots=True)
class ClusterResult:
    clusters: tuple[GraphCluster, ...]
    enumerated_nodes: int
    truncated: bool
    missing_edge_endpoints: tuple[str, ...]


def build_graph_clusters(
    nodes: Iterable[GraphNode],
    edges: Iterable[tuple[str, str]],
    *,
    max_initial_nodes: int = 1000,
    max_cluster_size: int = 64,
) -> ClusterResult:
    if min(max_initial_nodes, max_cluster_size) < 1:
        raise ValueError("graph bounds must be positive")
    supplied = tuple(nodes)
    selected = supplied[:max_initial_nodes]
    lookup = {node.node_id: node for node in selected}
    adjacency = {node_id: set() for node_id in lookup}
    missing = set()
    for left, right in edges:
        if left not in lookup or right not in lookup:
            if left not in lookup:
                missing.add(left)
            if right not in lookup:
                missing.add(right)
            continue
        adjacency[left].add(right)
        adjacency[right].add(left)
    assigned = set()
    clusters = []
    for seed in sorted(lookup):
        if seed in assigned:
            continue
        queue = [seed]
        members = []
        while queue and len(members) < max_cluster_size:
            node_id = queue.pop(0)
            if node_id in assigned or node_id not in lookup:
                continue
            assigned.add(node_id)
            members.append(node_id)
            queue.extend(sorted(adjacency[node_id] - assigned))
        terms = []
        seen_terms = set()
        provenance = set()
        for node_id in members:
            node = lookup[node_id]
            provenance.update(node.provenance)
            for term in WORD.findall(node.text.casefold()):
                if term not in seen_terms:
                    terms.append(term)
                    seen_terms.add(term)
        clusters.append(
            GraphCluster(
                f"cluster-{len(clusters) + 1:04d}",
                tuple(members),
                tuple(terms[:32]),
                tuple(sorted(provenance)),
                not any(adjacency[node_id] for node_id in members),
            )
        )
    return ClusterResult(
        tuple(clusters),
        len(selected),
        len(supplied) > len(selected),
        tuple(sorted(missing)),
    )


@dataclass(slots=True)
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0
    failures: int = 0
    opened_at: datetime | None = None

    def allow(self, now: datetime) -> bool:
        if self.opened_at is None:
            return True
        if now - self.opened_at >= timedelta(seconds=self.cooldown_seconds):
            self.failures = 0
            self.opened_at = None
            return True
        return False

    def success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def failure(self, now: datetime) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = now


@dataclass(frozen=True, slots=True)
class OperationOutcome:
    operation: str
    status: str
    value: object | None
    error_code: str | None
    alert_required: bool
    backoff_seconds: float


class StateKVGuard:
    def __init__(
        self, *, failure_threshold: int = 3, cooldown_seconds: float = 30.0
    ) -> None:
        self.breakers: dict[str, CircuitBreaker] = {}
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

    def execute(
        self, operation: str, function: Callable[[], T], *, timeout_seconds: float
    ) -> OperationOutcome:
        if timeout_seconds <= 0:
            raise ValueError("operation timeout must be positive")
        now = datetime.now(timezone.utc)
        breaker = self.breakers.setdefault(
            operation, CircuitBreaker(self.failure_threshold, self.cooldown_seconds)
        )
        if not breaker.allow(now):
            return OperationOutcome(
                operation,
                "circuit_open",
                None,
                "CircuitOpen",
                True,
                self.cooldown_seconds,
            )
        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"memory-{operation}"
        )
        future = executor.submit(function)
        try:
            value = future.result(timeout=timeout_seconds)
        except FutureTimeout:
            future.cancel()
            breaker.failure(now)
            return OperationOutcome(
                operation,
                "error",
                None,
                "TimeoutError",
                True,
                min(self.cooldown_seconds, 2**breaker.failures),
            )
        except Exception as error:  # boundary intentionally converts backend failures
            breaker.failure(now)
            return OperationOutcome(
                operation,
                "error",
                None,
                type(error).__name__,
                True,
                min(self.cooldown_seconds, 2**breaker.failures),
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        breaker.success()
        return OperationOutcome(operation, "ok", value, None, False, 0.0)


def normalize_action_attribution(
    payload: Mapping[str, object], *, authenticated_agent_id: str
) -> dict[str, object]:
    if not authenticated_agent_id:
        raise ValueError("authenticated agent identity is required")
    result = dict(payload)
    supplied = str(result.get("agentId", authenticated_agent_id))
    created_by = str(result.get("createdBy", authenticated_agent_id))
    if supplied != authenticated_agent_id or created_by != authenticated_agent_id:
        raise ValueError(
            "memory action attribution does not match authenticated identity"
        )
    result["agentId"] = authenticated_agent_id
    result["createdBy"] = authenticated_agent_id
    if "records" in result:
        result["records"] = [
            normalize_action_attribution(
                dict(record), authenticated_agent_id=authenticated_agent_id
            )
            for record in result.get("records", ())
        ]
    return result


def guarded_search(
    function: Callable[[], Sequence[object]],
    guard: StateKVGuard,
    *,
    timeout_seconds: float,
) -> BackendResult:
    outcome = guard.execute("smart-search", function, timeout_seconds=timeout_seconds)
    if outcome.status != "ok":
        return normalize_backend_result(
            error=RuntimeError(outcome.error_code or outcome.status)
        )
    return normalize_backend_result(items=tuple(outcome.value or ()))


def persist_with_graph_isolation(
    vault: MemoryVault,
    record: MemoryRecord,
    graph_write: Callable[[VaultWrite], object],
    guard: StateKVGuard,
    *,
    timeout_seconds: float,
) -> dict[str, object]:
    canonical = vault.append(record)
    graph = guard.execute(
        "graph-write", lambda: graph_write(canonical), timeout_seconds=timeout_seconds
    )
    return {
        "canonical_persisted": True,
        "memory_id": canonical.memory_id,
        "revision": canonical.revision,
        "graph_status": graph.status,
        "graph_error": graph.error_code,
        "reconciliation_required": graph.status != "ok",
    }
