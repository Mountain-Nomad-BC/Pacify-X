"""Supervised one-job-at-a-time AirLLM cold/offload runtime.

AirLLM is never imported into the PX broker.  An already-prepared model and a
user-managed worker executable/script are started under ResourceManager custody.
Model preparation/download is deliberately outside request execution.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import threading
import time
from typing import Callable, Iterable, Mapping, Sequence
from urllib.request import ProxyHandler, Request, build_opener
from uuid import uuid4

from .archive_io import reject_path_links
from .model_resource_interlock import (
    ExternalRuntimePolicy,
    ModelResourceInterlock,
    ModelResourceLease,
    ModelResourceNeed,
    load_external_runtime_policy,
)
from .resource_lifecycle import ResourceManager


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum or "\0" in value:
        raise ValueError(f"AirLLM {field} must be bounded nonempty text")
    return value.strip()


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    target = os.path.normcase(str(path))
    for root in roots:
        try:
            if os.path.commonpath((target, os.path.normcase(str(root)))) == os.path.normcase(str(root)):
                return True
        except ValueError:
            continue
    return False


@dataclass(frozen=True, slots=True)
class PreparedAirModel:
    schema_version: str
    model_id: str
    source_revision: str
    prepared_root: str
    prepared_set_sha256: str
    compression: str
    prefetching: bool
    disk_bytes: int
    manifest_path: str
    manifest_sha256: str


@dataclass(frozen=True, slots=True)
class AirLlmWorkerPlan:
    schema_version: str
    plan_id: str
    prepared_model: PreparedAirModel
    python_path: str
    python_sha256: str
    worker_script: str
    worker_sha256: str
    host: str
    port: int
    max_seq_len: int
    command: tuple[str, ...]
    policy_sha256: str
    plan_sha256: str

    def identity_payload(self) -> dict[str, object]:
        body = asdict(self)
        body.pop("plan_sha256")
        return body


class AirLlmRuntime:
    def __init__(
        self,
        root: Path,
        *,
        manager: ResourceManager,
        interlock: ModelResourceInterlock,
        allowed_prepared_roots: Iterable[Path],
        allowed_runtime_roots: Iterable[Path],
        policy: ExternalRuntimePolicy | None = None,
        readiness_probe: Callable[[str, float], bool] | None = None,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.manager = manager
        self.interlock = interlock
        self.policy = policy or load_external_runtime_policy(self.root)
        self.policy.validate()
        self.prepared_roots = tuple(path.resolve(strict=True) for path in allowed_prepared_roots)
        self.runtime_roots = tuple(path.resolve(strict=True) for path in allowed_runtime_roots)
        if not self.prepared_roots or not self.runtime_roots:
            raise ValueError("AirLLM requires explicit prepared-model and runtime roots")
        self.readiness_probe = readiness_probe or self._http_ready
        self._mutex = threading.RLock()
        self._active: dict[str, object] | None = None

    @staticmethod
    def _http_ready(origin: str, timeout: float) -> bool:
        opener = build_opener(ProxyHandler({}))
        try:
            with opener.open(Request(origin + "/health", method="GET"), timeout=timeout) as response:
                return 200 <= int(response.status) < 300
        except OSError:
            return False

    def _admitted_path(self, value: Path, roots: Sequence[Path]) -> Path:
        path = value.resolve(strict=True)
        if not _inside(path, roots):
            raise ValueError("AirLLM path is outside its admitted roots")
        reject_path_links(path)
        return path

    def load_prepared_model(self, manifest_path: Path, *, expected_manifest_sha256: str) -> PreparedAirModel:
        path = self._admitted_path(manifest_path, self.prepared_roots)
        if len(expected_manifest_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_manifest_sha256):
            raise ValueError("AirLLM expected manifest digest is invalid")
        raw = path.read_bytes()
        if len(raw) > 262_144 or hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
            raise ValueError("AirLLM prepared manifest digest is stale")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("AirLLM prepared manifest is invalid JSON") from error
        required = {"schema_version", "model_id", "source_revision", "prepared_root", "prepared_set_sha256", "compression", "prefetching", "disk_bytes"}
        if type(payload) is not dict or set(payload) != required or payload["schema_version"] != "px.airllm-prepared-model/1.0":
            raise ValueError("unsupported AirLLM prepared manifest contract")
        prepared_root = self._admitted_path(Path(payload["prepared_root"]), self.prepared_roots)
        model_id = _text(payload["model_id"], "model_id", maximum=256)
        source_revision = _text(payload["source_revision"], "source_revision", maximum=256)
        prepared_set_sha = _text(payload["prepared_set_sha256"], "prepared_set_sha256", maximum=64)
        if len(prepared_set_sha) != 64 or any(c not in "0123456789abcdef" for c in prepared_set_sha):
            raise ValueError("AirLLM prepared-set digest is invalid")
        compression = _text(payload["compression"], "compression", maximum=16)
        if compression not in self.policy.airllm_approved_compression:
            raise ValueError("AirLLM prepared compression mode is not approved")
        if type(payload["prefetching"]) is not bool:
            raise ValueError("AirLLM prefetch flag must be boolean")
        if compression != "none" and payload["prefetching"] is True:
            raise ValueError("AirLLM compression and prefetching cannot share one runtime identity")
        disk_bytes = payload["disk_bytes"]
        if type(disk_bytes) is not int or isinstance(disk_bytes, bool) or not 0 <= disk_bytes <= 2**63 - 1:
            raise ValueError("AirLLM prepared disk bytes are invalid")
        return PreparedAirModel(
            schema_version=payload["schema_version"], model_id=model_id, source_revision=source_revision,
            prepared_root=str(prepared_root), prepared_set_sha256=prepared_set_sha, compression=compression,
            prefetching=payload["prefetching"], disk_bytes=disk_bytes,
            manifest_path=str(path), manifest_sha256=expected_manifest_sha256,
        )

    def plan_worker(
        self,
        prepared: PreparedAirModel,
        *,
        python_path: Path,
        worker_script: Path,
        port: int,
        max_seq_len: int,
    ) -> AirLlmWorkerPlan:
        python = self._admitted_path(python_path, self.runtime_roots)
        worker = self._admitted_path(worker_script, self.runtime_roots)
        if not 1024 <= port <= 65535 or type(port) is not int:
            raise ValueError("AirLLM worker port is invalid")
        if type(max_seq_len) is not int or not 128 <= max_seq_len <= 1_048_576:
            raise ValueError("AirLLM max sequence length is invalid")
        command = [
            str(python), str(worker), "--manifest", prepared.manifest_path,
            "--manifest-sha256", prepared.manifest_sha256,
            "--host", "127.0.0.1", "--port", str(port), "--max-seq-len", str(max_seq_len),
            "--compression", prepared.compression,
            "--prefetching", "true" if prepared.prefetching else "false",
        ]
        plan_id = f"airllm-plan-{uuid4().hex}"
        python_sha256 = _file_sha(python)
        worker_sha256 = _file_sha(worker)
        identity = {
            "schema_version": "px.airllm-worker-plan/1.0",
            "plan_id": plan_id,
            "prepared_model": asdict(prepared),
            "python_path": str(python), "python_sha256": python_sha256,
            "worker_script": str(worker), "worker_sha256": worker_sha256,
            "host": "127.0.0.1", "port": port, "max_seq_len": max_seq_len,
            "command": list(command), "policy_sha256": self.policy.policy_sha256,
        }
        return AirLlmWorkerPlan(
            schema_version="px.airllm-worker-plan/1.0", plan_id=plan_id, prepared_model=prepared,
            python_path=str(python), python_sha256=python_sha256, worker_script=str(worker),
            worker_sha256=worker_sha256, host="127.0.0.1", port=port, max_seq_len=max_seq_len,
            command=tuple(command), policy_sha256=self.policy.policy_sha256, plan_sha256=_sha(identity),
        )

    def start(
        self,
        plan: AirLlmWorkerPlan,
        need: ModelResourceNeed,
        *,
        supplied_authority: bool,
        readiness_timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        if self.policy.globally_enabled is not True or self.policy.airllm_enabled is not True:
            raise PermissionError("AirLLM cold runtime is disabled by policy")
        if supplied_authority is not True:
            raise PermissionError("AirLLM worker start requires explicit effect authority")
        if need.runtime_id != "airllm":
            raise ValueError("AirLLM runtime requires an airllm resource need")
        if plan.policy_sha256 != self.policy.policy_sha256 or plan.plan_sha256 != _sha(plan.identity_payload()):
            raise ValueError("AirLLM worker plan identity is stale")
        if _file_sha(Path(plan.python_path)) != plan.python_sha256 or _file_sha(Path(plan.worker_script)) != plan.worker_sha256:
            raise ValueError("AirLLM worker executable/script identity is stale")
        manifest = Path(plan.prepared_model.manifest_path)
        if not manifest.is_file() or _file_sha(manifest) != plan.prepared_model.manifest_sha256:
            raise ValueError("AirLLM prepared manifest identity changed after planning")
        prepared_root = Path(plan.prepared_model.prepared_root)
        if not prepared_root.is_dir():
            raise ValueError("AirLLM prepared model root is no longer available")
        timeout = self.policy.airllm_start_timeout_seconds if readiness_timeout_seconds is None else float(readiness_timeout_seconds)
        if not 0.1 <= timeout <= self.policy.airllm_start_timeout_seconds:
            raise ValueError("AirLLM readiness timeout exceeds policy")
        with self._mutex:
            if self._active is not None:
                raise RuntimeError("AirLLM cold lane permits one active worker")
            lease = self.interlock.acquire(f"airllm:{plan.prepared_model.model_id}", need, timeout_seconds=0.0)
            record = process = None
            try:
                record, process = self.manager.spawn_owned_process(
                    plan.command, cwd=Path(plan.worker_script).parent,
                    project_id="px-local-model-runtime", run_id=plan.plan_id, lane_id="airllm-cold",
                    creator="runtime.airllm_runtime", ownership="supervised" if os.name == "nt" else "direct",
                )
                deadline = time.monotonic() + timeout
                origin = f"http://127.0.0.1:{plan.port}"
                ready = False
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    if self.readiness_probe(origin, min(1.0, max(0.05, deadline - time.monotonic()))):
                        ready = True
                        break
                    time.sleep(0.05)
                if not ready:
                    raise RuntimeError("AirLLM worker did not become ready within its bounded startup")
                session_id = f"airllm-session-{uuid4().hex}"
                self._active = {"session_id": session_id, "plan": plan, "lease": lease, "resource_id": record.resource_id, "pid": process.pid}
            except BaseException:
                cleanup_proven = False
                if record is not None:
                    receipt = self.manager.terminate_owned_process(record.resource_id, graceful_timeout_seconds=self.policy.airllm_cancel_timeout_seconds)
                    cleanup_proven = receipt.resources_reclaimed == 1 and not receipt.errors
                if cleanup_proven:
                    self.interlock.release(lease.lease_id, cleanup_proven=True)
                raise
            body = {
                "schema_version": "px.airllm-runtime-receipt/1.0", "operation": "start",
                "session_id": session_id, "plan_sha256": plan.plan_sha256,
                "model_id": plan.prepared_model.model_id, "prepared_set_sha256": plan.prepared_model.prepared_set_sha256,
                "manifest_sha256": plan.prepared_model.manifest_sha256,
                "resource_id": record.resource_id, "pid": process.pid, "resource_lease_id": lease.lease_id,
                "origin": f"http://127.0.0.1:{plan.port}", "routing_authority": False, "payload_retained": False,
            }
            return {**body, "receipt_sha256": _sha(body)}

    def stop(self, session_id: str, *, supplied_authority: bool) -> dict[str, object]:
        if supplied_authority is not True:
            raise PermissionError("AirLLM worker stop requires explicit effect authority")
        with self._mutex:
            active = self._active
            if active is None or active["session_id"] != session_id:
                raise KeyError("AirLLM session is not active")
            receipt = self.manager.terminate_owned_process(
                active["resource_id"], graceful_timeout_seconds=self.policy.airllm_cancel_timeout_seconds,
            )
            if receipt.resources_reclaimed != 1 or receipt.errors:
                raise RuntimeError("AirLLM worker cleanup is not proven; resource lease retained")
            lease: ModelResourceLease = active["lease"]  # type: ignore[assignment]
            self.interlock.release(lease.lease_id, cleanup_proven=True)
            self._active = None
            body = {
                "schema_version": "px.airllm-runtime-receipt/1.0", "operation": "stop",
                "session_id": session_id, "plan_sha256": active["plan"].plan_sha256,
                "resource_id": active["resource_id"], "resource_lease_id": lease.lease_id,
                "cleanup_receipt_id": receipt.cleanup_id, "routing_authority": False, "payload_retained": False,
            }
            return {**body, "receipt_sha256": _sha(body)}

    def active_session(self) -> Mapping[str, object] | None:
        with self._mutex:
            if self._active is None:
                return None
            return {k: v for k, v in self._active.items() if k not in {"plan", "lease"}}
