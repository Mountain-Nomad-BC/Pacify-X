"""Owned resource lifecycle, safe reclamation, and process-tree closure.

The manager is intentionally conservative: paths and processes become mutable only
after PACIFY-X registered them, and every ambiguous safety check retains the resource.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from typing import Iterator, Mapping, Sequence
from uuid import uuid4

from .file_lock import FileLock, _process_exists
from .wal_transaction import JsonArtifact, JsonWal


_RECLAIM_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.15, 0.35)


def _retry_writable_removal(function: object, path: str, _exc_info: object) -> None:
    """Retry one Windows-style read-only removal without widening scope."""

    os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    function(path)  # type: ignore[operator]


def _remove_owned_target(target: Path) -> None:
    """Remove one already-authorized target with bounded transient-lock retries."""

    last_error: OSError | None = None
    for delay in _RECLAIM_RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            if target.is_dir():
                # ``onerror`` retains Python 3.11 compatibility. It is invoked
                # only for children of the target already admitted by the
                # reclamation gate and makes a read-only entry writable before
                # retrying that exact failed operation.
                shutil.rmtree(target, onerror=_retry_writable_removal)
            else:
                try:
                    target.unlink()
                except PermissionError:
                    target.chmod(stat.S_IREAD | stat.S_IWRITE)
                    target.unlink()
            return
        except OSError as error:
            last_error = error
            if not target.exists():
                return
    if last_error is not None:
        raise last_error
    raise OSError("owned cleanup target remains after bounded reclamation")


class ResourceClassification(str, Enum):
    PROTECTED = "protected"
    EVIDENCE = "evidence"
    QUARANTINE = "quarantine"
    EPHEMERAL = "ephemeral"
    UNKNOWN = "unknown"


class ResourceStatus(str, Enum):
    ACTIVE = "active"
    RETAINED = "retained"
    RECLAIMABLE = "reclaimable"
    RECLAIMED = "reclaimed"
    CLEANUP_FAILED = "cleanup_failed"


class RunState(str, Enum):
    ACTIVE = "active"
    RECOVERABLE = "recoverable"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"


class StoragePressure(str, Enum):
    NORMAL = "normal"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"


class RetentionClass(str, Enum):
    """Storage intent; this does not itself authorize deletion."""

    PROTECTED = "protected"
    EVIDENCE = "evidence"
    OPERATIONAL = "operational"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


ENDED_RUN_STATES = {
    RunState.COMPLETED.value,
    RunState.FAILED.value,
    RunState.CANCELLED.value,
    RunState.ABANDONED.value,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _path_is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
        return bool(attributes & 0x400)  # Windows FILE_ATTRIBUTE_REPARSE_POINT
    except OSError:
        return True


def _inside(target: Path, root: Path) -> bool:
    try:
        target_value = os.path.normcase(str(target.resolve(strict=False)))
        root_value = os.path.normcase(str(root.resolve(strict=True)))
        return os.path.commonpath((target_value, root_value)) == root_value
    except (OSError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class ResourceRecord:
    resource_id: str
    resource_type: str
    project_id: str
    run_id: str
    lane_id: str
    creator: str
    classification: str
    created_at: str
    last_activity_at: str
    expected_cleanup_event: str
    retention_required: bool
    run_state: str = RunState.ACTIVE.value
    active: bool = True
    status: str = ResourceStatus.ACTIVE.value
    path: str | None = None
    allowed_cleanup_root: str | None = None
    pid: int | None = None
    process_identity: str | None = None
    parent_resource_id: str | None = None
    link_status: str = "not_checked"
    evidence_validated: bool = False
    promoted_outputs: tuple[str, ...] = ()
    reclamation_approved: bool = False
    files: int = 0
    directories: int = 0
    bytes: int = 0
    cleanup_result: str | None = None
    retained_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupReceipt:
    cleanup_id: str
    project_id: str
    run_id: str
    lane_id: str
    start_time: str
    end_time: str
    reason: str
    validated_roots: tuple[str, ...]
    workers: int
    priority_mode: str
    resources_considered: int
    resources_reclaimed: int
    resources_skipped: int
    resources_failed: int
    files_removed: int
    directories_removed: int
    bytes_reclaimed: int
    retained_artifacts: tuple[str, ...]
    promoted_artifacts: tuple[str, ...]
    links_encountered: int
    orphan_processes_reaped: int
    errors: tuple[str, ...]
    remaining_owned_ephemeral_resources: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class StorageBudget:
    minimum_free_bytes: int = 5 * 1024**3
    warning_free_fraction: float = 0.15
    high_free_fraction: float = 0.08
    critical_free_fraction: float = 0.04
    max_owned_ephemeral_bytes: int | None = None
    max_workspace_count: int | None = None
    max_file_count: int | None = None


class ResourceLedger:
    """Small atomic JSON ledger; large tree accounting stays incremental."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        self._lock = threading.RLock()

    def _load_unlocked(self) -> tuple[ResourceRecord, ...]:
        if not self.path.is_file():
            return ()
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported resource ledger schema")
        return tuple(ResourceRecord(**item) for item in payload.get("resources", ()))

    def load(self) -> tuple[ResourceRecord, ...]:
        # Readers participate in the same cross-process exclusion boundary as
        # writers.  Atomic replacement protects content integrity, but Windows
        # can transiently deny an open while another process replaces the file.
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            return self._load_unlocked()

    def _write_unlocked(self, records: Sequence[ResourceRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": "1.0",
            "updated_at": _utc_now(),
            "resources": [asdict(item) for item in records],
        }
        handle, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def write(self, records: Sequence[ResourceRecord]) -> None:
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            self._write_unlocked(records)

    def upsert(self, record: ResourceRecord) -> None:
        # The re-entrant lock covers threads in this process; FileLock covers
        # independent CLI/worker processes sharing the same ledger.
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            records = {item.resource_id: item for item in self._load_unlocked()}
            records[record.resource_id] = record
            self._write_unlocked(tuple(records[key] for key in sorted(records)))

    def update(self, resource_id: str, **changes: object) -> ResourceRecord:
        """Atomically update one record without a cross-process read/write gap."""
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            records = {item.resource_id: item for item in self._load_unlocked()}
            if resource_id not in records:
                raise KeyError(resource_id)
            updated = replace(records[resource_id], **changes)
            records[resource_id] = updated
            self._write_unlocked(tuple(records[key] for key in sorted(records)))
            return updated

    def get(self, resource_id: str) -> ResourceRecord:
        for record in self.load():
            if record.resource_id == resource_id:
                return record
        raise KeyError(resource_id)


class ResourceManager:
    """Register, reconcile, and reclaim only conclusively owned resources."""

    def __init__(self, ledger_path: Path, *, receipt_dir: Path | None = None) -> None:
        self.ledger = ResourceLedger(ledger_path)
        self.receipt_dir = (
            receipt_dir or ledger_path.parent / "cleanup-receipts"
        ).resolve()
        self._processes: dict[str, subprocess.Popen[object]] = {}

    def register_path(
        self,
        path: Path,
        *,
        allowed_cleanup_root: Path,
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        classification: ResourceClassification = ResourceClassification.EPHEMERAL,
        retention_required: bool = False,
        expected_cleanup_event: str = "run_end",
        parent_resource_id: str | None = None,
    ) -> ResourceRecord:
        target = path.absolute()
        root = allowed_cleanup_root.resolve(strict=True)
        if not _inside(target, root) or target.resolve(strict=False) == root:
            raise ValueError(
                "resource target must be a child of the allowed cleanup root"
            )
        if target.exists() and _path_is_link_or_reparse(target):
            link_status = "link_or_reparse"
        else:
            link_status = "ordinary_or_absent"
        now = _utc_now()
        record = ResourceRecord(
            resource_id=f"path-{uuid4().hex}",
            resource_type="path",
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator=creator,
            classification=classification.value,
            created_at=now,
            last_activity_at=now,
            expected_cleanup_event=expected_cleanup_event,
            retention_required=retention_required,
            path=str(target),
            allowed_cleanup_root=str(root),
            parent_resource_id=parent_resource_id,
            link_status=link_status,
        )
        self.ledger.upsert(record)
        return record

    def create_workspace(
        self,
        allowed_cleanup_root: Path,
        *,
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        prefix: str = "pacifyx-",
        retention_required: bool = False,
    ) -> ResourceRecord:
        root = allowed_cleanup_root.resolve(strict=True)
        path = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
        try:
            return self.register_path(
                path,
                allowed_cleanup_root=root,
                project_id=project_id,
                run_id=run_id,
                lane_id=lane_id,
                creator=creator,
                retention_required=retention_required,
            )
        except Exception:
            shutil.rmtree(path, ignore_errors=True)
            raise

    def update(self, resource_id: str, **changes: object) -> ResourceRecord:
        allowed = set(ResourceRecord.__dataclass_fields__) - {"resource_id"}
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"unknown resource fields: {sorted(unknown)}")
        return self.ledger.update(resource_id, last_activity_at=_utc_now(), **changes)

    def mark_run_ended(
        self,
        run_id: str,
        state: RunState,
        *,
        retain_reason: str | None = None,
    ) -> tuple[ResourceRecord, ...]:
        if state.value not in ENDED_RUN_STATES and state is not RunState.RECOVERABLE:
            raise ValueError("run must be ended or explicitly recoverable")
        updated: list[ResourceRecord] = []
        for record in self.ledger.load():
            if record.run_id != run_id:
                continue
            # Process closure and an earlier path reclamation are terminal. A
            # later run-level transition must not resurrect either resource as
            # reclaimable and make reconciliation report a false leak.
            if record.status == ResourceStatus.RECLAIMED.value:
                continue
            status = (
                ResourceStatus.RETAINED.value
                if state is RunState.RECOVERABLE or retain_reason
                else ResourceStatus.RECLAIMABLE.value
                if record.classification == ResourceClassification.EPHEMERAL.value
                else ResourceStatus.RETAINED.value
            )
            updated.append(
                self.update(
                    record.resource_id,
                    run_state=state.value,
                    active=False,
                    status=status,
                    retained_reason=retain_reason,
                )
            )
        return tuple(updated)

    def reclaim_ephemeral_path(
        self,
        resource_id: str,
        *,
        reason: str,
        state: RunState = RunState.COMPLETED,
    ) -> CleanupReceipt:
        """End and reclaim one registered ephemeral path without ending sibling resources."""

        if state.value not in ENDED_RUN_STATES:
            raise ValueError("path cleanup requires an ended run state")
        record = self.ledger.get(resource_id)
        if record.resource_type != "path":
            raise ValueError("resource is not a registered path")
        if record.classification != ResourceClassification.EPHEMERAL.value:
            raise ValueError("resource is not an owned ephemeral path")
        if record.status == ResourceStatus.RECLAIMED.value:
            raise ValueError("ephemeral path is already reclaimed")
        self.update(
            resource_id,
            run_state=state.value,
            active=False,
            status=ResourceStatus.RECLAIMABLE.value,
        )
        return self.reclaim(resource_id, reason=reason, apply=True)

    def promote_outputs(
        self, resource_id: str, outputs: Sequence[Path], *, validated: bool
    ) -> ResourceRecord:
        record = self.ledger.get(resource_id)
        target = Path(record.path or ".").resolve(strict=False)
        normalized: list[str] = []
        for output in outputs:
            resolved = output.resolve(strict=True)
            if _inside(resolved, target):
                raise ValueError(
                    "promoted output must be outside the disposable resource"
                )
            if not resolved.is_file():
                raise ValueError("promoted output must be a readable file")
            with resolved.open("rb") as stream:
                stream.read(1)
            normalized.append(str(resolved))
        return self.update(
            resource_id,
            promoted_outputs=tuple(normalized),
            evidence_validated=bool(validated),
        )

    def approve_quarantine_reclamation(self, resource_id: str) -> ResourceRecord:
        record = self.ledger.get(resource_id)
        if record.classification != ResourceClassification.QUARANTINE.value:
            raise ValueError("only quarantine resources require this approval")
        return self.update(resource_id, reclamation_approved=True)

    def _active_dependants(self, resource_id: str) -> tuple[str, ...]:
        return tuple(
            item.resource_id
            for item in self.ledger.load()
            if item.parent_resource_id == resource_id and item.active
        )

    def reclamation_gate(self, record: ResourceRecord) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if record.resource_type != "path" or not record.path:
            reasons.append("resource is not a registered path")
        if record.classification == ResourceClassification.QUARANTINE.value:
            if not record.reclamation_approved:
                reasons.append("quarantine disposition is not approved")
        elif record.classification != ResourceClassification.EPHEMERAL.value:
            reasons.append("resource is not ephemeral")
        if record.active or record.run_state not in ENDED_RUN_STATES:
            reasons.append("owning run is active or recoverable")
        if record.status not in {
            ResourceStatus.RECLAIMABLE.value,
            ResourceStatus.CLEANUP_FAILED.value,
        }:
            reasons.append("resource is not marked reclaimable")
        if record.retention_required and not record.evidence_validated:
            reasons.append("required evidence has not been validated")
        if any(not Path(value).is_file() for value in record.promoted_outputs):
            reasons.append("promoted output is missing")
        if self._active_dependants(record.resource_id):
            reasons.append("active child resources still reference the target")
        if not record.allowed_cleanup_root:
            reasons.append("allowed cleanup root is missing")
        elif not _inside(Path(record.path or "."), Path(record.allowed_cleanup_root)):
            reasons.append("target does not resolve inside its allowed cleanup root")
        if record.path and record.allowed_cleanup_root:
            try:
                if Path(record.path).resolve(strict=False) == Path(
                    record.allowed_cleanup_root
                ).resolve(strict=True):
                    reasons.append("cleanup target is the allowed root itself")
            except OSError:
                reasons.append("target resolution is ambiguous")
        if (
            record.path
            and Path(record.path).exists()
            and _path_is_link_or_reparse(Path(record.path))
        ):
            reasons.append("target is a link or reparse point")
        return not reasons, tuple(sorted(set(reasons)))

    @staticmethod
    def inventory(path: Path) -> dict[str, int]:
        if not path.exists():
            return {"files": 0, "directories": 0, "bytes": 0, "links": 0}
        if path.is_file():
            return {
                "files": 1,
                "directories": 0,
                "bytes": path.stat().st_size,
                "links": int(_path_is_link_or_reparse(path)),
            }
        files = directories = byte_count = links = 0
        stack = [path]
        while stack:
            current = stack.pop()
            directories += 1
            with os.scandir(current) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    if entry.is_symlink() or _path_is_link_or_reparse(entry_path):
                        links += 1
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry_path)
                    else:
                        files += 1
                        try:
                            byte_count += entry.stat(follow_symlinks=False).st_size
                        except OSError:
                            pass
        return {
            "files": files,
            "directories": directories,
            "bytes": byte_count,
            "links": links,
        }

    @staticmethod
    def nested_links_are_internal(path: Path) -> bool:
        """Prove every nested link resolves inside the disposable root."""

        root = path.resolve(strict=True)
        stack = [root]
        try:
            while stack:
                current = stack.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        entry_path = Path(entry.path)
                        if entry.is_symlink() or _path_is_link_or_reparse(entry_path):
                            if not _inside(entry_path.resolve(strict=False), root):
                                return False
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry_path)
            return True
        except OSError:
            return False

    def reclaim(
        self,
        resource_id: str,
        *,
        reason: str,
        apply: bool = False,
    ) -> CleanupReceipt:
        started = _utc_now()
        record = self.ledger.get(resource_id)
        allowed, blockers = self.reclamation_gate(record)
        inventory = {"files": 0, "directories": 0, "bytes": 0, "links": 0}
        errors = list(blockers)
        reclaimed = failed = 0
        skipped = 1
        if allowed:
            try:
                inventory = self.inventory(Path(record.path or ""))
                if inventory["links"] and not self.nested_links_are_internal(
                    Path(record.path or "")
                ):
                    errors.append(
                        "nested link or reparse point escapes the cleanup root or is ambiguous"
                    )
                elif apply and Path(record.path or "").exists():
                    target = Path(record.path or "")
                    _remove_owned_target(target)
                    if target.exists():
                        raise OSError("target remains after reclamation")
                    self.update(
                        resource_id,
                        status=ResourceStatus.RECLAIMED.value,
                        cleanup_result="reclaimed",
                        files=inventory["files"],
                        directories=inventory["directories"],
                        bytes=inventory["bytes"],
                    )
                    reclaimed, skipped = 1, 0
                elif apply:
                    self.update(
                        resource_id,
                        status=ResourceStatus.RECLAIMED.value,
                        cleanup_result="already_absent",
                    )
                    reclaimed, skipped = 1, 0
            except OSError as error:
                errors.append(f"{type(error).__name__}: {error}")
                failed, skipped = 1, 0
                self.update(
                    resource_id,
                    status=ResourceStatus.CLEANUP_FAILED.value,
                    cleanup_result="failed",
                    retained_reason=str(error),
                )
        if errors and apply and allowed and not failed:
            self.update(
                resource_id,
                status=ResourceStatus.RETAINED.value,
                cleanup_result="blocked",
                retained_reason="; ".join(errors),
            )
        receipt = CleanupReceipt(
            cleanup_id=f"cleanup-{uuid4().hex}",
            project_id=record.project_id,
            run_id=record.run_id,
            lane_id=record.lane_id,
            start_time=started,
            end_time=_utc_now(),
            reason=reason,
            validated_roots=(record.allowed_cleanup_root,)
            if record.allowed_cleanup_root
            else (),
            workers=1,
            priority_mode="conservative_sequential",
            resources_considered=1,
            resources_reclaimed=reclaimed,
            resources_skipped=skipped,
            resources_failed=failed,
            files_removed=inventory["files"] if reclaimed else 0,
            directories_removed=inventory["directories"] if reclaimed else 0,
            bytes_reclaimed=inventory["bytes"] if reclaimed else 0,
            retained_artifacts=(record.path,) if skipped or failed else (),
            promoted_artifacts=record.promoted_outputs,
            links_encountered=inventory["links"],
            orphan_processes_reaped=0,
            errors=tuple(errors),
            remaining_owned_ephemeral_resources=sum(
                item.classification == ResourceClassification.EPHEMERAL.value
                and item.status != ResourceStatus.RECLAIMED.value
                for item in self.ledger.load()
            ),
            dry_run=not apply,
        )
        self._write_receipt(receipt)
        return receipt

    def _write_receipt(self, receipt: CleanupReceipt) -> Path:
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        path = self.receipt_dir / f"{receipt.cleanup_id}.json"
        path.write_text(
            json.dumps(asdict(receipt), indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return path

    def spawn_owned_process(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        environment: Mapping[str, str] | None = None,
        stdout: int | None = subprocess.PIPE,
        stderr: int | None = subprocess.PIPE,
        text: bool = True,
        start_suspended: bool = False,
    ) -> tuple[ResourceRecord, subprocess.Popen[object]]:
        if start_suspended and os.name != "nt":
            raise ValueError("suspended process creation is Windows-only")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        if start_suspended:
            creationflags |= 0x00000004  # Windows CREATE_SUSPENDED
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment) if environment is not None else None,
            stdout=stdout,
            stderr=stderr,
            text=text,
            shell=False,
            start_new_session=os.name != "nt",
            creationflags=creationflags,
        )
        now = _utc_now()
        identity = hashlib.sha256(
            (str(process.pid) + "\0" + "\0".join(command) + "\0" + now).encode()
        ).hexdigest()
        record = ResourceRecord(
            resource_id=f"process-{uuid4().hex}",
            resource_type="process",
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator=creator,
            classification=ResourceClassification.EPHEMERAL.value,
            created_at=now,
            last_activity_at=now,
            expected_cleanup_event="process_exit_or_cancel",
            retention_required=False,
            pid=process.pid,
            process_identity=identity,
        )
        self.ledger.upsert(record)
        self._processes[record.resource_id] = process
        return record, process

    def complete_process(self, resource_id: str) -> ResourceRecord:
        process = self._processes.get(resource_id)
        if process is None or process.poll() is None:
            raise ValueError("owned process has not exited")
        for stream in (process.stdout, process.stderr, process.stdin):
            if stream is not None and not stream.closed:
                stream.close()
        self._processes.pop(resource_id, None)
        return self.update(
            resource_id,
            active=False,
            run_state=RunState.COMPLETED.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result=f"exit_{process.returncode}",
        )

    def complete_current_process(
        self,
        resource_id: str,
        *,
        expected_pid: int,
        exit_code: int,
        run_state: RunState = RunState.COMPLETED,
    ) -> ResourceRecord:
        """Close a process record from inside its independently-owned worker.

        A durable worker outlives the one-shot parent that created its Popen
        handle.  The child may close only its exact active ledger identity; it
        cannot close an arbitrary or reused PID.
        """
        record = self.ledger.get(resource_id)
        if record.resource_type != "process" or record.pid != expected_pid or expected_pid != os.getpid():
            raise PermissionError("current process does not own the resource record")
        if not record.active:
            if record.status == ResourceStatus.RECLAIMED.value:
                return record
            raise PermissionError("current process resource is already inactive")
        return self.update(
            resource_id,
            active=False,
            run_state=run_state.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result=f"exit_{int(exit_code)}",
        )

    def complete_persisted_process_after_exit(
        self,
        resource_id: str,
        *,
        expected_pid: int,
        run_state: RunState,
    ) -> ResourceRecord:
        """Close durable process custody only after the exact PID is absent.

        This is the external half of terminal publication for detached Studio
        workers.  A worker cannot truthfully publish both its own death and the
        terminal run state, so an observing host verifies absence first.
        """
        record = self.ledger.get(resource_id)
        if record.resource_type != "process" or record.pid != expected_pid:
            raise PermissionError("persisted process identity does not match")
        if not record.active:
            if record.status == ResourceStatus.RECLAIMED.value:
                return record
            raise PermissionError("persisted process resource is already inactive")
        if _process_exists(expected_pid):
            raise ValueError("persisted process is still alive")
        return self.update(
            resource_id,
            active=False,
            run_state=run_state.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result="process_absence_verified",
        )

    def terminate_owned_process(
        self, resource_id: str, *, graceful_timeout_seconds: float = 3.0
    ) -> CleanupReceipt:
        record = self.ledger.get(resource_id)
        process = self._processes.get(resource_id)
        started = _utc_now()
        errors: list[str] = []
        reaped = 0
        if record.resource_type != "process" or process is None:
            errors.append("live process identity cannot be proven")
        elif process.pid != record.pid:
            errors.append("registered process identity mismatch")
        elif process.poll() is not None:
            reaped = 1
        else:
            try:
                if os.name == "nt":
                    process.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                try:
                    process.wait(timeout=graceful_timeout_seconds)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        completed = subprocess.run(
                            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                            text=True,
                            capture_output=True,
                            timeout=15,
                            check=False,
                        )
                        if completed.returncode not in {0, 128}:
                            errors.append(
                                completed.stderr.strip()
                                or f"taskkill exit {completed.returncode}"
                            )
                    else:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    process.wait(timeout=15)
                reaped = int(process.poll() is not None)
                if not reaped:
                    errors.append("owned process remains active after cancellation")
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(f"{type(error).__name__}: {error}")
        if reaped:
            for stream in (process.stdout, process.stderr, process.stdin):
                if stream is not None and not stream.closed:
                    stream.close()
            self._processes.pop(resource_id, None)
            self.update(
                resource_id,
                active=False,
                run_state=RunState.CANCELLED.value,
                status=ResourceStatus.RECLAIMED.value,
                cleanup_result="process_tree_terminated",
            )
        else:
            self.update(
                resource_id,
                status=ResourceStatus.CLEANUP_FAILED.value,
                cleanup_result="process_tree_not_verified",
                retained_reason="; ".join(errors),
            )
        receipt = CleanupReceipt(
            cleanup_id=f"cleanup-{uuid4().hex}",
            project_id=record.project_id,
            run_id=record.run_id,
            lane_id=record.lane_id,
            start_time=started,
            end_time=_utc_now(),
            reason="owned_process_cancellation",
            validated_roots=(),
            workers=1,
            priority_mode="bounded_process_tree_shutdown",
            resources_considered=1,
            resources_reclaimed=reaped,
            resources_skipped=int(bool(errors) and not reaped),
            resources_failed=int(bool(errors) and not reaped),
            files_removed=0,
            directories_removed=0,
            bytes_reclaimed=0,
            retained_artifacts=(),
            promoted_artifacts=(),
            links_encountered=0,
            orphan_processes_reaped=reaped,
            errors=tuple(errors),
            remaining_owned_ephemeral_resources=sum(
                item.classification == ResourceClassification.EPHEMERAL.value
                and item.status != ResourceStatus.RECLAIMED.value
                for item in self.ledger.load()
            ),
            dry_run=False,
        )
        self._write_receipt(receipt)
        return receipt

    def retire_proven_absent_process(
        self, resource_id: str, *, apply: bool
    ) -> CleanupReceipt:
        """Close persisted process custody only when the recorded PID is dead."""

        record = self.ledger.get(resource_id)
        started = _utc_now()
        errors: list[str] = []
        reclaimed = 0
        if record.resource_type != "process" or not record.active:
            errors.append("resource is not an active process")
        elif record.pid is None or _process_exists(record.pid):
            errors.append("persisted process absence is not proven")
        elif apply:
            self.update(
                resource_id,
                active=False,
                run_state=RunState.ABANDONED.value,
                status=ResourceStatus.RECLAIMED.value,
                cleanup_result="persisted_process_proven_absent",
            )
            reclaimed = 1
        receipt = CleanupReceipt(
            cleanup_id=f"cleanup-{uuid4().hex}",
            project_id=record.project_id,
            run_id=record.run_id,
            lane_id=record.lane_id,
            start_time=started,
            end_time=_utc_now(),
            reason="persisted_owned_process_absence_reconciliation",
            validated_roots=(),
            workers=1,
            priority_mode="identity_conservative_process_reconciliation",
            resources_considered=1,
            resources_reclaimed=reclaimed,
            resources_skipped=int(not reclaimed),
            resources_failed=0,
            files_removed=0,
            directories_removed=0,
            bytes_reclaimed=0,
            retained_artifacts=(),
            promoted_artifacts=(),
            links_encountered=0,
            orphan_processes_reaped=0,
            errors=tuple(errors),
            remaining_owned_ephemeral_resources=sum(
                item.classification == ResourceClassification.EPHEMERAL.value
                and item.status != ResourceStatus.RECLAIMED.value
                for item in self.ledger.load()
            ),
            dry_run=not apply,
        )
        self._write_receipt(receipt)
        return receipt

    @contextmanager
    def workspace(
        self,
        allowed_cleanup_root: Path,
        *,
        project_id: str,
        run_id: str,
        lane_id: str,
        creator: str,
        retain_on_failure: bool = False,
    ) -> Iterator[Path]:
        record = self.create_workspace(
            allowed_cleanup_root,
            project_id=project_id,
            run_id=run_id,
            lane_id=lane_id,
            creator=creator,
        )
        failed = False
        try:
            yield Path(record.path or "")
        except BaseException:
            failed = True
            raise
        finally:
            if failed and retain_on_failure:
                self.mark_run_ended(
                    run_id, RunState.FAILED, retain_reason="governed_debug_retention"
                )
            else:
                self.mark_run_ended(
                    run_id, RunState.FAILED if failed else RunState.COMPLETED
                )
                self.reclaim(
                    record.resource_id,
                    reason="managed_workspace_scope_closed",
                    apply=True,
                )

    def storage_status(
        self, path: Path, budget: StorageBudget = StorageBudget()
    ) -> dict[str, object]:
        usage = shutil.disk_usage(path)
        free_fraction = usage.free / usage.total if usage.total else 0.0
        records = self.ledger.load()
        owned = [
            item
            for item in records
            if item.classification == ResourceClassification.EPHEMERAL.value
            and item.status != ResourceStatus.RECLAIMED.value
        ]
        owned_bytes = sum(item.bytes for item in owned)
        if (
            usage.free < budget.minimum_free_bytes
            or free_fraction <= budget.critical_free_fraction
        ):
            pressure = StoragePressure.CRITICAL
        elif free_fraction <= budget.high_free_fraction:
            pressure = StoragePressure.HIGH
        elif free_fraction <= budget.warning_free_fraction:
            pressure = StoragePressure.WARNING
        else:
            pressure = StoragePressure.NORMAL
        alerts: list[str] = []
        if (
            budget.max_owned_ephemeral_bytes is not None
            and owned_bytes > budget.max_owned_ephemeral_bytes
        ):
            alerts.append("owned ephemeral byte budget exceeded")
        if (
            budget.max_workspace_count is not None
            and len(owned) > budget.max_workspace_count
        ):
            alerts.append("workspace count budget exceeded")
        if (
            budget.max_file_count is not None
            and sum(item.files for item in owned) > budget.max_file_count
        ):
            alerts.append("owned ephemeral file budget exceeded")
        return {
            "valid": not alerts,
            "pressure": pressure.value,
            "host_total_bytes": usage.total,
            "host_free_bytes": usage.free,
            "host_free_fraction": free_fraction,
            "owned_ephemeral_bytes": owned_bytes,
            "owned_ephemeral_resources": len(owned),
            "quarantine_bytes": sum(
                item.bytes
                for item in records
                if item.classification == ResourceClassification.QUARANTINE.value
            ),
            "alerts": alerts,
        }

    def reconcile(self, *, apply: bool = False) -> dict[str, object]:
        receipts: list[CleanupReceipt] = []
        retained: list[dict[str, object]] = []
        for record in self.ledger.load():
            if record.resource_type == "process" and record.active:
                if record.resource_id in self._processes:
                    receipts.append(self.terminate_owned_process(record.resource_id))
                elif record.pid is not None and not _process_exists(record.pid):
                    receipt = self.retire_proven_absent_process(
                        record.resource_id, apply=apply
                    )
                    receipts.append(receipt)
                    if receipt.resources_reclaimed == 0:
                        retained.append(
                            {
                                "resource_id": record.resource_id,
                                "reason": "persisted process is absent; apply is required to close custody",
                            }
                        )
                else:
                    retained.append(
                        {
                            "resource_id": record.resource_id,
                            "reason": "persisted PID cannot be reaped without live identity proof",
                        }
                    )
            elif record.resource_type == "path" and record.status in {
                ResourceStatus.RECLAIMABLE.value,
                ResourceStatus.CLEANUP_FAILED.value,
            }:
                receipt = self.reclaim(
                    record.resource_id,
                    reason="startup_or_run_reconciliation",
                    apply=apply,
                )
                receipts.append(receipt)
                if receipt.resources_reclaimed == 0:
                    retained.append(
                        {
                            "resource_id": record.resource_id,
                            "reason": "; ".join(receipt.errors) or "dry run",
                        }
                    )
        final = self.ledger.load()
        active_processes = sum(
            item.resource_type == "process" and item.active for item in final
        )
        unexplained = sum(
            item.classification == ResourceClassification.EPHEMERAL.value
            and item.status
            not in {ResourceStatus.RECLAIMED.value, ResourceStatus.RETAINED.value}
            for item in final
        )
        cleanup_failures = sum(
            item.status == ResourceStatus.CLEANUP_FAILED.value for item in final
        )
        return {
            "valid": active_processes == 0
            and unexplained == 0
            and cleanup_failures == 0,
            "dry_run": not apply,
            "owned_child_processes_active": active_processes,
            "owned_ephemeral_unexplained": unexplained,
            "cleanup_failures": cleanup_failures,
            "receipts": [asdict(item) for item in receipts],
            "retained": retained,
            "resource_ledger_reconciled": active_processes == 0 and unexplained == 0,
        }


def resource_status(
    ledger_path: Path, *, storage_path: Path | None = None
) -> dict[str, object]:
    manager = ResourceManager(ledger_path)
    records = manager.ledger.load()
    classifications = {
        classification.value: sum(
            item.classification == classification.value for item in records
        )
        for classification in ResourceClassification
    }
    output: dict[str, object] = {
        "valid": True,
        "resource_count": len(records),
        "classifications": classifications,
        "active_processes": sum(
            item.resource_type == "process" and item.active for item in records
        ),
        "reclaimable_paths": sum(
            item.resource_type == "path"
            and item.status == ResourceStatus.RECLAIMABLE.value
            for item in records
        ),
        "cleanup_failures": sum(
            item.status == ResourceStatus.CLEANUP_FAILED.value for item in records
        ),
    }
    if storage_path is not None:
        output["storage"] = manager.storage_status(storage_path)
    return output


OPERATIONAL_HISTORY_SCHEMA_VERSION = "px.operational-history/1.0"
RETENTION_RECEIPT_SCHEMA_VERSION = "px.retention-receipt/1.0"


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _record_digest(record: Mapping[str, object]) -> str:
    value = dict(record)
    value.pop("record_sha256", None)
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def retention_policy(retention_class: RetentionClass | str) -> dict[str, object]:
    """Return the non-authorizing disposition for one explicit retention class."""
    try:
        normalized = RetentionClass(retention_class)
    except ValueError:
        normalized = RetentionClass.UNKNOWN
    decisions = {
        RetentionClass.PROTECTED: ("retain", False, "protected material is immutable"),
        RetentionClass.EVIDENCE: ("retain", False, "evidence requires explicit policy"),
        RetentionClass.OPERATIONAL: (
            "bounded_prune",
            False,
            "prune only through a retained ancestry anchor and receipt",
        ),
        RetentionClass.TRANSIENT: (
            "safe_gate",
            False,
            "delegate only registered PACIFY-X ephemerals to ResourceManager",
        ),
        RetentionClass.UNKNOWN: ("retain", False, "classification is ambiguous"),
    }
    action, auto_delete, reason = decisions[normalized]
    return {
        "schema_version": "px.retention-policy-decision/1.0",
        "retention_class": normalized.value,
        "action": action,
        "auto_delete": auto_delete,
        "reason": reason,
    }


class RetentionManager:
    """Bound operational history and delegate transient cleanup to its authority."""

    def __init__(
        self,
        resource_manager: ResourceManager,
        *,
        allowed_root: Path,
        wal_root: Path,
        receipt_dir: Path | None = None,
    ) -> None:
        self.resource_manager = resource_manager
        self.allowed_root = allowed_root.resolve(strict=True)
        self.wal = JsonWal(wal_root, self.allowed_root)
        self.receipt_dir = (
            receipt_dir or self.allowed_root / ".pacify-x" / "retention-receipts"
        ).resolve()
        if not _inside(self.receipt_dir, self.allowed_root):
            raise ValueError("retention receipt directory must stay below allowed root")

    def reclaim_transient(
        self, resource_id: str, *, reason: str, apply: bool = False
    ) -> CleanupReceipt:
        """Use the sole cleanup authority after proving transient/ephemeral identity."""
        record = self.resource_manager.ledger.get(resource_id)
        if record.classification != ResourceClassification.EPHEMERAL.value:
            # A normal ResourceManager receipt records the refusal and retained target.
            return self.resource_manager.reclaim(
                resource_id, reason=reason, apply=apply
            )
        return self.resource_manager.reclaim(resource_id, reason=reason, apply=apply)

    @staticmethod
    def _validate_history(
        value: object,
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "anchor",
            "records",
        }:
            raise ValueError("operational history fields are not exact")
        if value.get("schema_version") != OPERATIONAL_HISTORY_SCHEMA_VERSION:
            raise ValueError("operational history schema is unsupported")
        anchor = value.get("anchor")
        if anchor is None:
            previous: str | None = None
            sequence = 0
        elif (
            not isinstance(anchor, dict)
            or set(anchor) != {"through_sequence", "head_sha256"}
            or not isinstance(anchor.get("through_sequence"), int)
            or int(anchor["through_sequence"]) < 1
            or not isinstance(anchor.get("head_sha256"), str)
        ):
            raise ValueError("operational ancestry anchor is invalid")
        else:
            previous = str(anchor["head_sha256"])
            sequence = int(anchor["through_sequence"])
        raw_records = value.get("records")
        if not isinstance(raw_records, list) or len(raw_records) > 100_000:
            raise ValueError("operational history record count is invalid")
        records: list[dict[str, object]] = []
        for raw in raw_records:
            if (
                not isinstance(raw, dict)
                or set(raw)
                != {
                    "sequence",
                    "previous_record_sha256",
                    "payload",
                    "record_sha256",
                }
                or raw.get("sequence") != sequence + 1
                or raw.get("previous_record_sha256") != previous
                or raw.get("record_sha256") != _record_digest(raw)
            ):
                raise ValueError("operational history ancestry is invalid")
            sequence += 1
            previous = str(raw["record_sha256"])
            records.append(dict(raw))
        return dict(value), records

    def prune_operational_history(
        self,
        history_path: Path,
        *,
        max_records: int,
        apply: bool = False,
    ) -> dict[str, object]:
        """Retain a bounded suffix with an immutable ancestry anchor and receipt."""
        if max_records < 1 or max_records > 100_000:
            raise ValueError("max_records must be between 1 and 100000")
        path = history_path.resolve(strict=True)
        if (
            not path.is_file()
            or path.is_symlink()
            or not _inside(path, self.allowed_root)
        ):
            raise ValueError("operational history is outside bounded custody")
        try:
            raw = path.read_bytes()
            value = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("operational history is unreadable") from error
        history, records = self._validate_history(value)
        remove_count = max(0, len(records) - max_records)
        before_sha256 = hashlib.sha256(raw).hexdigest()
        if remove_count == 0:
            return {
                "schema_version": RETENTION_RECEIPT_SCHEMA_VERSION,
                "valid": True,
                "applied": False,
                "reason": "within_bound",
                "retention_class": RetentionClass.OPERATIONAL.value,
                "records_before": len(records),
                "records_after": len(records),
                "before_sha256": before_sha256,
                "after_sha256": before_sha256,
            }
        removed = records[:remove_count]
        retained = records[remove_count:]
        last_removed = removed[-1]
        anchor = {
            "through_sequence": last_removed["sequence"],
            "head_sha256": last_removed["record_sha256"],
        }
        next_history = {
            "schema_version": OPERATIONAL_HISTORY_SCHEMA_VERSION,
            "anchor": anchor,
            "records": retained,
        }
        # Revalidate the resulting suffix before any write is staged.
        self._validate_history(next_history)
        after_sha256 = hashlib.sha256(_canonical_json(next_history)).hexdigest()
        receipt_id = f"retention-{int(anchor['through_sequence']):08d}-{str(anchor['head_sha256'])[:16]}"
        anchor_path = (
            self.receipt_dir
            / "anchors"
            / f"{int(anchor['through_sequence']):08d}-{anchor['head_sha256']}.json"
        )
        receipt_path = self.receipt_dir / f"{receipt_id}.json"
        receipt = {
            "schema_version": RETENTION_RECEIPT_SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "valid": True,
            "applied": apply,
            "retention_class": RetentionClass.OPERATIONAL.value,
            "history_path": path.as_posix(),
            "records_before": len(records),
            "records_pruned": remove_count,
            "records_after": len(retained),
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "anchor_path": anchor_path.as_posix(),
            "anchor": anchor,
            "ancestry_preserved": True,
        }
        if not apply:
            return receipt
        transaction = self.wal.commit(
            (
                JsonArtifact("state", path, next_history),
                JsonArtifact("receipt", anchor_path, anchor),
                JsonArtifact("receipt", receipt_path, receipt),
            ),
            transaction_id=receipt_id,
        )
        return {**receipt, "transaction": transaction}
