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
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import threading
import time
from typing import Iterator, Mapping, Sequence
from uuid import uuid4

from .file_lock import FileLock, _process_exists, _process_start_fingerprint
from .json_io import decode_json_object
from .wal_transaction import JsonArtifact, JsonWal, _atomic_replace, _bounded_image, _wal_lock
from .archive_io import reject_path_links


_RECLAIM_RETRY_DELAYS_SECONDS = (0.0, 0.05, 0.15, 0.35)
_LEDGER_IO_RETRY_DELAYS_SECONDS = (0.0, 0.01, 0.05, 0.15, 0.35, 0.75)


def _retry_transient_permission_error(operation: object) -> object:
    """Retry only bounded access-denied ledger I/O, then fail closed."""

    last_error: PermissionError | None = None
    for delay in _LEDGER_IO_RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            return operation()  # type: ignore[operator]
        except PermissionError as error:
            last_error = error
    assert last_error is not None
    raise last_error


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
    CLEANUP_PENDING = "cleanup_pending"


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


def _lexically_inside(target: Path, root: Path) -> bool:
    """Check an absent target's registered lexical containment without resolving it."""

    try:
        target_value = os.path.normcase(os.path.abspath(os.fspath(target)))
        root_value = os.path.normcase(os.path.abspath(os.fspath(root)))
        return os.path.commonpath((target_value, root_value)) == root_value
    except ValueError:
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
    path_identity: tuple[int, ...] | None = None
    cleanup_intent: dict[str, object] | None = None
    cleanup_receipt_id: str | None = None


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
        encoded = _retry_transient_permission_error(
            lambda: self.path.read_text(encoding="utf-8")
        )
        if not isinstance(encoded, str):
            raise TypeError("resource ledger read did not return text")
        payload = json.loads(encoded)
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported resource ledger schema")
        return tuple(ResourceRecord(**item) for item in payload.get("resources", ()))

    def load(self) -> tuple[ResourceRecord, ...]:
        # Readers participate in the same cross-process exclusion boundary as
        # writers.  Atomic replacement protects content integrity, but Windows
        # can transiently deny an open while another process replaces the file.
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            return self._load_unlocked()

    def observe(self) -> tuple[ResourceRecord, ...]:
        """Read one bounded image without creating lock/lease or ledger files.

        This is observational input, never authorization to mutate a resource.
        Apply paths must reacquire their owner and check current conditions.
        """
        with self._lock:
            def acquire():
                reject_path_links(self.path)
                if not os.path.lexists(self.path):
                    return None
                return _bounded_image(self.path, limit=64 * 1024 * 1024)
            raw = _retry_transient_permission_error(acquire)
            return _resource_records_from_image(raw)

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
            _retry_transient_permission_error(
                lambda: os.replace(temporary, self.path)
            )
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

    def rebind_active_process(
        self,
        resource_id: str,
        *,
        expected_launcher_pid: int,
        actual_pid: int,
        expected_run_id: str,
        expected_lane_id: str,
        expected_creator: str,
        launch_binding: str,
    ) -> ResourceRecord:
        """Atomically compare and transfer one active process identity."""
        with self._lock, FileLock(self.lock_path, timeout_seconds=30.0):
            records = {item.resource_id: item for item in self._load_unlocked()}
            if resource_id not in records:
                raise KeyError(resource_id)
            record = records[resource_id]
            if (
                record.resource_type != "process"
                or not record.active
                or record.pid != expected_launcher_pid
                or record.run_id != expected_run_id
                or record.lane_id != expected_lane_id
                or record.creator != expected_creator
                or not record.process_identity
            ):
                raise PermissionError("process launch handoff does not match resource custody")
            if actual_pid == expected_launcher_pid:
                return record
            start_fingerprint = _process_start_fingerprint(actual_pid)
            identity = (
                f"process-start:{start_fingerprint}"
                if start_fingerprint is not None
                else hashlib.sha256(
                    (
                        record.process_identity
                        + "\0handoff\0"
                        + str(actual_pid)
                        + "\0"
                        + launch_binding
                    ).encode()
                ).hexdigest()
            )
            updated = replace(
                record,
                pid=actual_pid,
                process_identity=identity,
                last_activity_at=_utc_now(),
            )
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
        self._process_jobs: dict[str, object] = {}
        self._failed_creation_custody: dict[str, object] = {}
        self._supervision_failures: dict[str, object] = {}
        self._cleanup_effects: dict[str, dict] = {}

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
            path_identity=self._path_identity(target),
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

    def bind_created_path(self, resource_id: str, expected_bytes: bytes) -> ResourceRecord:
        """Bind an absent-path registration only to the exact intended publication."""
        if type(expected_bytes) is not bytes or len(expected_bytes) > 8 * 1024 * 1024:
            raise ValueError('created path binding requires bounded exact bytes')
        with self.ledger._lock, _wal_lock(self.ledger.lock_path, 30.0):
            records = {row.resource_id: row for row in self.ledger._load_unlocked()}
            record = records[resource_id]
            if (record.resource_type != 'path' or not record.active or record.run_state != 'active'
                    or record.classification != ResourceClassification.EPHEMERAL.value or not record.path):
                raise ValueError('created path registration is not an active owned ephemeral')
            target = Path(record.path)
            reject_path_links(target)
            if not record.allowed_cleanup_root or not _inside(target, Path(record.allowed_cleanup_root)):
                raise ValueError('created path escaped its registered root')
            identity = self._path_identity(target)
            if identity is None or _bounded_image(target, limit=len(expected_bytes)) != expected_bytes:
                raise ValueError('created path does not match intended publication')
            if self._path_identity(target) != identity:
                raise ValueError('created path changed during binding')
            if record.path_identity is not None and tuple(record.path_identity) != identity:
                raise ValueError('created path registration is already bound to another generation')
            updated = replace(record, path_identity=identity, last_activity_at=_utc_now())
            records[resource_id] = updated
            self.ledger._write_unlocked(tuple(records[key] for key in sorted(records)))
            return updated

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

    def _pending_custody_resource_ids(self) -> set[str]:
        if len(self._pending_creation_ids()) + len(self._supervision_failures) > 64:
            raise ValueError('retained custody exceeds bounded recovery batch')
        pending = self._pending_creation_ids()
        for custody in self._supervision_failures.values():
            record = custody.get('record')
            if record is not None:
                pending.add(record.resource_id)
            creation = custody.get('creation', {})
            if creation.get('resource_id'):
                pending.add(creation['resource_id'])
        return pending

    def _pending_creation_ids(self) -> set[str]:
        return set(self._failed_creation_custody) | (self._process_jobs.keys() - self._processes.keys())

    def _active_dependants(self, resource_id: str, records=None) -> tuple[str, ...]:
        pending = self._pending_custody_resource_ids()
        children = {}
        for index, item in enumerate(self.ledger.observe() if records is None else records):
            if index >= 100000:
                raise ValueError('resource dependency inventory exceeds bound')
            children.setdefault(item.parent_resource_id, []).append(item)
        seen, blocked, queue = {resource_id}, set(), [resource_id]
        while queue:
            for child in children.get(queue.pop(), ()):
                if child.active or child.cleanup_intent is not None or child.resource_id in pending or child.resource_id in seen:
                    blocked.add(child.resource_id)
                if child.resource_id not in seen:
                    seen.add(child.resource_id)
                    queue.append(child.resource_id)
        return tuple(sorted(blocked))

    def reclamation_gate(self, record: ResourceRecord, *, records=None) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        target = Path(record.path or ".")
        allowed_root = (
            Path(record.allowed_cleanup_root)
            if record.allowed_cleanup_root
            else None
        )
        # When both registered paths are already physically absent there is
        # nothing left to delete or resolve through links.  Lexical containment
        # is sufficient only to close that no-effect ledger record.  Any path
        # that still exists continues through the strict resolved check below.
        absent_registered_chain = bool(
            record.path
            and allowed_root is not None
            and not os.path.lexists(target)
            and not os.path.lexists(allowed_root)
        )
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
            ResourceStatus.CLEANUP_PENDING.value,
        }:
            reasons.append("resource is not marked reclaimable")
        if record.retention_required and not record.evidence_validated:
            reasons.append("required evidence has not been validated")
        if any(not Path(value).is_file() for value in record.promoted_outputs):
            reasons.append("promoted output is missing")
        if self._active_dependants(record.resource_id, records):
            reasons.append("active child resources still reference the target")
        if allowed_root is None:
            reasons.append("allowed cleanup root is missing")
        elif absent_registered_chain:
            if not _lexically_inside(target, allowed_root):
                reasons.append("target is not lexically inside its absent allowed cleanup root")
        elif not _inside(target, allowed_root):
            reasons.append("target does not resolve inside its allowed cleanup root")
        if record.path and allowed_root is not None:
            try:
                if absent_registered_chain:
                    target_value = os.path.normcase(os.path.abspath(os.fspath(target)))
                    root_value = os.path.normcase(
                        os.path.abspath(os.fspath(allowed_root))
                    )
                    same_target = target_value == root_value
                else:
                    same_target = target.resolve(strict=False) == allowed_root.resolve(
                        strict=True
                    )
                if same_target:
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

    @staticmethod
    def _path_identity(path):
        if not os.path.lexists(path):
            return None
        info = path.lstat()
        return (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode),
                getattr(info, 'st_birthtime_ns', 0))

    @staticmethod
    def _validate_cleanup_intent(operation, record):
        fields = {'schema_version', 'cleanup_id', 'resource_id', 'path', 'path_identity',
                  'phase', 'started', 'reason', 'inventory', 'initially_absent'}
        if type(operation) is not dict or operation.get('phase') not in {'effect_pending', 'effect_complete'}:
            raise ValueError('invalid retained cleanup operation')
        if operation['phase'] == 'effect_complete':
            fields.add('receipt')
        if set(operation) != fields or operation['schema_version'] != 'px.cleanup-intent/1.0':
            raise ValueError('invalid retained cleanup schema')
        if (operation['resource_id'] != record.resource_id or operation['path'] != record.path
                or type(operation['cleanup_id']) is not str
                or re.fullmatch(r'cleanup-[0-9a-f]{32}', operation['cleanup_id']) is None):
            raise ValueError('retained cleanup operation identity mismatch')
        if any(type(operation[key]) is not str or not operation[key] or len(operation[key]) > 4096
               for key in ('started', 'reason')):
            raise ValueError('invalid retained cleanup text')
        identity = operation['path_identity']
        if (type(operation['initially_absent']) is not bool
                or operation['initially_absent'] != (identity is None)
                or (identity is not None and (type(identity) not in (tuple, list) or len(identity) != 4
                    or any(type(value) is not int or value < 0 for value in identity)))):
            raise ValueError('invalid retained cleanup generation')
        if identity is not None and tuple(identity) != tuple(record.path_identity or ()):
            raise ValueError('retained cleanup generation does not match its resource')
        inventory = operation['inventory']
        if (type(inventory) is not dict or set(inventory) != {'files', 'directories', 'bytes', 'links'}
                or any(type(value) is not int or not 0 <= value <= 2**63 - 1 for value in inventory.values())):
            raise ValueError('invalid retained cleanup inventory')
        if operation['phase'] == 'effect_complete':
            value = operation['receipt']
            if type(value) is not dict or set(value) != set(CleanupReceipt.__dataclass_fields__):
                raise ValueError('invalid retained cleanup receipt schema')
            expected = {'cleanup_id': operation['cleanup_id'], 'project_id': record.project_id,
                'run_id': record.run_id, 'lane_id': record.lane_id, 'start_time': operation['started'],
                'reason': operation['reason'], 'resources_considered': 1, 'resources_reclaimed': 1,
                'resources_failed': 0, 'resources_skipped': 0, 'files_removed': inventory['files'],
                'directories_removed': inventory['directories'], 'bytes_reclaimed': inventory['bytes'],
                'links_encountered': inventory['links'], 'orphan_processes_reaped': 0, 'workers': 1,
                'dry_run': False, 'priority_mode': 'conservative_sequential'}
            if any(type(value[key]) is not type(expected_value) or value[key] != expected_value
                   for key, expected_value in expected.items()):
                raise ValueError('retained cleanup receipt scope or effect mismatch')
            if (value['errors'] not in ([], ()) or value['retained_artifacts'] not in ([], ())
                    or type(value['validated_roots']) not in (list, tuple)
                    or type(value['promoted_artifacts']) not in (list, tuple)
                    or list(value['validated_roots']) != [record.allowed_cleanup_root]
                    or list(value['promoted_artifacts']) != list(record.promoted_outputs)
                    or type(value['remaining_owned_ephemeral_resources']) is not int
                    or value['remaining_owned_ephemeral_resources'] < 0
                    or type(value['end_time']) is not str or not value['end_time'] or len(value['end_time']) > 128):
                raise ValueError('invalid retained cleanup receipt details')

    def _cleanup_receipt(self, record, records, *, reason, started, inventory,
                         errors=(), reclaimed=False, apply=False, cleanup_id=None):
        return CleanupReceipt(
            cleanup_id=cleanup_id or f"cleanup-{uuid4().hex}",
            project_id=record.project_id, run_id=record.run_id, lane_id=record.lane_id,
            start_time=started, end_time=_utc_now(), reason=reason,
            validated_roots=(record.allowed_cleanup_root,) if record.allowed_cleanup_root else (),
            workers=1, priority_mode='conservative_sequential', resources_considered=1,
            resources_reclaimed=int(reclaimed), resources_skipped=int(not reclaimed),
            resources_failed=0, files_removed=inventory['files'] if reclaimed else 0,
            directories_removed=inventory['directories'] if reclaimed else 0,
            bytes_reclaimed=inventory['bytes'] if reclaimed else 0,
            retained_artifacts=() if reclaimed else (record.path,),
            promoted_artifacts=record.promoted_outputs, links_encountered=inventory['links'],
            orphan_processes_reaped=0, errors=tuple(errors),
            remaining_owned_ephemeral_resources=sum(
                row.classification == ResourceClassification.EPHEMERAL.value
                and row.status != ResourceStatus.RECLAIMED.value
                and not (reclaimed and row.resource_id == record.resource_id)
                for row in records), dry_run=not apply)

    def reclaim(self, resource_id: str, *, reason: str, apply: bool = False) -> CleanupReceipt:
        """Revalidate under writer exclusion; retain intent until receipt acknowledgment.

        Filesystem identity checks are observation checks, not pinned ancestor
        handles. Ambiguous post-crash deletion accounting remains unresolved.
        """
        if type(apply) is not bool:
            raise ValueError('cleanup apply must be an actual boolean')
        started = _utc_now()
        observed = self.ledger.observe()
        matches = [row for row in observed if row.resource_id == resource_id]
        if len(matches) != 1:
            raise KeyError(resource_id)
        record = matches[0]
        allowed, blockers = self.reclamation_gate(record, records=observed)
        target = Path(record.path or '')
        empty_inventory = {'files': 0, 'directories': 0, 'bytes': 0, 'links': 0}
        try:
            identity = self._path_identity(target) if allowed else None
            inventory = self.inventory(target) if allowed else empty_inventory
        except (OSError, ValueError) as error:
            if apply:
                raise
            receipt = self._cleanup_receipt(record, observed, reason=reason,
                started=started, inventory=empty_inventory,
                errors=(*blockers, str(error)))
            return replace(receipt, resources_failed=1, resources_skipped=0)
        if not apply:
            return self._cleanup_receipt(record, observed, reason=reason, started=started,
                inventory=inventory, errors=blockers)
        # All cooperating registration, retention and record writers use this
        # same ledger lock. Inventory happens before exclusion, then authority
        # and the physical generation are rechecked inside it.
        with self.ledger._lock, _wal_lock(self.ledger.lock_path, 30.0):
            rows = self.ledger._load_unlocked()
            if len(rows) > 100000 or len({row.resource_id for row in rows}) != len(rows):
                raise ValueError('cleanup ledger inventory is oversized or ambiguous')
            records = {row.resource_id: row for row in rows}
            current = records[resource_id]
            def publish(updated):
                records[resource_id] = updated
                self.ledger._write_unlocked(tuple(records[key] for key in sorted(records)))
                return updated
            allowed, blockers = self.reclamation_gate(current, records=tuple(records.values()))
            errors = list(blockers)
            if current.path != record.path or current.allowed_cleanup_root != record.allowed_cleanup_root:
                errors.append('registered cleanup scope changed during inventory')
            now_identity = self._path_identity(target) if allowed else None
            if allowed and now_identity != identity:
                errors.append('cleanup target generation changed during inventory')
            if allowed and now_identity is not None and (
                current.path_identity is None or tuple(current.path_identity) != now_identity):
                errors.append('cleanup target differs from its registered generation')
            if allowed and inventory['links'] and not self.nested_links_are_internal(target):
                errors.append('nested link or reparse point escapes the cleanup root or is ambiguous')
            if errors:
                receipt = self._cleanup_receipt(current, tuple(records.values()), reason=reason,
                    started=started, inventory=inventory, errors=errors, apply=True)
                self._write_receipt(receipt)
                return receipt
            operation = current.cleanup_intent
            if operation is not None:
                self._validate_cleanup_intent(operation, current)
                retained = self._cleanup_effects.get(resource_id)
                if retained is not None and retained.get('cleanup_id') == operation.get('cleanup_id'):
                    self._validate_cleanup_intent(retained, current)
                    operation = retained
                inventory = operation['inventory']
                started = operation['started']
            else:
                if len(self._cleanup_effects) >= 64:
                    raise ValueError('retained cleanup effects exceed recovery batch bound')
                operation = {'schema_version': 'px.cleanup-intent/1.0',
                    'cleanup_id': f"cleanup-{uuid4().hex}", 'resource_id': resource_id,
                    'path': current.path, 'path_identity': identity,
                    'phase': 'effect_pending', 'started': started, 'reason': reason,
                    'inventory': inventory, 'initially_absent': identity is None}
                self._validate_cleanup_intent(operation, current)
                current = publish(replace(current, cleanup_intent=operation,
                    status=ResourceStatus.CLEANUP_PENDING.value))
            if operation['phase'] == 'effect_pending':
                if self._path_identity(target) != identity:
                    raise ValueError('cleanup target changed before effect')
                if identity is None and not operation['initially_absent']:
                    raise ValueError('retained cleanup effect is ambiguous after restart')
                try:
                    if identity is not None:
                        _remove_owned_target(target)
                    if os.path.lexists(target):
                        raise OSError('target remains after reclamation')
                except OSError as error:
                    try:
                        publish(replace(current, status=ResourceStatus.CLEANUP_FAILED.value,
                            cleanup_result='failed', retained_reason=str(error)))
                        receipt = self._cleanup_receipt(current, tuple(records.values()), reason=reason,
                            started=started, inventory=inventory, errors=(str(error),), apply=True)
                        receipt = replace(receipt, resources_failed=1, resources_skipped=0)
                        self._write_receipt(receipt)
                    except BaseException as secondary:
                        try:
                            error.add_note('cleanup publication failed: ' + type(secondary).__name__ + ': ' + str(secondary))
                        except BaseException:
                            pass
                        raise error from secondary
                    return receipt
                receipt = self._cleanup_receipt(current, tuple(records.values()),
                    reason=operation['reason'], started=started, inventory=inventory,
                    reclaimed=True, apply=True, cleanup_id=operation['cleanup_id'])
                operation = {**operation, 'phase': 'effect_complete', 'receipt': asdict(receipt)}
                # Keep exact in-process effect proof even if the next durable
                # update fails. Restart without that proof remains conservative.
                self._cleanup_effects[resource_id] = operation
            else:
                if os.path.lexists(target):
                    raise ValueError('cleanup target reappeared after completed effect')
                receipt = CleanupReceipt(**operation['receipt'])
            current = publish(replace(current, cleanup_intent=operation,
                status=ResourceStatus.CLEANUP_PENDING.value,
                cleanup_result='effect_complete_pending_receipt'))
            self._write_receipt(receipt)
            publish(replace(current, cleanup_intent=None, cleanup_receipt_id=receipt.cleanup_id,
                status=ResourceStatus.RECLAIMED.value, retained_reason=None,
                cleanup_result='already_absent' if operation['initially_absent'] else 'reclaimed',
                files=inventory['files'], directories=inventory['directories'], bytes=inventory['bytes']))
            self._cleanup_effects.pop(resource_id, None)
            return receipt


    def _write_receipt(self, receipt: CleanupReceipt) -> Path:
        if type(receipt.cleanup_id) is not str or re.fullmatch(r'cleanup-[0-9a-f]{32}', receipt.cleanup_id) is None:
            raise ValueError('cleanup receipt ID is not canonical')
        self.receipt_dir.mkdir(parents=True, exist_ok=True)
        path = self.receipt_dir / f"{receipt.cleanup_id}.json"
        payload = (json.dumps(asdict(receipt), indent=2) + '\n').encode('utf-8')
        if path.exists():
            if _bounded_image(path, limit=1024 * 1024) != payload:
                raise ValueError('cleanup receipt identity already has different content')
            return path
        _atomic_replace(path, payload, label='cleanup:receipt', fault_injector=None)
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
        ownership: str = "direct",
        parent_resource_id: str | None = None,
        creation_outcome: dict | None = None,
    ) -> tuple[ResourceRecord, subprocess.Popen[object]]:
        if creation_outcome is not None:
            if type(creation_outcome) is not dict:
                raise TypeError('creation outcome must be a plain dictionary')
            creation_outcome.clear()
            creation_outcome.update(created=False, tree_closed=True, custody_retained=False)
        if start_suspended and os.name != "nt":
            raise ValueError("suspended process creation is Windows-only")
        if ownership not in {"direct", "supervised", "durable"}:
            raise ValueError("unsupported process ownership mode")
        if not isinstance(command, (list, tuple)) or not command or len(command) > 4096:
            raise ValueError("process command must be a bounded argv sequence")
        if any(type(item) is not str or '\0' in item or len(item) > 32766 for item in command):
            raise ValueError("invalid process command argument")
        if not command[0] or sum(len(item) + 1 for item in command) > 32767:
            raise ValueError("process command exceeds its aggregate bound")
        if parent_resource_id is not None:
            parent = self.ledger.get(parent_resource_id)
            if (parent.resource_type != 'path' or not parent.active
                    or parent.project_id != project_id or parent.run_id != run_id):
                raise ValueError('process workspace custody does not match its run')
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        if start_suspended:
            creationflags |= 0x00000004  # Windows CREATE_SUSPENDED
        now = _utc_now()
        intent = hashlib.sha256(json.dumps(
            [list(command), str(cwd), project_id, run_id, lane_id, creator, ownership],
            ensure_ascii=True, separators=(',', ':')).encode()).hexdigest()
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
            expected_cleanup_event=f"{ownership}_process_exit_or_cancel",
            retention_required=False,
            process_identity=f"creation-intent:{intent}",
            cleanup_result="creation_pending",
            parent_resource_id=parent_resource_id,
        )
        # No native creation occurs until the recoverable intent exists.
        self.ledger.upsert(record)
        resource_id = record.resource_id
        if creation_outcome is not None:
            creation_outcome.update(resource_id=resource_id, tree_closed=False, custody_retained=True)

        def register_created(process):
            nonlocal record
            self._processes[resource_id] = process
            if creation_outcome is not None:
                creation_outcome['created'] = True
            fingerprint = _process_start_fingerprint(process.pid)
            identity = f"process-start:{fingerprint}" if fingerprint is not None else f"owned-handle:{resource_id}"
            record = replace(record, pid=process.pid, process_identity=identity,
                             cleanup_result="created_registered")
            self.ledger.upsert(record)

        try:
            arguments = dict(cwd=cwd, env=dict(environment) if environment is not None else None,
                             stdout=stdout, stderr=stderr, text=text, shell=False,
                             close_fds=True, start_new_session=os.name != "nt", creationflags=creationflags)
            if ownership == "supervised" and os.name == "nt":
                from .process_supervisor import _WindowsContainedPopen, _WindowsJob
                job = _WindowsJob(custody_owner=lambda owner: self._process_jobs.__setitem__(resource_id, owner))
                process = _WindowsContainedPopen(
                    list(command), creation_job=job, creation_hook=register_created,
                    custody_owner=lambda owner: self._failed_creation_custody.__setitem__(resource_id, owner),
                    **arguments)
            else:
                process = subprocess.Popen(list(command), **arguments)
                register_created(process)
            self._failed_creation_custody.pop(resource_id, None)
            return record, process
        except BaseException as error:
            process = self._processes.get(resource_id)
            job = self._process_jobs.get(resource_id)
            created = process is not None or bool(getattr(self._failed_creation_custody.get(resource_id), '_px_created', False))
            closed = process is None and job is None
            cleanup_errors = []
            try:
                if job is not None:
                    if job.handle:
                        job.terminate()
                        closed = job.wait_closed(5.0, 0.02)
                    else:
                        owner = self._failed_creation_custody.get(resource_id)
                        closed = not created or bool(getattr(owner, '_px_tree_closed', False))
                elif process is not None:
                    if process.poll() is None:
                        if os.name == 'nt':
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)
                    # A direct root exit cannot establish descendant closure.
                    closed = False
                if process is not None and closed:
                    process.wait(timeout=5)
                    self._close_process_handles(process)
                owner = self._failed_creation_custody.get(resource_id)
                if owner is not None:
                    owner.close_retained_creation_handles()
                if job is not None and closed:
                    job.close()
            except BaseException as cleanup_error:
                cleanup_errors.append(type(cleanup_error).__name__)
            if job is not None:
                job._verified_closed = closed
            settled = closed and not cleanup_errors
            try:
                self.ledger.upsert(replace(record, active=not settled,
                    status=ResourceStatus.RECLAIMED.value if settled else ResourceStatus.CLEANUP_FAILED.value,
                    run_state=RunState.FAILED.value, cleanup_result='creation_failed_closed' if settled else 'creation_failed_custody_retained',
                    retained_reason=None if settled else 'creation or physical cleanup remains unresolved'))
            except BaseException as publication_error:
                cleanup_errors.append(type(publication_error).__name__)
            if settled and not cleanup_errors:
                self._processes.pop(resource_id, None)
                self._process_jobs.pop(resource_id, None)
                self._failed_creation_custody.pop(resource_id, None)
            outcome = {'resource_id': resource_id,
                    'created': created,
                    'tree_closed': closed, 'cleanup_errors': cleanup_errors,
                    'custody_retained': bool(cleanup_errors) or not settled}
            if creation_outcome is not None:
                creation_outcome.update(outcome)
            try:
                error.resource_creation_outcome = outcome
            except BaseException:
                pass
            raise

    @staticmethod
    def _close_process_handles(process):
        errors = []
        operations = [stream.close for stream in (getattr(process, name, None) for name in ('stdout', 'stderr', 'stdin'))
                      if stream is not None and not stream.closed]
        if hasattr(process, 'close_retained_creation_handles'):
            operations.append(process.close_retained_creation_handles)
        elif os.name == 'nt' and hasattr(process, '_handle'):
            operations.append(process._handle.Close)
        for operation in operations:
            try:
                operation()
            except BaseException as error:
                errors.append(error)
        if errors:
            raise errors[0]

    def settle_failed_launch(self, resource_id, original):
        """Attempt physical settlement independently of outcome publication."""
        job = self._process_jobs.get(resource_id)
        process = self._processes.get(resource_id)
        errors = []
        tree_closed = bool(job is not None and getattr(job, '_verified_closed', False))
        if job is not None and job.handle:
            try:
                job.terminate()
                tree_closed = job.wait_closed(5.0, 0.02)
                job._verified_closed = tree_closed
            except BaseException as error:
                errors.append(type(error).__name__)
        if process is not None:
            # Retained native custody remains usable when ledger reads fail.
            # This proves only root closure for a durable/direct launch.
            try:
                if process.poll() is None:
                    if os.name == 'nt':
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5.0)
            except BaseException as error:
                errors.append(type(error).__name__)
            try:
                self.terminate_owned_process(resource_id)
            except BaseException as error:
                errors.append(type(error).__name__)
        outcome = {'resource_id': resource_id, 'tree_closed': tree_closed,
                   'root_closed': process is not None and process.returncode is not None,
                   'cleanup_errors': errors, 'custody_retained': resource_id in self._processes or resource_id in self._process_jobs}
        try:
            outcomes = getattr(original, 'launch_settlement', [])
            original.launch_settlement = [*outcomes, outcome]
        except BaseException:
            pass
        return outcome

    def complete_process(self, resource_id: str, *, deadline: float | None = None) -> ResourceRecord:
        if deadline is not None:
            from .numeric_inputs import finite_number
            deadline = finite_number(deadline, 'completion deadline', minimum=0)
            if deadline <= 0:
                raise ValueError('completion deadline must be positive')
        process = self._processes.get(resource_id)
        if process is None or process.poll() is None:
            raise ValueError("owned process has not exited")
        job = self._process_jobs.get(resource_id)
        if job is not None:
            if job.handle:
                if job.active_processes() > 0:
                    job.terminate()
                job._verified_closed = job.wait_closed(
                    5.0 if deadline is None else min(5.0, max(0.0, deadline - time.monotonic())), 0.02)
            if not getattr(job, '_verified_closed', False):
                raise RuntimeError('owned process tree has not closed')
        self._close_process_handles(process)
        if job is not None:
            job.close()
        result = self.update(
            resource_id,
            active=False,
            run_state=RunState.COMPLETED.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result=f"exit_{process.returncode}",
        )
        self._processes.pop(resource_id, None)
        self._process_jobs.pop(resource_id, None)
        return result

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

    def rebind_current_process(
        self,
        resource_id: str,
        *,
        expected_launcher_pid: int,
        expected_run_id: str,
        expected_lane_id: str,
        expected_creator: str,
        launch_binding: str,
    ) -> ResourceRecord:
        """Transfer a registered launcher identity to its actual interpreter.

        Windows virtual-environment redirectors may create the registered
        process and then hand execution to a second PID.  The child may accept
        that handoff only for its exact active resource and launch binding.
        """
        actual_pid = os.getpid()
        if expected_launcher_pid <= 0 or not launch_binding:
            raise PermissionError("process launch handoff binding is incomplete")
        return self.ledger.rebind_active_process(
            resource_id,
            expected_launcher_pid=expected_launcher_pid,
            actual_pid=actual_pid,
            expected_run_id=expected_run_id,
            expected_lane_id=expected_lane_id,
            expected_creator=expected_creator,
            launch_binding=launch_binding,
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
        if self._persisted_process_is_alive(record, expected_pid=expected_pid):
            raise ValueError("persisted process is still alive")
        return self.update(
            resource_id,
            active=False,
            run_state=run_state.value,
            status=ResourceStatus.RECLAIMED.value,
            cleanup_result="process_absence_verified",
        )

    def persisted_process_has_exited(
        self, resource_id: str, *, expected_pid: int
    ) -> bool:
        """Verify one exact persisted process identity without mutating custody."""
        record = self.ledger.get(resource_id)
        if record.resource_type != "process" or record.pid != expected_pid:
            raise PermissionError("persisted process identity does not match")
        if not record.active:
            return record.status == ResourceStatus.RECLAIMED.value
        return not self._persisted_process_is_alive(
            record, expected_pid=expected_pid
        )

    @staticmethod
    def _persisted_process_is_alive(
        record: ResourceRecord, *, expected_pid: int
    ) -> bool:
        """Reject PID reuse when durable custody has a kernel start binding."""
        if not _process_exists(expected_pid):
            return False
        prefix = "process-start:"
        identity = str(record.process_identity or "")
        if not identity.startswith(prefix):
            return True
        current = _process_start_fingerprint(expected_pid)
        # An unavailable fingerprint proves neither exit nor reuse.
        return current is None or current == identity[len(prefix) :]

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
        elif resource_id in self._process_jobs:
            job = self._process_jobs[resource_id]
            try:
                if job.handle:
                    job.terminate()
                    job._verified_closed = job.wait_closed(5.0, 0.02)
                if not getattr(job, '_verified_closed', False):
                    raise RuntimeError('owned Job tree closure is not proven')
                process.wait(timeout=5.0)
                self._close_process_handles(process)
                job.close()
                reaped = 1
            except BaseException as error:
                errors.append(type(error).__name__)
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
            self._close_process_handles(process)
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
        if reaped:
            self._processes.pop(resource_id, None)
            self._process_jobs.pop(resource_id, None)
        return receipt

    def retire_proven_absent_process(
        self, resource_id: str, *, apply: bool
    ) -> CleanupReceipt:
        """Close persisted process custody only when the recorded PID is dead."""

        observed = None if apply else self.ledger.observe()
        if observed is None:
            record = self.ledger.get(resource_id)
        else:
            matches = [item for item in observed if item.resource_id == resource_id]
            if not matches:
                raise KeyError(resource_id)
            record = matches[0]
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
                for item in (self.ledger.load() if observed is None else observed)
            ),
            dry_run=not apply,
        )
        if apply:
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
        records = self.ledger.observe()
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

    def _write_custody_recovery_receipt(self, resource_id, context):
        """Retain physical recovery evidence before releasing in-memory custody."""
        now = _utc_now()
        receipt = CleanupReceipt(
            cleanup_id=f'cleanup-{uuid4().hex}', project_id=context['project_id'],
            run_id=context['run_id'], lane_id=context['lane_id'], start_time=now, end_time=now,
            reason=f'retained_custody_recovered:{resource_id}', validated_roots=(), workers=1,
            priority_mode='exact_retained_handles', resources_considered=1,
            resources_reclaimed=1, resources_skipped=0, resources_failed=0,
            files_removed=0, directories_removed=0, bytes_reclaimed=0,
            retained_artifacts=(), promoted_artifacts=(), links_encountered=0,
            orphan_processes_reaped=0, errors=(),
            remaining_owned_ephemeral_resources=sum(
                item.classification == ResourceClassification.EPHEMERAL.value
                and item.status != ResourceStatus.RECLAIMED.value for item in self.ledger.observe()),
            dry_run=False)
        self._write_receipt(receipt)
        return receipt.cleanup_id

    def reconcile_retained_custody(self, *, apply: bool = False) -> dict[str, object]:
        """Retry retained in-process owners; never reconstruct handles from PIDs."""
        if type(apply) is not bool:
            raise ValueError('recovery apply must be an actual boolean')
        if len(self._pending_creation_ids()) + len(self._supervision_failures) > 64:
            raise ValueError('retained custody exceeds bounded recovery batch')
        pending = sorted(self._pending_creation_ids() | set(self._supervision_failures))
        if not apply:
            return {'valid': not pending, 'dry_run': True, 'pending': pending, 'outcomes': []}
        outcomes = []
        deadline = time.monotonic() + 60.0
        for resource_id in sorted(self._pending_creation_ids()):
            if time.monotonic() >= deadline:
                break
            owner = self._failed_creation_custody.get(resource_id)
            job = self._process_jobs.get(resource_id)
            errors = []
            closed = bool(job is not None and getattr(job, '_verified_closed', False))
            try:
                if job is not None and job.handle:
                    if job.active_processes():
                        job.terminate()
                    closed = job.wait_closed(min(5.0, max(0.0, deadline - time.monotonic())), 0.02)
                    job._verified_closed = closed
                else:
                    closed = closed or bool(getattr(owner, '_px_tree_closed', False))
                if not closed:
                    raise RuntimeError('creation tree closure remains unresolved')
                if owner is not None:
                    owner._px_tree_closed = closed
                process = self._processes.get(resource_id) or owner
                if process is not None:
                    if getattr(process, '_child_created', False) and not getattr(getattr(process, '_handle', None), 'closed', False):
                        process.wait(timeout=min(5.0, max(0.0, deadline - time.monotonic())))
                    self._close_process_handles(process)
                if job is not None:
                    job.close()
                record = self.update(resource_id, active=False, run_state=RunState.FAILED.value,
                    status=ResourceStatus.RECLAIMED.value, cleanup_result='creation_failure_recovered', retained_reason=None)
                self._write_custody_recovery_receipt(resource_id, asdict(record))
                self._failed_creation_custody.pop(resource_id, None)
                self._processes.pop(resource_id, None)
                self._process_jobs.pop(resource_id, None)
                for custody in self._supervision_failures.values():
                    creation = custody.get('creation', {})
                    if creation.get('resource_id') == resource_id:
                        creation.update(tree_closed=True, custody_retained=False, cleanup_errors=[])
            except BaseException as error:
                errors.append(type(error).__name__)
            outcomes.append({'resource_id': resource_id, 'tree_closed': closed, 'errors': errors})
        from .process_supervisor import ProcessSupervisor
        supervisor = ProcessSupervisor(self)
        seen_custodies = set()
        for key, custody in list(self._supervision_failures.items()):
            if time.monotonic() >= deadline:
                break
            if id(custody) in seen_custodies:
                continue
            seen_custodies.add(id(custody))
            error = RuntimeError('retained supervision recovery')
            supervisor._settle_failed_supervision(custody, error, deadline=deadline)
            outcome = dict(custody.get('settlement', {'custody_retained': True}))
            try:
                liveness = custody.get('liveness')
                if liveness is not None:
                    liveness.close()
            except BaseException as close_error:
                outcome['custody_retained'] = True
                outcome['cleanup_errors'] = [*outcome.get('cleanup_errors', []), type(close_error).__name__]
            if not outcome['custody_retained']:
                try:
                    self._write_custody_recovery_receipt(key, custody)
                except BaseException as receipt_error:
                    outcome['custody_retained'] = True
                    outcome['cleanup_errors'] = [*outcome.get('cleanup_errors', []), type(receipt_error).__name__]
                else:
                    for alias, value in list(self._supervision_failures.items()):
                        if value is custody:
                            self._supervision_failures.pop(alias)
            outcomes.append({'resource_id': key, **outcome})
        pending = sorted(self._pending_creation_ids() | set(self._supervision_failures))
        return {'valid': not pending, 'dry_run': False, 'pending': pending, 'outcomes': outcomes}

    def reconcile(self, *, apply: bool = False) -> dict[str, object]:
        custody = self.reconcile_retained_custody(apply=apply)
        pending_custody = self._pending_custody_resource_ids()
        receipts: list[CleanupReceipt] = []
        retained: list[dict[str, object]] = []
        abandoned_owners: set[tuple[str, str, str]] = set()
        for record in (self.ledger.load() if apply else self.ledger.observe()):
            if record.resource_id in pending_custody:
                retained.append({'resource_id': record.resource_id,
                                 'reason': 'exact native custody or its recovery acknowledgement remains unresolved'})
                continue
            if record.resource_type == "process" and record.active:
                if record.resource_id in self._processes:
                    if apply:
                        receipts.append(self.terminate_owned_process(record.resource_id))
                    else:
                        retained.append({'resource_id': record.resource_id,
                                         'reason': 'owned process retained during read-only reconciliation'})
                elif record.pid is not None and not _process_exists(record.pid):
                    receipt = self.retire_proven_absent_process(
                        record.resource_id, apply=apply
                    )
                    receipts.append(receipt)
                    if apply and receipt.resources_reclaimed == 1:
                        abandoned_owners.add(
                            (record.project_id, record.run_id, record.lane_id)
                        )
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
                ResourceStatus.CLEANUP_PENDING.value,
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
        if apply and abandoned_owners:
            current = self.ledger.load()
            live_process_owners = {
                (item.project_id, item.run_id, item.lane_id)
                for item in current
                if item.resource_type == "process" and item.active
            }
            for record in current:
                owner = (record.project_id, record.run_id, record.lane_id)
                if (
                    record.resource_type != "path"
                    or not record.active
                    or owner not in abandoned_owners
                    or owner in live_process_owners
                    or record.classification
                    != ResourceClassification.EPHEMERAL.value
                    or record.retention_required
                ):
                    continue
                self.update(
                    record.resource_id,
                    active=False,
                    run_state=RunState.ABANDONED.value,
                    status=ResourceStatus.RECLAIMABLE.value,
                )
                receipt = self.reclaim(
                    record.resource_id,
                    reason="abrupt_owner_absence_reconciliation",
                    apply=True,
                )
                receipts.append(receipt)
                if receipt.resources_reclaimed == 0:
                    retained.append(
                        {
                            "resource_id": record.resource_id,
                            "reason": "; ".join(receipt.errors)
                            or "abandoned owned path was not reclaimed",
                        }
                    )
        final = self.ledger.load() if apply else self.ledger.observe()
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
        cleanup_pending = sum(item.cleanup_intent is not None for item in final)
        return {
            "valid": active_processes == 0
            and unexplained == 0
            and cleanup_failures == 0 and cleanup_pending == 0 and custody['valid'],
            "dry_run": not apply,
            "owned_child_processes_active": active_processes,
            "owned_ephemeral_unexplained": unexplained,
            "cleanup_failures": cleanup_failures,
            "cleanup_pending": cleanup_pending,
            "receipts": [asdict(item) for item in receipts],
            "retained": retained,
            "retained_custody": custody,
            "resource_ledger_reconciled": active_processes == 0 and unexplained == 0 and cleanup_pending == 0 and custody['valid'],
        }


def _resource_records_from_image(raw: bytes | None) -> tuple[ResourceRecord, ...]:
    if raw is None:
        return ()
    payload = decode_json_object(raw, max_bytes=64 * 1024 * 1024)
    rows = payload.get('resources')
    if payload.get('schema_version') != '1.0' or type(rows) is not list or len(rows) > 100_000:
        raise ValueError('invalid bounded resource ledger image')
    records = []
    ids = set()
    for row in rows:
        if type(row) is not dict:
            raise ValueError('invalid resource ledger record')
        item = ResourceRecord(**row)
        if type(item.active) is not bool or item.resource_type not in {'path', 'process'} or item.resource_id in ids:
            raise ValueError('invalid resource identity or activity')
        ids.add(item.resource_id)
        records.append(item)
    return tuple(records)


def resource_status_from_image(raw: bytes | None) -> dict[str, object]:
    """Evaluate one captured ledger image without locks or filesystem effects."""
    return _resource_status_records(_resource_records_from_image(raw))


def _resource_status_records(records) -> dict[str, object]:
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
        "active_paths": sum(
            item.resource_type == "path" and item.active for item in records
        ),
        "reclaimable_paths": sum(
            item.resource_type == "path"
            # Existing closure consumers require this count to be zero. A
            # pending acknowledgment still requires cleanup reconciliation.
            and (item.status in {ResourceStatus.RECLAIMABLE.value, ResourceStatus.CLEANUP_PENDING.value}
                 or item.cleanup_intent is not None)
            for item in records
        ),
        "cleanup_pending": sum(item.cleanup_intent is not None for item in records),
        "cleanup_failures": sum(
            item.status == ResourceStatus.CLEANUP_FAILED.value for item in records
        ),
    }
    return output


def resource_status(
    ledger_path: Path, *, storage_path: Path | None = None
) -> dict[str, object]:
    manager = ResourceManager(ledger_path)
    output = _resource_status_records(manager.ledger.observe())
    if storage_path is not None:
        output['storage'] = manager.storage_status(storage_path)
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
        if type(max_records) is not int or max_records < 1 or max_records > 100_000:
            raise ValueError("max_records must be between 1 and 100000")
        raw = self.wal.read_source_image(history_path)
        path = history_path.resolve(strict=True)
        if (
            not path.is_file()
            or path.is_symlink()
            or not _inside(path, self.allowed_root)
        ):
            raise ValueError("operational history is outside bounded custody")
        try:
            if raw is None:
                raise ValueError('operational history is absent')
            value = decode_json_object(raw, max_bytes=64 * 1024 * 1024)
        except (OSError, UnicodeError, ValueError) as error:
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
            expected_before={
                path.relative_to(self.allowed_root).as_posix(): before_sha256,
                anchor_path.relative_to(self.allowed_root).as_posix(): None,
                receipt_path.relative_to(self.allowed_root).as_posix(): None,
            },
        )
        return {**receipt, "transaction": transaction}
