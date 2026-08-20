"""Persistent bounded admission and state-bus owner for expensive Python work.

The service has no timer, daemon, or background thread. Stable state is quiet:
work happens only for an explicit request, a changed input fingerprint, or an
expired informational cache. Cross-process lock directories provide bounded
single-flight and pool admission without stealing Codex host authority.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Callable, Mapping, Sequence, TypeVar
from uuid import uuid4


T = TypeVar("T")
SCHEMA = "px.runtime-work-plane/1.0"
POOL_LIMITS = {"interactive": 2, "light": 2, "heavy": 1, "validation": 1}
PRODUCER_CATALOG = (
    {"id": "dashboard.snapshot", "class": "dynamic-read", "admission": "legacy-direct"},
    {"id": "dashboard.hardware", "class": "sensor", "admission": "runtime-work-plane"},
    {"id": "dashboard.host-startup", "class": "host-log-sensor", "admission": "runtime-work-plane"},
    {"id": "execution-placement", "class": "decision", "admission": "runtime-work-plane"},
    {"id": "project-map.build", "class": "filesystem-heavy", "admission": "runtime-work-plane"},
    {"id": "test-index.build", "class": "filesystem-heavy", "admission": "runtime-work-plane"},
    {"id": "test-group.run", "class": "validation", "admission": "bounded-test-owner"},
    {"id": "hardware.cli", "class": "sensor", "admission": "runtime-work-plane"},
    {"id": "workspace.discovery", "class": "filesystem-heavy", "admission": "runtime-work-plane"},
)


class WorkAdmissionTimeout(RuntimeError):
    pass


def content_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    prepared = path.with_name(f".{path.name}.{uuid4().hex}.prepared")
    prepared.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(prepared, path)


class RuntimeWorkPlane:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.plane = self.root / ".engineering-bootstrap" / "runtime-core"
        self.locks = self.plane / "locks"
        self.pools = self.plane / "pools"
        self.cache = self.plane / "cache"
        self.operations = self.plane / "operations"
        self.state_path = self.plane / "state.json"

    def _empty_state(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA,
            "bus_revision": 0,
            "domain_revisions": {},
            "active": {},
            "counters": {
                "starts": 0,
                "joins": 0,
                "waits": 0,
                "failures": 0,
                "duplicate_executions_avoided": 0,
            },
            "last_delta": None,
            "operations": [],
        }

    def _read_state(self) -> dict[str, Any]:
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            return state if state.get("schema_version") == SCHEMA else self._empty_state()
        except (OSError, json.JSONDecodeError, AttributeError):
            return self._empty_state()

    @staticmethod
    def _read_cache(path: Path) -> dict[str, Any] | None:
        """Reject malformed or incomplete cache entries and let work rebuild them."""
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeError):
            return None
        if not isinstance(cached, dict) or "result" not in cached:
            return None
        try:
            float(cached.get("created_epoch", 0))
        except (TypeError, ValueError):
            return None
        return cached

    def _acquire_directory(self, path: Path, timeout_seconds: float) -> float:
        started = time.monotonic()
        path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            if self._claim_directory(path):
                return time.monotonic() - started
            self._reconcile_orphan(path)
            if time.monotonic() - started >= timeout_seconds:
                raise WorkAdmissionTimeout(f"bounded admission timed out: {path.name}")
            time.sleep(0.025)

    def _claim_directory(self, path: Path) -> bool:
        try:
            path.mkdir()
            _atomic_json(
                path / "owner.json",
                {"pid": os.getpid(), "created_epoch": time.time(), "created_at": _now()},
            )
            return True
        except FileExistsError:
            return False

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
        if pid == os.getpid():
            return True
        if os.name == "nt":
            try:
                import ctypes

                process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
                if not process:
                    return False
                exit_code = ctypes.c_ulong()
                alive = bool(
                    ctypes.windll.kernel32.GetExitCodeProcess(
                        process, ctypes.byref(exit_code)
                    )
                    and exit_code.value == 259
                )
                ctypes.windll.kernel32.CloseHandle(process)
                return alive
            except (AttributeError, OSError):
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _reconcile_orphan(self, path: Path) -> bool:
        try:
            owner = json.loads((path / "owner.json").read_text(encoding="utf-8"))
            pid = int(owner.get("pid", 0))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return False
        if self._pid_alive(pid):
            return False
        custody = self.plane / "orphaned-locks"
        custody.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(path, custody / f"{path.name}-{uuid4().hex}")
            return True
        except OSError:
            return False

    @staticmethod
    def _release_directory(path: Path) -> None:
        owner = path / "owner.json"
        if owner.is_file():
            for _ in range(10):
                try:
                    owner.unlink()
                    break
                except PermissionError:
                    time.sleep(0.05)
            else:
                raise
        for _ in range(12):
            try:
                path.rmdir()
                return
            except PermissionError:
                time.sleep(0.05)
            except OSError:
                if not path.is_dir():
                    return
                # Keep retrying only when another process briefly blocks release.
        raise RuntimeError(f"unable to release directory lock: {path}")

    def _update_state(self, mutate: Callable[[dict[str, Any]], None]) -> None:
        lock = self.locks / "state"
        self._acquire_directory(lock, 2.0)
        try:
            state = self._read_state()
            mutate(state)
            _atomic_json(self.state_path, state)
        finally:
            self._release_directory(lock)

    def _pool_token(self, lane: str, timeout_seconds: float) -> tuple[Path, float]:
        if lane not in POOL_LIMITS:
            raise ValueError(f"unknown runtime work lane: {lane}")
        started = time.monotonic()
        contended = False
        directory = self.pools / lane
        directory.mkdir(parents=True, exist_ok=True)
        while True:
            for index in range(POOL_LIMITS[lane]):
                token = directory / str(index)
                if self._claim_directory(token):
                    return token, time.monotonic() - started if contended else 0.0
                self._reconcile_orphan(token)
            contended = True
            if time.monotonic() - started >= timeout_seconds:
                raise WorkAdmissionTimeout(f"{lane} pool is saturated")
            time.sleep(0.025)

    def execute(
        self,
        operation: str,
        producer: Callable[[], T],
        *,
        reason: str,
        input_fingerprint: object,
        domains: Sequence[str],
        lane: str = "light",
        cache_seconds: float = 0.0,
        timeout_seconds: float = 10.0,
        authoritative: bool = False,
    ) -> dict[str, Any]:
        if not operation.strip() or not reason.strip() or not domains:
            raise ValueError("operation, reason, and affected domains are required")
        if cache_seconds < 0 or timeout_seconds <= 0:
            raise ValueError("cache and timeout bounds are invalid")
        input_sha = content_hash(input_fingerprint)
        key = hashlib.sha256(operation.encode("utf-8")).hexdigest()[:24]
        cache_path = self.cache / f"{key}.json"
        if cache_seconds and not authoritative and cache_path.is_file():
            cached = self._read_cache(cache_path)
        else:
            cached = None
        if cached is not None:
            age = time.time() - float(cached.get("created_epoch", 0))
            if cached.get("input_sha256") == input_sha and 0 <= age < cache_seconds:
                return {
                    "result": cached["result"],
                    "admission": {
                        "decision": "cache_hit",
                        "operation": operation,
                        "reason": reason,
                        "input_sha256": input_sha,
                        "cache_age_seconds": round(age, 6),
                        "authority": "informational-cache-only",
                    },
                }

        operation_lock = self.locks / f"operation-{key}"
        acquired = False
        wait_started = time.monotonic()
        join_started_epoch = time.time()
        while not acquired:
            try:
                operation_lock.parent.mkdir(parents=True, exist_ok=True)
                acquired = self._claim_directory(operation_lock)
            except OSError:
                acquired = False
            if not acquired:
                self._reconcile_orphan(operation_lock)
                if cache_path.is_file():
                    cached = self._read_cache(cache_path)
                    if cached is not None and (
                        cached.get("input_sha256") == input_sha
                        and float(cached.get("created_epoch", 0)) >= join_started_epoch
                    ):
                        waited = time.monotonic() - wait_started
                        self._record_join(operation, reason, waited)
                        return {
                            "result": cached["result"],
                            "admission": {
                                "decision": "joined",
                                "operation": operation,
                                "reason": reason,
                                "input_sha256": input_sha,
                                "wait_seconds": round(waited, 6),
                            },
                        }
                if time.monotonic() - wait_started >= timeout_seconds:
                    raise WorkAdmissionTimeout(
                        f"single-flight wait timed out for {operation}"
                    )
                time.sleep(0.025)

        token: Path | None = None
        operation_id = f"{key}-{uuid4().hex}"
        started = time.perf_counter()
        try:
            token, pool_wait = self._pool_token(lane, timeout_seconds)
            self._record_start(
                operation_id,
                operation,
                reason,
                lane,
                input_sha,
                domains,
                pool_wait,
                authoritative,
            )
            result = producer()
            payload = {
                "schema_version": "px.runtime-work-result/1.0",
                "operation": operation,
                "operation_id": operation_id,
                "input_sha256": input_sha,
                "created_epoch": time.time(),
                "created_at": _now(),
                "result": result,
                "result_sha256": content_hash(result),
            }
            _atomic_json(cache_path, payload)
            duration = time.perf_counter() - started
            self._record_finish(
                operation_id, operation, reason, domains, duration, payload["result_sha256"]
            )
            return {
                "result": result,
                "admission": {
                    "decision": "ran",
                    "operation": operation,
                    "operation_id": operation_id,
                    "reason": reason,
                    "input_sha256": input_sha,
                    "duration_seconds": round(duration, 6),
                    "pool_wait_seconds": round(pool_wait, 6),
                    "lane": lane,
                    "authoritative": authoritative,
                },
            }
        except Exception as error:
            self._record_failure(operation_id, operation, reason, error)
            raise
        finally:
            if token is not None and token.is_dir():
                self._release_directory(token)
            if operation_lock.is_dir():
                self._release_directory(operation_lock)

    def _record_join(self, operation: str, reason: str, waited: float) -> None:
        def mutate(state: dict[str, Any]) -> None:
            counters = state["counters"]
            counters["joins"] += 1
            counters["waits"] += 1
            counters["duplicate_executions_avoided"] += 1
            state["operations"] = (
                state["operations"]
                + [{"operation": operation, "outcome": "joined", "reason": reason, "wait_seconds": round(waited, 6), "at": _now()}]
            )[-50:]

        self._update_state(mutate)

    def _record_start(
        self,
        operation_id: str,
        operation: str,
        reason: str,
        lane: str,
        input_sha: str,
        domains: Sequence[str],
        waited: float,
        authoritative: bool,
    ) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["active"] = {
                key: value
                for key, value in state["active"].items()
                if self._pid_alive(int(value.get("pid", 0)))
            }
            state["counters"]["starts"] += 1
            if waited >= 0.001:
                state["counters"]["waits"] += 1
            state["active"][operation_id] = {
                "operation": operation,
                "reason": reason,
                "lane": lane,
                "input_sha256": input_sha,
                "domains": sorted(set(domains)),
                "started_at": _now(),
                "authoritative": authoritative,
                "pid": os.getpid(),
            }

        self._update_state(mutate)

    def _record_finish(
        self,
        operation_id: str,
        operation: str,
        reason: str,
        domains: Sequence[str],
        duration: float,
        result_sha: str,
    ) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["active"].pop(operation_id, None)
            state["bus_revision"] += 1
            revisions = state["domain_revisions"]
            changed = {}
            for domain in sorted(set(domains)):
                revisions[domain] = int(revisions.get(domain, 0)) + 1
                changed[domain] = revisions[domain]
            event = {
                "operation": operation,
                "operation_id": operation_id,
                "outcome": "published",
                "reason": reason,
                "duration_seconds": round(duration, 6),
                "result_sha256": result_sha,
                "bus_revision": state["bus_revision"],
                "changed": changed,
                "at": _now(),
            }
            state["last_delta"] = event
            state["operations"] = (state["operations"] + [event])[-50:]

        self._update_state(mutate)

    def _record_failure(
        self, operation_id: str, operation: str, reason: str, error: Exception
    ) -> None:
        def mutate(state: dict[str, Any]) -> None:
            state["active"].pop(operation_id, None)
            state["counters"]["failures"] += 1
            state["operations"] = (
                state["operations"]
                + [{"operation": operation, "operation_id": operation_id, "outcome": "failed", "reason": reason, "error": type(error).__name__, "at": _now()}]
            )[-50:]

        self._update_state(mutate)

    def snapshot(self) -> dict[str, Any]:
        state = self._read_state()
        active = {
            key: value
            for key, value in state.get("active", {}).items()
            if self._pid_alive(int(value.get("pid", 0)))
        }
        orphaned_active = sorted(set(state.get("active", {})) - set(active))
        connected = sum(row["admission"] == "runtime-work-plane" for row in PRODUCER_CATALOG)
        separately_bounded = sum(
            row["admission"] == "bounded-test-owner" for row in PRODUCER_CATALOG
        )
        legacy_direct = sum(row["admission"] == "legacy-direct" for row in PRODUCER_CATALOG)
        return {
            **state,
            "active": active,
            "orphaned_active": orphaned_active,
            "quiet_model": "no timers or background workers; explicit demand only",
            "pool_limits": dict(POOL_LIMITS),
            "producer_trace": list(PRODUCER_CATALOG),
            "producer_trace_summary": {
                "total": len(PRODUCER_CATALOG),
                "runtime_work_plane": connected,
                "separately_bounded": separately_bounded,
                "legacy_direct": legacy_direct,
                "owned_total": connected + separately_bounded,
                "complete": legacy_direct == 0,
            },
            "observed_at": _now(),
        }
