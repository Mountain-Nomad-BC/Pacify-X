"""Bounded session, graph, attribution, and backend operations for the memory vault."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from collections import deque
from itertools import islice
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import base64
import os
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

from .archive_io import portable_member_name, reject_path_links
from .bounded_walk import bounded_walk, WalkLimits
from .input_files import contained_file, read_file_image, cooperative_deadline
from .json_io import decode_json_object, bounded_json_text
from .memory_fabric import BackendResult, MemoryRecord, normalize_backend_result
from .memory_vault import MemoryVault, VaultWrite
from .numeric_inputs import (
    bounded_integer,
    bounded_items,
    bounded_sequence,
    bounded_text,
)


T = TypeVar("T")
WORD = re.compile(r"[a-z0-9]+")


def _write_new(path: Path, payload: Mapping[str, object]) -> None:
    rendered = bounded_json_text(dict(payload), max_bytes=256 * 1024)
    reject_path_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    reject_path_links(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(rendered)
        stream.flush()
        os.fsync(stream.fileno())


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
    """Bounded delta summaries with injective namespaces and checked legacy history."""

    def __init__(self, root: Path) -> None:
        reject_path_links(root)
        if root.exists() and not root.is_dir():
            raise ValueError("summary root must be a directory")
        self.root = root.resolve()

    def _identity(self, session_id: str):
        identity = bounded_text(
            session_id, "session identity", maximum=128, strip=False
        )
        if not identity.strip():
            raise ValueError("session identity must be nonempty")
        namespace = (
            "session-"
            + base64.b32encode(identity.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
            .lower()
        )
        return identity, namespace

    def _inventory(self, session_id: str):
        identity, namespace = self._identity(session_id)
        reject_path_links(self.root)
        directories = [self.root / namespace]
        legacy = re.sub(r"[^a-zA-Z0-9._-]", "-", identity)
        try:
            portable_member_name(legacy, allow_directory=False)
        except ValueError:
            legacy = ""
        if (
            legacy
            and legacy != namespace
            and legacy.casefold() not in {"quarantine", ".quarantine", "_quarantine"}
        ):
            directories.append(self.root / legacy)
        paths = []
        total_bytes = 0
        for directory in directories:
            reject_path_links(directory)
            if not directory.exists():
                continue
            if not directory.is_dir() or not directory.resolve().is_relative_to(
                self.root.resolve()
            ):
                raise ValueError("summary namespace must be a contained directory")
            inventory = bounded_walk(
                directory,
                limits=WalkLimits(
                    max_files=10000,
                    max_depth=1,
                    max_bytes=16 * 1024 * 1024,
                    max_entries=10001,
                    max_directories=1,
                    max_duration_seconds=60,
                ),
                symlink_policy="reject",
            )
            for entry in inventory.files:
                if not re.fullmatch(
                    r"[0-9]{6}-(checkpoint|final)\.json", entry.relative
                ):
                    raise ValueError("unclassified file in summary namespace")
                paths.append(entry.path)
                total_bytes += entry.size
                if len(paths) > 10000 or total_bytes > 16 * 1024 * 1024:
                    raise ValueError("summary history exceeds its aggregate budget")
        return identity, namespace, tuple(paths)

    def _paths(self, session_id: str) -> tuple[Path, ...]:
        return self._inventory(session_id)[2]

    def _history(self, session_id: str):
        identity, namespace, paths = self._inventory(session_id)
        deadline = cooperative_deadline()
        admitted = []
        total_bytes = 0
        for path in paths:
            path, info = contained_file(
                self.root, path.relative_to(self.root).as_posix()
            )
            total_bytes += info.st_size
            if info.st_size > 256 * 1024 or total_bytes > 16 * 1024 * 1024:
                raise ValueError(
                    "summary history exceeds its byte budget before acquisition"
                )
            admitted.append((path, info))
        rows = []
        fields = {
            "schema_version",
            "session_id",
            "start_event_id",
            "end_event_id",
            "processed_event_count",
            "lifecycle",
            "summary",
            "source_sha256",
            "created_utc",
        }
        for path, info in admitted:
            data = decode_json_object(
                read_file_image(path, info, limit=256 * 1024, deadline=deadline),
                max_bytes=256 * 1024,
                max_depth=8,
                max_nodes=10000,
            )
            if (
                set(data) != fields
                or data["schema_version"] != "1.0"
                or data["session_id"] != identity
            ):
                raise ValueError(
                    "summary history session identity or contract mismatch"
                )
            start = bounded_integer(
                data["start_event_id"], "summary start event", maximum=2**53 - 1
            )
            end = bounded_integer(
                data["end_event_id"],
                "summary end event",
                minimum=start,
                maximum=2**53 - 1,
            )
            count = bounded_integer(
                data["processed_event_count"], "processed events", maximum=10000
            )
            lifecycle = bounded_text(
                data["lifecycle"], "summary lifecycle", maximum=16, strip=False
            )
            if count > end - start + 1 or lifecycle not in {
                "checkpoint",
                "final",
            }:
                raise ValueError("summary history interval or lifecycle is invalid")
            if path.stem.split("-", 1)[1] != data["lifecycle"]:
                raise ValueError("summary filename and lifecycle disagree")
            summary = bounded_sequence(data["summary"], "summary facts", maximum=256)
            if any(
                type(item) is not str or not item or len(item) > 65536
                for item in summary
            ):
                raise ValueError("summary facts must be bounded nonempty text")
            for item in summary:
                item.encode("utf-8")
            if type(data["source_sha256"]) is not str or not re.fullmatch(
                "[0-9a-f]{64}", data["source_sha256"]
            ):
                raise ValueError("summary source digest is malformed")
            stamp = bounded_text(data["created_utc"], "summary timestamp", maximum=128)
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError("invalid summary timestamp") from error
            if parsed.tzinfo is None:
                raise ValueError("summary timestamp must declare its timezone")
            rows.append((int(path.name[:6]), start, end, data, path))
        rows.sort(key=lambda row: row[0])
        cursor = 0
        for sequence, row in enumerate(rows, 1):
            if row[0] != sequence or row[1] <= cursor:
                raise ValueError(
                    "summary history sequence gap, duplicate or overlapping interval"
                )
            cursor = row[2]
        return identity, namespace, rows, cursor

    def last_event_id(self, session_id: str) -> int:
        return self._history(session_id)[3]

    def summarize(
        self, session_id: str, events: Sequence[SessionEvent], *, max_facts: int = 12
    ) -> SummaryCheckpoint | None:
        max_facts = bounded_integer(max_facts, "maximum summary facts", maximum=256)
        self._identity(session_id)
        admitted = []
        identities = set()
        input_bytes = 0
        for event in bounded_items(events, "session events", maximum=10000):
            if type(event) is not SessionEvent:
                raise ValueError("summary events must be typed records")
            identity = bounded_integer(
                event.event_id, "session event identity", maximum=2**53 - 1
            )
            if identity in identities:
                raise ValueError("session event identities must be unique")
            identities.add(identity)
            kind = bounded_text(
                event.kind, "session event kind", maximum=128, strip=False
            )
            if type(event.content) is not str or len(event.content) > 65536:
                raise ValueError("session event content must be bounded text")
            if (
                type(event.created_at) is not datetime
                or event.created_at.tzinfo is None
            ):
                raise ValueError("session event timestamp must be timezone-aware")
            input_bytes += (
                len(kind.encode("utf-8")) + len(event.content.encode("utf-8")) + 32
            )
            if input_bytes > 8 * 1024 * 1024:
                raise ValueError("session events exceed their aggregate byte budget")
            admitted.append(event)
        identity, namespace, history, cursor = self._history(session_id)
        pending = tuple(
            sorted(
                (event for event in admitted if event.event_id > cursor),
                key=lambda event: event.event_id,
            )
        )
        if not pending:
            return None
        if len(history) >= 10000:
            raise ValueError("summary history file budget exhausted")
        lifecycle = "final" if pending[-1].kind == "SessionEnd" else "checkpoint"
        statements = []
        seen = set()
        summary_bytes = 0
        for event in pending:
            if event.kind in {"Stop", "SessionEnd"}:
                continue
            for sentence in re.split(r"(?<=[.!?])\s+|\r?\n+", event.content.strip()):
                normalized = " ".join(sentence.split())
                fingerprint = normalized.casefold()
                if normalized and fingerprint not in seen:
                    summary_bytes += len(normalized.encode("utf-8"))
                    if summary_bytes > 128 * 1024:
                        raise ValueError(
                            "summary facts exceed their aggregate byte budget"
                        )
                    statements.append(normalized)
                    seen.add(fingerprint)
                if len(statements) >= max_facts:
                    break
            if len(statements) >= max_facts:
                break
        canonical = "\n".join(
            f"{event.event_id}\0{event.kind}\0{event.content}" for event in pending
        )
        path = self.root / namespace / f"{len(history) + 1:06d}-{lifecycle}.json"
        reject_path_links(path)
        if not path.resolve().is_relative_to(self.root.resolve()):
            raise ValueError("summary output escapes its root")
        payload = {
            "schema_version": "1.0",
            "session_id": identity,
            "start_event_id": pending[0].event_id,
            "end_event_id": pending[-1].event_id,
            "processed_event_count": len(pending),
            "lifecycle": lifecycle,
            "summary": statements,
            "source_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        _write_new(path, payload)
        return SummaryCheckpoint(
            identity,
            pending[0].event_id,
            pending[-1].event_id,
            len(pending),
            lifecycle,
            tuple(statements),
            payload["source_sha256"],
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
    inspected_nodes: int = 0
    edges_observed: int = 0


def build_graph_clusters(
    nodes: Iterable[GraphNode],
    edges: Iterable[tuple[str, str]],
    *,
    max_initial_nodes: int = 1000,
    max_cluster_size: int = 64,
) -> ClusterResult:
    max_initial_nodes = bounded_integer(
        max_initial_nodes, "initial graph nodes", maximum=10000
    )
    max_cluster_size = bounded_integer(
        max_cluster_size, "graph cluster size", maximum=10000
    )
    supplied = tuple(
        islice(
            bounded_items(nodes, "graph nodes", maximum=10001), max_initial_nodes + 1
        )
    )
    selected = supplied[:max_initial_nodes]
    lookup = {}
    input_bytes = 0
    for node in selected:
        if type(node) is not GraphNode:
            raise ValueError("graph requires typed nodes")
        identity = bounded_text(node.node_id, "graph node identity")
        if identity in lookup:
            raise ValueError("graph node identities must be unique")
        if type(node.text) is not str or len(node.text) > 65536:
            raise ValueError("graph node text exceeds its budget")
        provenance = tuple(
            bounded_text(value, "graph provenance", maximum=512)
            for value in bounded_sequence(
                node.provenance, "graph provenance", maximum=64
            )
        )
        input_bytes += len(node.text.encode("utf-8")) + len(identity.encode("utf-8"))
        input_bytes += sum(len(value.encode("utf-8")) for value in provenance)
        if input_bytes > 8 * 1024 * 1024:
            raise ValueError("graph inputs exceed their aggregate byte budget")
        lookup[identity] = GraphNode(identity, node.text, provenance)
    adjacency = {node_id: set() for node_id in lookup}
    missing = set()
    edges_observed = 0
    edge_bytes = 0
    for edge in bounded_items(edges, "graph edges", maximum=20000):
        edge = bounded_sequence(edge, "graph edge", minimum=2, maximum=2)
        left, right = (bounded_text(value, "edge endpoint") for value in edge)
        edges_observed += 1
        edge_bytes += len(left.encode("utf-8")) + len(right.encode("utf-8"))
        if edge_bytes > 8 * 1024 * 1024:
            raise ValueError("graph edges exceed their aggregate byte budget")
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
        queue = deque([seed])
        queued = {seed}
        members = []
        while queue and len(members) < max_cluster_size:
            node_id = queue.popleft()
            if node_id in assigned or node_id not in lookup:
                continue
            assigned.add(node_id)
            members.append(node_id)
            for neighbor in sorted(adjacency[node_id]):
                if neighbor not in assigned and neighbor not in queued:
                    queued.add(neighbor)
                    queue.append(neighbor)
        terms = []
        seen_terms = set()
        provenance = set()
        for node_id in members:
            node = lookup[node_id]
            provenance.update(node.provenance)
            if len(terms) < 32:
                for match in WORD.finditer(node.text.casefold()):
                    term = match.group()
                    if term not in seen_terms:
                        terms.append(term)
                        seen_terms.add(term)
                    if len(terms) == 32:
                        break
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
        len(supplied),
        edges_observed,
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
