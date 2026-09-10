"""Governed, data-free lifecycle owner for local GGUF llama.cpp servers.

Canonical model bytes remain user-owned.  Pacify-X records only stable filesystem
identity, SHA-256, bounded GGUF metadata, an immutable launch plan, and owned
process/session receipts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time
from typing import Callable, Iterable, Mapping, Sequence
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from runtime.file_lock import FileLock
from runtime.process_supervisor import ProcessSupervisor
from runtime.resource_lifecycle import ResourceManager, RunState


MAX_GGUF_METADATA_BYTES = 1_048_576
MAX_GGUF_METADATA_ITEMS = 4_096
MAX_MODEL_BYTES = 1024**4
SUPPORTED_GGUF_VERSIONS = frozenset({2, 3})
DEFAULT_ARCHITECTURES = frozenset(
    {"llama", "mistral", "qwen2", "qwen3", "gemma", "gemma2", "phi2", "phi3"}
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    candidate = os.path.normcase(str(path))
    for root in roots:
        try:
            if os.path.commonpath((candidate, os.path.normcase(str(root)))) == os.path.normcase(str(root)):
                return True
        except ValueError:
            continue
    return False


def _linked(path: Path, stop: Path) -> bool:
    current = path
    while True:
        try:
            stat = current.lstat()
        except OSError:
            return True
        if current.is_symlink() or bool(getattr(stat, "st_file_attributes", 0) & 0x400):
            return True
        if current == stop:
            return False
        if current.parent == current:
            return True
        current = current.parent


class _Reader:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.offset = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.raw):
            raise ValueError("GGUF metadata is truncated or exceeds the inspection bound")
        result = self.raw[self.offset : self.offset + size]
        self.offset += size
        return result

    def unpack(self, code: str) -> object:
        size = struct.calcsize("<" + code)
        return struct.unpack("<" + code, self.take(size))[0]

    def string(self) -> str:
        size = int(self.unpack("Q"))
        if size > MAX_GGUF_METADATA_BYTES:
            raise ValueError("GGUF string exceeds the inspection bound")
        try:
            return self.take(size).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("GGUF metadata is not valid UTF-8") from error


_SCALARS = {0: "B", 1: "b", 2: "H", 3: "h", 4: "I", 5: "i", 6: "f", 7: "?", 10: "Q", 11: "q", 12: "d"}


def _value(reader: _Reader, kind: int, *, depth: int = 0) -> object:
    if depth > 2:
        raise ValueError("GGUF metadata nesting exceeds the inspection bound")
    if kind in _SCALARS:
        return reader.unpack(_SCALARS[kind])
    if kind == 8:
        return reader.string()
    if kind == 9:
        element_kind = int(reader.unpack("I"))
        count = int(reader.unpack("Q"))
        if count > MAX_GGUF_METADATA_ITEMS:
            raise ValueError("GGUF metadata array exceeds the inspection bound")
        return [_value(reader, element_kind, depth=depth + 1) for _ in range(count)]
    raise ValueError(f"unsupported GGUF metadata value type {kind}")


def parse_gguf_metadata(raw: bytes) -> dict[str, object]:
    """Parse only the bounded GGUF header/metadata area; tensor bytes are untouched."""
    if len(raw) > MAX_GGUF_METADATA_BYTES:
        raise ValueError("GGUF metadata inspection buffer is over budget")
    reader = _Reader(raw)
    if reader.take(4) != b"GGUF":
        raise ValueError("model does not have a GGUF header")
    version = int(reader.unpack("I"))
    tensor_count = int(reader.unpack("Q"))
    metadata_count = int(reader.unpack("Q"))
    if version not in SUPPORTED_GGUF_VERSIONS:
        raise ValueError("GGUF version is not supported")
    if tensor_count <= 0:
        raise ValueError("GGUF model declares no tensors")
    if metadata_count <= 0 or metadata_count > MAX_GGUF_METADATA_ITEMS:
        raise ValueError("GGUF metadata count is invalid")
    metadata: dict[str, object] = {}
    for _ in range(metadata_count):
        key = reader.string()
        if not key or len(key) > 256 or key in metadata:
            raise ValueError("GGUF metadata key is invalid or duplicated")
        metadata[key] = _value(reader, int(reader.unpack("I")))
    architecture = metadata.get("general.architecture")
    if not isinstance(architecture, str) or not architecture:
        raise ValueError("GGUF architecture metadata is missing")
    return {
        "version": version,
        "tensor_count": tensor_count,
        "metadata_count": metadata_count,
        "architecture": architecture,
        "name": metadata.get("general.name"),
        "file_type": metadata.get("general.file_type"),
        "context_length": metadata.get(f"{architecture}.context_length"),
        "embedding_length": metadata.get(f"{architecture}.embedding_length"),
    }


@dataclass(frozen=True, slots=True)
class ModelAdmission:
    schema_version: str
    model_path: str
    model_sha256: str
    size_bytes: int
    device: int
    inode: int
    mtime_ns: int
    metadata: dict[str, object]
    compatible: bool
    compatibility_reasons: tuple[str, ...]
    admitted_at: str


@dataclass(frozen=True, slots=True)
class ServerPlan:
    schema_version: str
    plan_id: str
    model: dict[str, object]
    executable_path: str
    executable_sha256: str
    host: str
    port: int
    context_size: int
    gpu_layers: int
    command: tuple[str, ...]
    plan_sha256: str
    created_at: str


class LocalModelRuntime:
    def __init__(
        self,
        root: Path,
        *,
        allowed_model_roots: Iterable[Path],
        allowed_runtime_roots: Iterable[Path],
        manager: ResourceManager | None = None,
        readiness_probe: Callable[[str, float], bool] | None = None,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.model_roots = tuple(path.resolve(strict=True) for path in allowed_model_roots)
        self.runtime_roots = tuple(path.resolve(strict=True) for path in allowed_runtime_roots)
        if not self.model_roots or not self.runtime_roots:
            raise ValueError("explicit model and runtime roots are required")
        state = self.root / ".engineering-bootstrap" / "local-model-runtime"
        self.event_path = state / "events.jsonl"
        self.head_path = state / "head.json"
        self.manager = manager or ResourceManager(
            self.root / ".engineering-bootstrap" / "resources" / "ledger.json",
            receipt_dir=self.root / ".engineering-bootstrap" / "resources" / "receipts",
        )
        self.readiness_probe = readiness_probe or self._http_ready

    @staticmethod
    def _http_ready(origin: str, timeout: float) -> bool:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(Request(origin + "/health", method="GET"), timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except OSError:
            return False

    @staticmethod
    def _digest_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _admitted_path(self, value: Path, roots: Sequence[Path], suffix: str | None = None) -> Path:
        path = value.resolve(strict=True)
        root = next((item for item in roots if _inside(path, (item,))), None)
        if root is None or not path.is_file() or _linked(path, root):
            raise ValueError("path is outside its admitted root or crosses a link/reparse point")
        if suffix and path.suffix.lower() != suffix:
            raise ValueError(f"path must end in {suffix}")
        return path

    def inspect_model(
        self, model_path: Path, *, supported_architectures: Iterable[str] = DEFAULT_ARCHITECTURES
    ) -> ModelAdmission:
        path = self._admitted_path(model_path, self.model_roots, ".gguf")
        before = path.stat()
        if before.st_size <= 24 or before.st_size > MAX_MODEL_BYTES:
            raise ValueError("GGUF file size is invalid or over budget")
        with path.open("rb") as stream:
            metadata = parse_gguf_metadata(stream.read(MAX_GGUF_METADATA_BYTES))
        digest = self._digest_file(path)
        after = path.stat()
        identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("GGUF file changed during admission")
        supported = frozenset(str(item).strip().lower() for item in supported_architectures)
        reasons: list[str] = []
        architecture = str(metadata["architecture"]).lower()
        if architecture not in supported:
            reasons.append("architecture_not_supported")
        if metadata.get("context_length") is None:
            reasons.append("context_length_unknown")
        return ModelAdmission(
            "px.local-model-admission/1.0", str(path), digest, after.st_size,
            after.st_dev, after.st_ino, after.st_mtime_ns, metadata, not reasons,
            tuple(reasons), _now(),
        )

    def plan_server(
        self,
        admission: ModelAdmission,
        executable_path: Path,
        *,
        port: int,
        context_size: int,
        gpu_layers: int = 0,
    ) -> ServerPlan:
        if not admission.compatible:
            raise ValueError("model admission is not compatible")
        if not 1024 <= port <= 65535 or not 128 <= context_size <= 1_048_576 or not 0 <= gpu_layers <= 10_000:
            raise ValueError("server port, context size, or GPU layer count is invalid")
        executable = self._admitted_path(executable_path, self.runtime_roots)
        if self._digest_file(Path(admission.model_path)) != admission.model_sha256:
            raise ValueError("admitted model digest is stale")
        executable_sha = self._digest_file(executable)
        command = (
            str(executable), "--model", admission.model_path, "--host", "127.0.0.1",
            "--port", str(port), "--ctx-size", str(context_size), "--n-gpu-layers", str(gpu_layers),
        )
        base = {
            "schema_version": "px.local-model-server-plan/1.0", "plan_id": f"local-model-plan-{uuid4().hex}",
            "model": asdict(admission), "executable_path": str(executable),
            "executable_sha256": executable_sha, "host": "127.0.0.1", "port": port,
            "context_size": context_size, "gpu_layers": gpu_layers, "command": list(command),
            "created_at": _now(),
        }
        return ServerPlan(**{**base, "command": command}, plan_sha256=_sha(base))

    def _load_events_unlocked(self) -> list[dict[str, object]]:
        if not self.event_path.is_file():
            return []
        events = [json.loads(line) for line in self.event_path.read_text(encoding="utf-8").splitlines() if line]
        previous = None
        for event in events:
            supplied = event.get("event_sha256")
            body = {key: value for key, value in event.items() if key != "event_sha256"}
            if event.get("previous_event_sha256") != previous or supplied != _sha(body):
                raise ValueError("local-model lifecycle event chain is invalid")
            previous = str(supplied)
        return events

    def _load_events(self) -> list[dict[str, object]]:
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.event_path.with_suffix(".lock"), timeout_seconds=30.0):
            return self._load_events_unlocked()

    def _append(self, event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
        self.event_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.event_path.with_suffix(".lock"), timeout_seconds=30.0):
            events = self._load_events_unlocked()
            body = {
                "schema_version": "px.local-model-lifecycle-event/1.0",
                "sequence": len(events) + 1,
                "event_id": f"local-model-event-{uuid4().hex}",
                "event_type": event_type,
                "timestamp": _now(),
                "previous_event_sha256": events[-1]["event_sha256"] if events else None,
                "payload": dict(payload),
            }
            event = {**body, "event_sha256": _sha(body)}
            with self.event_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            head = {"schema_version": "px.local-model-head/1.0", "event_id": event["event_id"], "event_sha256": event["event_sha256"]}
            temporary = self.head_path.with_suffix(f".{uuid4().hex}.tmp")
            temporary.write_text(json.dumps(head, indent=2) + "\n", encoding="utf-8", newline="\n")
            os.replace(temporary, self.head_path)
        return event

    def start(self, plan: ServerPlan, *, readiness_timeout_seconds: float = 30.0) -> dict[str, object]:
        plan_body = {key: value for key, value in asdict(plan).items() if key != "plan_sha256"}
        if _sha(plan_body) != plan.plan_sha256:
            raise ValueError("local-model server plan integrity failed")
        if self._digest_file(Path(plan.model["model_path"])) != plan.model["model_sha256"]:
            raise ValueError("model changed after planning")
        if self._digest_file(Path(plan.executable_path)) != plan.executable_sha256:
            raise ValueError("runtime changed after planning")
        session_id = f"local-model-session-{uuid4().hex}"
        record, process = self.manager.spawn_owned_process(
            plan.command, cwd=Path(plan.executable_path).parent, project_id=self.root.name,
            run_id=session_id, lane_id="local-model", creator="runtime.local_model_runtime",
            ownership="durable",
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=False,
        )
        cleanup_completed = False
        try:
            deadline = time.monotonic() + readiness_timeout_seconds
            origin = f"http://127.0.0.1:{plan.port}"
            while time.monotonic() < deadline and process.poll() is None:
                if self.readiness_probe(origin, min(1.0, max(0.05, deadline - time.monotonic()))):
                    event = self._append("started", {"session_id": session_id, "resource_id": record.resource_id, "pid": process.pid, "plan": asdict(plan), "origin": origin})
                    return {"session_id": session_id, "state": "running", "resource_id": record.resource_id, "origin": origin, "event_sha256": event["event_sha256"]}
                time.sleep(0.05)
            cleanup = self.manager.terminate_owned_process(record.resource_id)
            cleanup_completed = cleanup.resources_reclaimed == 1
            self._append("start_failed", {"session_id": session_id, "resource_id": record.resource_id, "cleanup_id": cleanup.cleanup_id, "tree_closed": cleanup.resources_reclaimed == 1})
            raise RuntimeError("llama.cpp server did not become ready within the bounded startup window")

        except BaseException as error:
            if not cleanup_completed:
                self.manager.settle_failed_launch(record.resource_id, error)
            raise

    def _session_event(self, session_id: str) -> dict[str, object]:
        matches = [event for event in self._load_events() if event["payload"].get("session_id") == session_id]
        if not matches:
            raise KeyError(session_id)
        return matches[-1]

    def status(self, session_id: str) -> dict[str, object]:
        event = self._session_event(session_id)
        resource_id = str(event["payload"].get("resource_id", ""))
        record = self.manager.ledger.get(resource_id)
        state = "running" if record.active and event["event_type"] == "started" else str(event["event_type"])
        return {"session_id": session_id, "state": state, "resource_id": resource_id, "pid": record.pid, "process_identity": record.process_identity, "event_sha256": event["event_sha256"]}

    def stop(self, session_id: str, *, supplied_authority: bool) -> dict[str, object]:
        if supplied_authority is not True:
            raise PermissionError("explicit stop/unload authority is required")
        current = self.status(session_id)
        resource_id = str(current["resource_id"])
        if current["state"] != "running":
            return current
        if resource_id in self.manager._processes:
            cleanup = self.manager.terminate_owned_process(resource_id)
            tree_closed = cleanup.resources_reclaimed == 1 and not cleanup.errors
            disposition = cleanup.cleanup_id
        else:
            result = ProcessSupervisor(self.manager).reconcile_persisted(resource_id, supplied_authority=True)
            tree_closed = bool(result["tree_closed"])
            disposition = str(result["status"])
        if not tree_closed:
            raise RuntimeError("owned llama.cpp process tree closure was not proven")
        event = self._append("stopped", {"session_id": session_id, "resource_id": resource_id, "disposition": disposition, "tree_closed": True, "model_deleted": False})
        return {"session_id": session_id, "state": "stopped", "resource_id": resource_id, "tree_closed": True, "model_deleted": False, "event_sha256": event["event_sha256"]}

    def unload(self, session_id: str, *, supplied_authority: bool) -> dict[str, object]:
        return self.stop(session_id, supplied_authority=supplied_authority)

    def recover(self, session_id: str) -> dict[str, object]:
        current = self.status(session_id)
        if current["state"] != "running":
            return current
        resource_id = str(current["resource_id"])
        expected_pid = int(current["pid"])
        if not self.manager.persisted_process_has_exited(resource_id, expected_pid=expected_pid):
            return current
        self.manager.complete_persisted_process_after_exit(resource_id, expected_pid=expected_pid, run_state=RunState.FAILED)
        event = self._append("recovered_absent", {"session_id": session_id, "resource_id": resource_id, "tree_closed": True, "restart_requires_fresh_plan": True})
        return {"session_id": session_id, "state": "recovered_absent", "resource_id": resource_id, "tree_closed": True, "restart_requires_fresh_plan": True, "event_sha256": event["event_sha256"]}
