"""Governed Docker Model Runner cold-lane adapter.

Docker Model Runner supplies model caching/loading and a loopback API.  PX remains
responsible for routing, resource admission, lifecycle intent, and provider
invocation receipts.  This module never uses Docker Model Gateway routing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import re
import subprocess
import threading
from pathlib import Path
from typing import Callable, Sequence

from .model_resource_interlock import (
    ExternalRuntimePolicy,
    ModelResourceInterlock,
    ModelResourceLease,
    ModelResourceNeed,
    load_external_runtime_policy,
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OCI = re.compile(r"^sha256:([0-9a-f]{64})$")
_MAX_OUTPUT = 1_048_576


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _text(value: object, field: str, *, maximum: int = 512) -> str:
    if type(value) is not str or not value.strip() or len(value.encode("utf-8")) > maximum or "\0" in value:
        raise ValueError(f"Docker runtime {field} must be bounded nonempty text")
    return value.strip()


def _inspect_manifest_identity(payload: dict[str, object], *, model_ref: str, expected_digest: str) -> str:
    # Docker's native Model API exposes the raw-manifest SHA256 as `id`.
    # Config, annotations and layer strings cannot supply that identity.
    required = {"id", "created", "config"}
    if not required <= payload.keys() or not payload.keys() <= required | {"tags"}:
        raise ValueError("Docker model inspect schema is unsupported or ambiguous")
    identity = payload["id"]
    if type(identity) is not str or _OCI.fullmatch(identity) is None or identity != expected_digest:
        raise ValueError("Docker model inspect does not prove the planned OCI digest")
    if type(payload["created"]) is not int or not 0 <= payload["created"] <= 2**63 - 1:
        raise ValueError("Docker model inspect creation timestamp is invalid")
    if type(payload["config"]) is not dict:
        raise ValueError("Docker model inspect configuration is invalid")
    tags = payload.get("tags", [])
    if type(tags) is not list or len(tags) > 128:
        raise ValueError("Docker model inspect tags are invalid")
    for tag in tags:
        if type(tag) is not str or tag != _text(tag, "inspect tag") or any(c.isspace() for c in tag):
            raise ValueError("Docker model inspect tag is invalid")
    if len(set(tags)) != len(tags):
        raise ValueError("Docker model inspect contains duplicate tags")
    immutable_reference = model_ref == expected_digest or model_ref.endswith("@" + expected_digest)
    if not immutable_reference and model_ref not in tags:
        raise ValueError("Docker model inspect does not bind the exact planned model reference")
    return identity


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes

    def validate(self) -> None:
        if type(self.returncode) is not int:
            raise ValueError("Docker command return code is invalid")
        if type(self.stdout) is not bytes or type(self.stderr) is not bytes:
            raise ValueError("Docker command output must be bytes")
        if len(self.stdout) > _MAX_OUTPUT or len(self.stderr) > _MAX_OUTPUT:
            raise ValueError("Docker command output exceeds its byte bound")


@dataclass(frozen=True, slots=True)
class DockerModelPlan:
    schema_version: str
    model_id: str
    model_ref: str
    oci_digest: str
    engine: str
    base_url: str
    policy_sha256: str
    plan_sha256: str

    def identity_payload(self) -> dict[str, object]:
        body = asdict(self)
        body.pop("plan_sha256")
        return body

    def validate(self, policy: ExternalRuntimePolicy) -> None:
        if self.schema_version != "px.docker-model-plan/1.0":
            raise ValueError("unsupported Docker model plan")
        _text(self.model_id, "model_id", maximum=256)
        model_ref = _text(self.model_ref, "model_ref", maximum=512)
        if any(char.isspace() for char in model_ref) or model_ref.startswith("-"):
            raise ValueError("Docker model reference may not contain whitespace or option-like prefixes")
        if _OCI.fullmatch(self.oci_digest) is None:
            raise ValueError("Docker model OCI digest must be exact sha256 identity")
        if "@" in model_ref:
            name, reference_digest = model_ref.rsplit("@", 1)
            if not name or "@" in name or reference_digest != self.oci_digest:
                raise ValueError("Docker model reference digest differs from the planned OCI digest")
        if self.engine not in policy.docker_approved_engines:
            raise ValueError("Docker model engine is not approved")
        if self.base_url != policy.docker_loopback_origin:
            raise ValueError("Docker model endpoint differs from governed loopback policy")
        if self.policy_sha256 != policy.policy_sha256:
            raise ValueError("Docker model plan policy digest is stale")
        if self.plan_sha256 != _sha(self.identity_payload()):
            raise ValueError("Docker model plan digest is invalid")


class DockerModelRuntime:
    def __init__(
        self,
        root: Path,
        *,
        interlock: ModelResourceInterlock,
        policy: ExternalRuntimePolicy | None = None,
        command_runner: Callable[[Sequence[str], float], CommandResult] | None = None,
    ) -> None:
        self.root = root.resolve(strict=True)
        self.policy = policy or load_external_runtime_policy(self.root)
        self.policy.validate()
        self.interlock = interlock
        self._run_command = command_runner or self._default_runner
        self._leases: dict[str, ModelResourceLease] = {}
        self._state_lock = threading.RLock()
        self._pending: set[str] = set()

    @staticmethod
    def _default_runner(argv: Sequence[str], timeout_seconds: float) -> CommandResult:
        if not isinstance(argv, (tuple, list)) or not argv or any(type(x) is not str or not x or "\0" in x for x in argv):
            raise ValueError("Docker command argv is invalid")
        try:
            completed = subprocess.run(
                list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                shell=False, check=False, timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("Docker model command exceeded its timeout") from error
        result = CommandResult(completed.returncode, completed.stdout[: _MAX_OUTPUT + 1], completed.stderr[: _MAX_OUTPUT + 1])
        result.validate()
        return result

    def _command(self, argv: Sequence[str], timeout_seconds: float) -> CommandResult:
        result = self._run_command(tuple(argv), float(timeout_seconds))
        if type(result) is not CommandResult:
            raise TypeError("Docker command runner must return CommandResult")
        result.validate()
        return result

    def plan(self, *, model_id: str, model_ref: str, oci_digest: str, engine: str = "llama.cpp") -> DockerModelPlan:
        body = {
            "schema_version": "px.docker-model-plan/1.0",
            "model_id": _text(model_id, "model_id", maximum=256),
            "model_ref": _text(model_ref, "model_ref", maximum=512),
            "oci_digest": _text(oci_digest, "oci_digest", maximum=71),
            "engine": _text(engine, "engine", maximum=64),
            "base_url": self.policy.docker_loopback_origin,
            "policy_sha256": self.policy.policy_sha256,
        }
        plan = DockerModelPlan(**body, plan_sha256=_sha(body))
        plan.validate(self.policy)
        return plan

    def verify_cached(self, plan: DockerModelPlan) -> dict[str, object]:
        plan.validate(self.policy)
        result = self._command(("docker", "model", "inspect", plan.model_ref), 60.0)
        if result.returncode != 0:
            raise FileNotFoundError("Docker model is not locally cached")
        from .json_io import decode_json_object
        try:
            payload = decode_json_object(result.stdout, max_bytes=_MAX_OUTPUT, max_nodes=32768)
        except (UnicodeDecodeError, ValueError) as error:
            raise ValueError("Docker model inspect returned invalid JSON") from error
        _inspect_manifest_identity(payload, model_ref=plan.model_ref, expected_digest=plan.oci_digest)
        body = {
            "schema_version": "px.docker-model-cache-receipt/1.0",
            "model_id": plan.model_id,
            "model_ref": plan.model_ref,
            "oci_digest": plan.oci_digest,
            "plan_sha256": plan.plan_sha256,
            "inspect_sha256": hashlib.sha256(result.stdout).hexdigest(),
        }
        return {**body, "receipt_sha256": _sha(body)}

    def prewarm(
        self,
        plan: DockerModelPlan,
        need: ModelResourceNeed,
        *,
        supplied_authority: bool,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        plan.validate(self.policy)
        if self.policy.globally_enabled is not True or self.policy.docker_enabled is not True:
            raise PermissionError("Docker cold runtime is disabled by policy")
        if supplied_authority is not True:
            raise PermissionError("Docker model load requires explicit effect authority")
        timeout = self.policy.docker_start_timeout_seconds if timeout_seconds is None else timeout_seconds
        if type(timeout) not in (int, float) or type(timeout) is bool or not 0.1 <= float(timeout) <= self.policy.docker_start_timeout_seconds:
            raise ValueError("Docker prewarm timeout exceeds policy")
        timeout = float(timeout)
        need.validate()
        if need.runtime_id != "docker_model_runner":
            raise ValueError("Docker runtime requires a docker_model_runner resource need")
        with self._state_lock:
            if plan.plan_sha256 in self._leases or plan.plan_sha256 in self._pending:
                raise ValueError("Docker model plan is already holding a lease or has an operation in progress")
            self._pending.add(plan.plan_sha256)
        try:
            return self._prewarm_reserved(plan, need, timeout)
        finally:
            with self._state_lock:
                self._pending.discard(plan.plan_sha256)

    def _prewarm_reserved(self, plan: DockerModelPlan, need: ModelResourceNeed, timeout: float) -> dict[str, object]:
        cache_receipt = self.verify_cached(plan)
        lease = self.interlock.acquire(f"docker:{plan.model_id}", need, timeout_seconds=0.0)
        run_invoked = False
        try:
            with self._state_lock:
                self._leases[plan.plan_sha256] = lease
            run_invoked = True
            result = self._command(("docker", "model", "run", "--detach", plan.model_ref), timeout)
            if result.returncode != 0:
                raise RuntimeError("Docker model prewarm command failed")
        except BaseException:
            cleanup_proven = not run_invoked
            if run_invoked:
                cleanup = self._command(("docker", "model", "unload", plan.model_ref), self.policy.docker_unload_timeout_seconds)
                cleanup_proven = cleanup.returncode == 0
            if cleanup_proven:
                with self._state_lock:
                    self.interlock.release(lease.lease_id, cleanup_proven=True)
                    self._leases.pop(plan.plan_sha256, None)
            raise
        body = {
            "schema_version": "px.docker-model-runtime-receipt/1.0",
            "operation": "prewarm",
            "model_id": plan.model_id,
            "model_ref": plan.model_ref,
            "oci_digest": plan.oci_digest,
            "plan_sha256": plan.plan_sha256,
            "cache_receipt_sha256": cache_receipt["receipt_sha256"],
            "resource_lease_id": lease.lease_id,
            "resource_need_sha256": lease.need_sha256,
            "provider_origin": plan.base_url,
            "routing_authority": False,
            "payload_retained": False,
        }
        return {**body, "receipt_sha256": _sha(body)}

    def unload(self, plan: DockerModelPlan, *, supplied_authority: bool) -> dict[str, object]:
        plan.validate(self.policy)
        if supplied_authority is not True:
            raise PermissionError("Docker model unload requires explicit effect authority")
        with self._state_lock:
            if plan.plan_sha256 in self._pending:
                raise ValueError("Docker model plan has an operation in progress")
            if plan.plan_sha256 not in self._leases:
                raise KeyError("Docker model plan does not hold a resource lease")
            self._pending.add(plan.plan_sha256)
        try:
            return self._unload_reserved(plan)
        finally:
            with self._state_lock:
                self._pending.discard(plan.plan_sha256)

    def _unload_reserved(self, plan: DockerModelPlan) -> dict[str, object]:
        lease = self._leases.get(plan.plan_sha256)
        if lease is None:
            raise KeyError("Docker model plan does not hold a resource lease")
        result = self._command(("docker", "model", "unload", plan.model_ref), self.policy.docker_unload_timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError("Docker model unload command failed; resource lease retained")
        released = self.interlock.release(lease.lease_id, cleanup_proven=True)
        self._leases.pop(plan.plan_sha256, None)
        body = {
            "schema_version": "px.docker-model-runtime-receipt/1.0",
            "operation": "unload",
            "model_id": plan.model_id,
            "model_ref": plan.model_ref,
            "oci_digest": plan.oci_digest,
            "plan_sha256": plan.plan_sha256,
            "resource_lease_id": released.lease_id,
            "routing_authority": False,
            "payload_retained": False,
        }
        return {**body, "receipt_sha256": _sha(body)}

    def pull_for_operator_preparation(self, plan: DockerModelPlan, *, supplied_authority: bool) -> dict[str, object]:
        """Explicit operator preparation only; normal requests never call this method."""
        plan.validate(self.policy)
        if supplied_authority is not True:
            raise PermissionError("Docker model pull requires explicit preparation authority")
        result = self._command(("docker", "model", "pull", plan.model_ref), self.policy.docker_pull_timeout_seconds)
        if result.returncode != 0:
            raise RuntimeError("Docker model pull failed")
        body = {
            "schema_version": "px.docker-model-preparation-receipt/1.0",
            "operation": "pull",
            "model_ref": plan.model_ref,
            "planned_oci_digest": plan.oci_digest,
            "plan_sha256": plan.plan_sha256,
            "requires_post_pull_identity_verification": True,
            "normal_request_path": False,
        }
        return {**body, "receipt_sha256": _sha(body)}
