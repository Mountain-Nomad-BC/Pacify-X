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
import math
import os
from pathlib import Path
import struct
import subprocess
import time
from typing import Callable, Iterable, Mapping, Sequence
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .file_lock import FileLock
from .process_supervisor import ProcessSupervisor
from .resource_lifecycle import ResourceManager, RunState
from .model_pool import ModelPool, PoolModelSpec
from .model_profile import ModelRuntimeProfile
from .llama_cpp_capabilities import (
    LlamaCppCapabilityFingerprint,
    LlamaCppLaunchPolicy,
    assert_fingerprint_current,
    render_launch_policy,
)


MAX_GGUF_METADATA_BYTES = 1_048_576
MAX_GGUF_METADATA_ITEMS = 4_096
MAX_MODEL_BYTES = 1024**4
SUPPORTED_GGUF_VERSIONS = frozenset({2, 3})
DEFAULT_ARCHITECTURES = frozenset(
    {
        "llama", "mistral", "qwen2", "qwen3", "qwen3moe", "qwen3next",
        "qwen35", "qwen35moe", "gemma", "gemma2", "phi2", "phi3",
    }
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


class _ReaderExhausted(Exception):
    """Raised when the bounded inspection buffer ends before metadata does."""


class _Reader:
    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.offset = 0

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.raw):
            raise _ReaderExhausted
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


def _skip_value(reader: _Reader, kind: int, *, depth: int = 0) -> None:
    """Advance past one metadata value without materialising it."""
    if depth > 2:
        raise ValueError("GGUF metadata nesting exceeds the inspection bound")
    if kind in _SCALARS:
        reader.unpack(_SCALARS[kind])
        return
    if kind == 8:
        reader.string()
        return
    if kind == 9:
        element_kind = int(reader.unpack("I"))
        count = int(reader.unpack("Q"))
        for _ in range(count):
            _skip_value(reader, element_kind, depth=depth + 1)
        return
    raise ValueError(f"unsupported GGUF metadata value type {kind}")


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
            # Large arrays (e.g. the tokenizer vocabulary) are not needed by the
            # bounded header inspection: skip their bytes without rejecting the file.
            for _ in range(count):
                _skip_value(reader, element_kind, depth=depth + 1)
            return {"skipped": True, "count": count}
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
    truncated = False
    for _ in range(metadata_count):
        try:
            key = reader.string()
        except _ReaderExhausted:
            # The bounded inspection window ended inside a large metadata array
            # (typically the tokenizer vocabulary). Facts already collected before
            # the array remain authoritative; stop cleanly rather than fail closed.
            truncated = True
            break
        if not key or len(key) > 256 or key in metadata:
            raise ValueError("GGUF metadata key is invalid or duplicated")
        try:
            metadata[key] = _value(reader, int(reader.unpack("I")))
        except _ReaderExhausted:
            truncated = True
            break
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
        "metadata_truncated_at_bound": truncated,
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
    gpu_layers: int | str
    command: tuple[str, ...]
    plan_sha256: str
    created_at: str
    capability_fingerprint_sha256: str | None = None
    launch_policy: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class RouterPoolPlan:
    schema_version: str
    plan_id: str
    models: tuple[dict[str, object], ...]
    executable_path: str
    executable_sha256: str
    preset_path: str
    preset_sha256: str
    host: str
    port: int
    models_max: int
    command: tuple[str, ...]
    plan_sha256: str
    created_at: str


@dataclass(frozen=True, slots=True)
class RetrievalModelServicesPlan:
    schema_version: str
    embedding_model_id: str
    embedding_revision: str
    embedding_server: ServerPlan
    reranker_model_id: str | None
    reranker_revision: str | None
    reranker_server: ServerPlan | None
    retrieval_policy_sha256: str
    resource_receipt_sha256: str



class LocalModelRuntime:
    def __init__(
        self,
        root: Path,
        *,
        allowed_model_roots: Iterable[Path],
        allowed_runtime_roots: Iterable[Path],
        manager: ResourceManager | None = None,
        readiness_probe: Callable[[str, float], bool] | None = None,
        allowed_config_roots: Iterable[Path] | None = None,
        router_request: Callable[[str, str, Mapping[str, object] | None, float], object] | None = None,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.model_roots = tuple(path.resolve(strict=True) for path in allowed_model_roots)
        self.runtime_roots = tuple(path.resolve(strict=True) for path in allowed_runtime_roots)
        config_roots = tuple(allowed_config_roots) if allowed_config_roots is not None else self.runtime_roots
        self.config_roots = tuple(path.resolve(strict=True) for path in config_roots)
        if not self.model_roots or not self.runtime_roots or not self.config_roots:
            raise ValueError("explicit model, runtime, and config roots are required")
        state = self.root / ".engineering-bootstrap" / "local-model-runtime"
        self.event_path = state / "events.jsonl"
        self.head_path = state / "head.json"
        self.manager = manager or ResourceManager(
            self.root / ".engineering-bootstrap" / "resources" / "ledger.json",
            receipt_dir=self.root / ".engineering-bootstrap" / "resources" / "receipts",
        )
        self.readiness_probe = readiness_probe or self._http_ready
        self.router_request = router_request or self._http_json

    @staticmethod
    def _http_ready(origin: str, timeout: float) -> bool:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(Request(origin + "/health", method="GET"), timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except OSError:
            return False

    @staticmethod
    def _http_json(method: str, url: str, payload: Mapping[str, object] | None, timeout: float) -> object:
        if method not in {"GET", "POST"}:
            raise ValueError("router HTTP method must be GET or POST")
        if not url.startswith("http://127.0.0.1:"):
            raise ValueError("local model router requests require literal loopback")
        if type(timeout) not in (int, float) or type(timeout) is bool or not 0 < float(timeout) <= 30:
            raise ValueError("router HTTP timeout must be in (0, 30]")
        body = None if payload is None else json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=body, headers=headers, method=method)
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=float(timeout)) as response:
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("local model router response exceeds the bounded JSON contract")
            if not 200 <= int(response.status) < 300:
                raise RuntimeError(f"local model router returned HTTP {response.status}")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError("local model router returned invalid JSON") from error

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
        launch_policy: LlamaCppLaunchPolicy | None = None,
        capability_fingerprint: LlamaCppCapabilityFingerprint | None = None,
    ) -> ServerPlan:
        """Create an immutable llama-server plan.

        The legacy integer ``gpu_layers`` interface remains available for existing
        callers.  Modern placement/performance controls must use a typed
        ``launch_policy`` bound to a capability fingerprint for the exact pinned
        executable; unsupported or stale options fail closed.
        """
        if not admission.compatible:
            raise ValueError("model admission is not compatible")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("server port is invalid")
        if type(context_size) is not int or not 128 <= context_size <= 1_048_576:
            raise ValueError("server context size is invalid")
        if type(gpu_layers) is not int or not 0 <= gpu_layers <= 10_000:
            raise ValueError("legacy GPU layer count is invalid")
        executable = self._admitted_path(executable_path, self.runtime_roots)
        if self._digest_file(Path(admission.model_path)) != admission.model_sha256:
            raise ValueError("admitted model digest is stale")
        executable_sha = self._digest_file(executable)

        capability_sha: str | None = None
        policy_mapping: dict[str, object] | None = None
        effective_gpu_layers: int | str = gpu_layers
        extra_args: tuple[str, ...] = ()
        if launch_policy is not None or capability_fingerprint is not None:
            if type(launch_policy) is not LlamaCppLaunchPolicy or type(capability_fingerprint) is not LlamaCppCapabilityFingerprint:
                raise ValueError("typed launch policy and exact capability fingerprint are required together")
            assert_fingerprint_current(capability_fingerprint, executable)
            if capability_fingerprint.executable_sha256 != executable_sha:
                raise ValueError("capability fingerprint executable digest mismatch")
            launch_policy.validate()
            extra_args = render_launch_policy(launch_policy, capability_fingerprint)
            capability_sha = capability_fingerprint.fingerprint_sha256
            policy_mapping = launch_policy.as_mapping()
            if launch_policy.gpu_layers is not None:
                effective_gpu_layers = launch_policy.gpu_layers
            # The typed policy owns GPU-layer rendering when explicitly set.
            legacy_gpu_args: tuple[str, ...] = () if launch_policy.gpu_layers is not None else ("--n-gpu-layers", str(gpu_layers))
        else:
            legacy_gpu_args = ("--n-gpu-layers", str(gpu_layers))

        command = (
            str(executable), "--model", admission.model_path, "--host", "127.0.0.1",
            "--port", str(port), "--ctx-size", str(context_size), *legacy_gpu_args, *extra_args,
        )
        base = {
            "schema_version": "px.local-model-server-plan/1.1" if capability_sha else "px.local-model-server-plan/1.0",
            "plan_id": f"local-model-plan-{uuid4().hex}",
            "model": asdict(admission), "executable_path": str(executable),
            "executable_sha256": executable_sha, "host": "127.0.0.1", "port": port,
            "context_size": context_size, "gpu_layers": effective_gpu_layers, "command": list(command),
            "created_at": _now(),
            "capability_fingerprint_sha256": capability_sha,
            "launch_policy": policy_mapping,
        }
        return ServerPlan(**{**base, "command": command}, plan_sha256=_sha(base))

    def plan_router_pool(
        self,
        models: Mapping[str, ModelAdmission],
        executable_path: Path,
        preset_path: Path,
        *,
        port: int,
        models_max: int = 2,
    ) -> RouterPoolPlan:
        if type(models) is not dict or not 1 <= len(models) <= 128:
            raise ValueError("router pool requires a bounded nonempty admitted model mapping")
        if type(models_max) is not int or not 1 <= models_max <= min(64, len(models)):
            raise ValueError("router pool models_max must be between 1 and the admitted model count")
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ValueError("router pool port is invalid")
        executable = self._admitted_path(executable_path, self.runtime_roots)
        preset = self._admitted_path(preset_path, self.config_roots, ".ini")
        bound_models: list[dict[str, object]] = []
        for model_id in sorted(models):
            if type(model_id) is not str or not model_id.strip() or len(model_id.encode("utf-8")) > 256:
                raise ValueError("router model IDs must be bounded nonempty text")
            admission = models[model_id]
            if type(admission) is not ModelAdmission or not admission.compatible:
                raise ValueError("router pool models must be compatible typed admissions")
            if self._digest_file(Path(admission.model_path)) != admission.model_sha256:
                raise ValueError(f"admitted router model digest is stale: {model_id}")
            bound_models.append({"model_id": model_id, "admission": asdict(admission)})
        executable_sha = self._digest_file(executable)
        preset_sha = self._digest_file(preset)
        command = (
            str(executable), "--host", "127.0.0.1", "--port", str(port),
            "--models-preset", str(preset), "--models-max", str(models_max),
            "--no-models-autoload", "--metrics", "--slots", "--no-ui", "--log-jsonl",
        )
        base = {
            "schema_version": "px.local-model-router-pool-plan/1.0",
            "plan_id": f"local-model-router-plan-{uuid4().hex}",
            "models": bound_models,
            "executable_path": str(executable),
            "executable_sha256": executable_sha,
            "preset_path": str(preset),
            "preset_sha256": preset_sha,
            "host": "127.0.0.1",
            "port": port,
            "models_max": models_max,
            "command": list(command),
            "created_at": _now(),
        }
        return RouterPoolPlan(**{**base, "models": tuple(bound_models), "command": command}, plan_sha256=_sha(base))

    def plan_retrieval_model_services(
        self,
        embedding: ModelAdmission,
        executable_path: Path,
        *,
        embedding_model_id: str,
        embedding_revision: str,
        embedding_port: int,
        embedding_context_size: int,
        retrieval_policy_sha256: str,
        reranker: ModelAdmission | None = None,
        reranker_model_id: str | None = None,
        reranker_revision: str | None = None,
        reranker_port: int | None = None,
        reranker_context_size: int = 4096,
        gpu_layers: int = 0,
    ) -> RetrievalModelServicesPlan:
        """Plan dedicated retrieval-model subprocesses without starting them.

        Exact admitted GGUF digests are the model revisions.  The returned receipt
        binds the process plans to the retrieval policy but grants no start/load
        authority.
        """
        def bounded_id(value: object, name: str) -> str:
            if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > 256:
                raise ValueError(f"{name} must be bounded nonempty text")
            return value
        def digest(value: object, name: str) -> str:
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"{name} must be a lowercase SHA-256")
            return value
        embedding_model_id = bounded_id(embedding_model_id, "embedding_model_id")
        embedding_revision = digest(embedding_revision, "embedding_revision")
        policy_sha = digest(retrieval_policy_sha256, "retrieval_policy_sha256")
        if embedding_revision != embedding.model_sha256:
            raise ValueError("embedding revision must equal the admitted model digest")
        embedding_server = self.plan_server(embedding, executable_path, port=embedding_port, context_size=embedding_context_size, gpu_layers=gpu_layers)
        reranker_server = None
        if reranker is not None:
            if reranker_model_id is None or reranker_revision is None or reranker_port is None:
                raise ValueError("reranker identity, revision, and port are required together")
            reranker_model_id = bounded_id(reranker_model_id, "reranker_model_id")
            reranker_revision = digest(reranker_revision, "reranker_revision")
            if reranker_revision != reranker.model_sha256:
                raise ValueError("reranker revision must equal the admitted model digest")
            if reranker_port == embedding_port:
                raise ValueError("embedding and reranker services require distinct ports")
            reranker_server = self.plan_server(reranker, executable_path, port=reranker_port, context_size=reranker_context_size, gpu_layers=gpu_layers)
        elif any(value is not None for value in (reranker_model_id, reranker_revision, reranker_port)):
            raise ValueError("reranker fields cannot be supplied without an admitted reranker model")
        receipt_base = {
            "schema_version": "px.retrieval-model-services-plan/1.0",
            "embedding_model_id": embedding_model_id,
            "embedding_revision": embedding_revision,
            "embedding_plan_sha256": embedding_server.plan_sha256,
            "reranker_model_id": reranker_model_id,
            "reranker_revision": reranker_revision,
            "reranker_plan_sha256": reranker_server.plan_sha256 if reranker_server else None,
            "retrieval_policy_sha256": policy_sha,
            "authority": "plan_only_no_start_or_load_grant",
        }
        return RetrievalModelServicesPlan(
            "px.retrieval-model-services-plan/1.0", embedding_model_id, embedding_revision, embedding_server,
            reranker_model_id, reranker_revision, reranker_server, policy_sha, _sha(receipt_base),
        )

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

    def start(self, plan: ServerPlan | RouterPoolPlan, *, readiness_timeout_seconds: float = 30.0) -> dict[str, object]:
        if type(readiness_timeout_seconds) not in (int, float) or type(readiness_timeout_seconds) is bool or not 0 < float(readiness_timeout_seconds) <= 300:
            raise ValueError("readiness timeout must be in (0, 300]")
        if type(plan) not in (ServerPlan, RouterPoolPlan):
            raise ValueError("typed local-model server or router plan is required")
        plan_body = {key: value for key, value in asdict(plan).items() if key != "plan_sha256"}
        if _sha(plan_body) != plan.plan_sha256:
            raise ValueError("local-model server plan integrity failed")
        if isinstance(plan, ServerPlan):
            if self._digest_file(Path(plan.model["model_path"])) != plan.model["model_sha256"]:
                raise ValueError("model changed after planning")
        else:
            if self._digest_file(Path(plan.preset_path)) != plan.preset_sha256:
                raise ValueError("router preset changed after planning")
            for item in plan.models:
                admission = item["admission"]
                if type(admission) is not dict or self._digest_file(Path(str(admission["model_path"]))) != admission["model_sha256"]:
                    raise ValueError("router model changed after planning")
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
        state_events = {"started", "stopped", "start_failed", "recovered_absent"}
        matches = [
            event for event in self._load_events()
            if event["event_type"] in state_events and event["payload"].get("session_id") == session_id
        ]
        if not matches:
            raise KeyError(session_id)
        return matches[-1]

    def _started_event(self, session_id: str) -> dict[str, object]:
        matches = [
            event for event in self._load_events()
            if event["event_type"] == "started" and event["payload"].get("session_id") == session_id
        ]
        if not matches:
            raise KeyError(session_id)
        return matches[-1]

    def _router_plan_for_session(self, session_id: str) -> dict[str, object]:
        started = self._started_event(session_id)
        plan = started["payload"].get("plan")
        if type(plan) is not dict or plan.get("schema_version") != "px.local-model-router-pool-plan/1.0":
            raise ValueError("session is not backed by a governed router-pool plan")
        return plan

    def status(self, session_id: str) -> dict[str, object]:
        event = self._session_event(session_id)
        resource_id = str(event["payload"].get("resource_id", ""))
        record = self.manager.ledger.get(resource_id)
        state = "running" if record.active and event["event_type"] == "started" else str(event["event_type"])
        return {"session_id": session_id, "state": state, "resource_id": resource_id, "pid": record.pid, "process_identity": record.process_identity, "event_sha256": event["event_sha256"]}

    def _router_origin(self, session_id: str) -> str:
        current = self.status(session_id)
        if current["state"] != "running":
            raise RuntimeError("local model router session is not running")
        plan = self._router_plan_for_session(session_id)
        if plan.get("host") != "127.0.0.1" or type(plan.get("port")) is not int:
            raise ValueError("router plan loopback identity is invalid")
        return f"http://127.0.0.1:{plan['port']}"

    @staticmethod
    def _router_timeout(value: object, *, maximum: float = 300.0) -> float:
        if type(value) not in (int, float) or type(value) is bool:
            raise ValueError(f"router timeout must be a finite number in (0, {maximum:g}]")
        timeout = float(value)
        if not math.isfinite(timeout) or not 0 < timeout <= maximum:
            raise ValueError(f"router timeout must be a finite number in (0, {maximum:g}]")
        return timeout

    def router_model_states(self, session_id: str, *, timeout_seconds: float = 2.0) -> dict[str, str]:
        timeout = self._router_timeout(timeout_seconds, maximum=30.0)
        origin = self._router_origin(session_id)
        plan = self._router_plan_for_session(session_id)
        plan_rows = plan.get("models")
        if type(plan_rows) not in (list, tuple):
            raise ValueError("router plan model binding is invalid")
        allowed_ids = {row.get("model_id") for row in plan_rows if type(row) is dict and type(row.get("model_id")) is str}
        if len(allowed_ids) != len(plan_rows):
            raise ValueError("router plan model identity set is invalid")
        payload = self.router_request("GET", origin + "/models", None, timeout)
        if type(payload) is not dict:
            raise ValueError("local model router model list must be a JSON object")
        rows = payload.get("data")
        if type(rows) is not list or len(rows) > 256:
            raise ValueError("local model router returned an invalid model list")
        states: dict[str, str] = {}
        for row in rows:
            if type(row) is not dict:
                raise ValueError("local model router model entry must be an object")
            model_id = row.get("id")
            if type(model_id) is not str or not model_id.strip() or len(model_id.encode("utf-8")) > 256 or model_id in states:
                raise ValueError("local model router model identity is invalid or duplicated")
            if model_id not in allowed_ids:
                raise ValueError("local model router reported a model outside the admitted router plan")
            status = row.get("status")
            if type(status) is dict:
                state = status.get("value")
            else:
                state = status
            if type(state) is not str or not state.strip() or len(state.encode("utf-8")) > 64:
                state = "unknown"
            states[model_id] = state.strip().lower()
        return states

    def _assert_router_model(self, session_id: str, model_id: str) -> dict[str, object]:
        if type(model_id) is not str or not model_id.strip() or len(model_id.encode("utf-8")) > 256:
            raise ValueError("router model ID must be bounded nonempty text")
        plan = self._router_plan_for_session(session_id)
        rows = plan.get("models")
        if type(rows) not in (tuple, list):
            raise ValueError("router plan model binding is invalid")
        match = next((row for row in rows if type(row) is dict and row.get("model_id") == model_id), None)
        if match is None:
            raise KeyError(model_id)
        return match

    def _wait_router_model_state(
        self, session_id: str, model_id: str, *, desired: frozenset[str], timeout_seconds: float
    ) -> str:
        timeout = self._router_timeout(timeout_seconds, maximum=300.0)
        deadline = time.monotonic() + timeout
        last = "unknown"
        while time.monotonic() < deadline:
            last = self.router_model_states(session_id, timeout_seconds=min(2.0, max(0.05, deadline - time.monotonic()))).get(model_id, "unloaded")
            if last in desired:
                return last
            if last in {"failed", "error"}:
                break
            time.sleep(0.05)
        raise RuntimeError(f"router model {model_id} did not reach {sorted(desired)}; last={last}")

    def load_router_model(
        self, session_id: str, model_id: str, *, supplied_authority: bool, timeout_seconds: float = 60.0
    ) -> str:
        if supplied_authority is not True:
            raise PermissionError("explicit model-load authority is required")
        timeout = self._router_timeout(timeout_seconds, maximum=300.0)
        binding = self._assert_router_model(session_id, model_id)
        origin = self._router_origin(session_id)
        self.router_request("POST", origin + "/models/load", {"model": model_id}, min(10.0, timeout))
        state = self._wait_router_model_state(session_id, model_id, desired=frozenset({"loaded", "sleeping"}), timeout_seconds=timeout)
        admission = binding.get("admission")
        self._append("router_model_loaded", {
            "session_id": session_id, "resource_id": self.status(session_id)["resource_id"],
            "model_id": model_id, "model_sha256": admission.get("model_sha256") if type(admission) is dict else None,
            "router_state": state,
        })
        return state

    def unload_router_model(
        self, session_id: str, model_id: str, *, supplied_authority: bool, timeout_seconds: float = 60.0
    ) -> str:
        if supplied_authority is not True:
            raise PermissionError("explicit model-unload authority is required")
        timeout = self._router_timeout(timeout_seconds, maximum=300.0)
        self._assert_router_model(session_id, model_id)
        origin = self._router_origin(session_id)
        self.router_request("POST", origin + "/models/unload", {"model": model_id}, min(10.0, timeout))
        state = self._wait_router_model_state(session_id, model_id, desired=frozenset({"unloaded"}), timeout_seconds=timeout)
        self._append("router_model_unloaded", {
            "session_id": session_id, "resource_id": self.status(session_id)["resource_id"],
            "model_id": model_id, "router_state": state, "model_deleted": False,
        })
        return state

    def open_model_pool(
        self,
        session_id: str,
        profiles: Mapping[str, ModelRuntimeProfile],
    ) -> ModelPool:
        plan = self._router_plan_for_session(session_id)
        rows = plan.get("models")
        if type(rows) not in (tuple, list):
            raise ValueError("router plan model binding is invalid")
        if type(profiles) is not dict:
            raise ValueError("model pool profiles must be a mapping")
        specs: list[PoolModelSpec] = []
        for row in rows:
            if type(row) is not dict:
                raise ValueError("router plan model binding is invalid")
            model_id = row.get("model_id")
            admission = row.get("admission")
            if type(model_id) is not str or type(admission) is not dict:
                raise ValueError("router plan model binding is invalid")
            profile = profiles.get(model_id)
            if type(profile) is not ModelRuntimeProfile or profile.model_id != model_id:
                raise ValueError(f"missing or mismatched runtime profile for {model_id}")
            profile.validate()
            model_sha = admission.get("model_sha256")
            if type(model_sha) is not str:
                raise ValueError("router admission model digest is invalid")
            specs.append(PoolModelSpec(
                model_id=model_id, profile_id=profile.profile_id, model_sha256=model_sha,
                profile_sha256=profile.profile_sha256, residency=profile.residency,
                idle_evict_seconds=profile.idle_evict_seconds,
                exclusive_group="heavy-model" if profile.exclusive_heavy else None,
            ))
        resource_id = self.status(session_id)["resource_id"]

        def sink(event_type: str, payload: Mapping[str, object]) -> object:
            return self._append(event_type, {"session_id": session_id, "resource_id": resource_id, **dict(payload)})

        return ModelPool(
            tuple(specs),
            load_model=lambda model_id: self.load_router_model(session_id, model_id, supplied_authority=True),
            unload_model=lambda model_id: self.unload_router_model(session_id, model_id, supplied_authority=True),
            observe_models=lambda: self.router_model_states(session_id),
            event_sink=sink, max_loaded_models=int(plan["models_max"]),
        )


    def open_docker_model_runtime(self, interlock, *, policy=None, command_runner=None):
        """Create a subordinate Docker cold runtime sharing PX model custody.

        The returned object owns no route authority and cannot widen this
        runtime's model/config roots.  Import is lazy so Docker support remains
        an optional lane rather than a startup dependency.
        """
        from .docker_model_runtime import DockerModelRuntime
        return DockerModelRuntime(
            self.root, interlock=interlock, policy=policy, command_runner=command_runner,
        )

    def open_airllm_runtime(
        self,
        interlock,
        *,
        allowed_prepared_roots,
        allowed_runtime_roots=None,
        policy=None,
        readiness_probe=None,
    ):
        """Create the supervised AirLLM cold lane under this ResourceManager."""
        from .airllm_runtime import AirLlmRuntime
        roots = self.runtime_roots if allowed_runtime_roots is None else tuple(allowed_runtime_roots)
        return AirLlmRuntime(
            self.root, manager=self.manager, interlock=interlock,
            allowed_prepared_roots=tuple(allowed_prepared_roots), allowed_runtime_roots=roots,
            policy=policy, readiness_probe=readiness_probe,
        )

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
