"""Crash-consistent, bounded transactions over related JSON artifacts.

The transaction protocol stages exact before-images and canonical after-images,
publishes a hash-sealed write-ahead manifest, and only then replaces targets.
Recovery rolls back transactions that never published a manifest and rolls every
published transaction forward.  A target whose bytes match neither image is an
external-write conflict and fails closed rather than being silently overwritten.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable, Iterable, Mapping
import uuid

from .file_lock import FileLock


SCHEMA_VERSION = "1.0"
RECOVERY_POLICY = "rollback-before-manifest-roll-forward-after-manifest"
ARTIFACT_ROLES = frozenset({"state", "event", "receipt", "handoff", "projection"})
MAX_ARTIFACTS = 128
MAX_TRANSACTION_BYTES = 64 * 1024 * 1024
MAX_PENDING_TRANSACTIONS = 128
MAX_INSPECTION_FILES = 4096
MAX_INSPECTION_BYTES = 256 * 1024 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class WalIntegrityError(RuntimeError):
    """Raised when a journal or target cannot be reconciled without data loss."""


@dataclass(frozen=True)
class JsonArtifact:
    """One JSON value and its semantic role in a coordinated transaction."""

    role: str
    path: Path
    value: object


FaultInjector = Callable[[str], None]


@dataclass(frozen=True)
class JsonTransition:
    """Decoded before/after values exposed to a fail-closed pre-commit guard."""

    role: str
    path: Path
    before: object | None
    after: object


PreCommitValidator = Callable[[tuple[JsonTransition, ...]], None]


def _canonical(value: object) -> bytes:
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


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    _fsync_directory(path.parent)


def _atomic_replace(
    path: Path,
    payload: bytes,
    *,
    label: str,
    fault_injector: FaultInjector | None,
    prepared_path: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = prepared_path or path.with_name(
        f".{path.name}.{uuid.uuid4().hex}.prepared"
    )
    if temporary.exists():
        if not temporary.is_file() or temporary.read_bytes() != payload:
            raise WalIntegrityError(f"conflicting prepared image: {temporary}")
    else:
        _write_new(temporary, payload)
        if fault_injector is not None:
            fault_injector(f"{label}:staged")
    os.replace(temporary, path)
    _fsync_directory(path.parent)
    if fault_injector is not None:
        fault_injector(f"{label}:published")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sealed_manifest(value: Mapping[str, object]) -> dict[str, object]:
    manifest = dict(value)
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = _sha_bytes(_canonical(manifest))
    return manifest


def _validate_manifest(value: object, transaction_id: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise WalIntegrityError(f"{transaction_id}: manifest is not an object")
    manifest = dict(value)
    expected = manifest.get("manifest_sha256")
    if not isinstance(expected, str) or _sealed_manifest(manifest) != manifest:
        raise WalIntegrityError(f"{transaction_id}: manifest digest mismatch")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise WalIntegrityError(f"{transaction_id}: unsupported manifest schema")
    if manifest.get("transaction_id") != transaction_id:
        raise WalIntegrityError(f"{transaction_id}: manifest identity mismatch")
    if manifest.get("recovery_policy") != RECOVERY_POLICY:
        raise WalIntegrityError(f"{transaction_id}: unsupported recovery policy")
    if manifest.get("phase") not in {"prepared", "applying", "committed"}:
        raise WalIntegrityError(f"{transaction_id}: invalid transaction phase")
    if set(manifest) != {
        "schema_version",
        "transaction_id",
        "recovery_policy",
        "intent_sha256",
        "phase",
        "artifacts",
        "manifest_sha256",
    }:
        raise WalIntegrityError(f"{transaction_id}: manifest fields are not exact")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not 1 <= len(artifacts) <= MAX_ARTIFACTS:
        raise WalIntegrityError(f"{transaction_id}: invalid artifact inventory")
    intents: list[dict[str, str]] = []
    for index, record in enumerate(artifacts):
        if not isinstance(record, Mapping) or set(record) != {
            "index",
            "role",
            "path",
            "before",
            "after",
        }:
            raise WalIntegrityError(f"{transaction_id}: artifact fields are not exact")
        before = record.get("before")
        after = record.get("after")
        role = record.get("role")
        path = record.get("path")
        if (
            record.get("index") != index
            or role not in ARTIFACT_ROLES
            or not isinstance(path, str)
            or not path
            or not isinstance(before, Mapping)
            or set(before) != {"exists", "sha256", "stage"}
            or not isinstance(after, Mapping)
            or set(after) != {"sha256", "stage"}
            or not re.fullmatch(r"[0-9a-f]{64}", str(after.get("sha256", "")))
            or not isinstance(after.get("stage"), str)
        ):
            raise WalIntegrityError(f"{transaction_id}: invalid artifact record")
        before_exists = before.get("exists")
        if not isinstance(before_exists, bool) or (
            before_exists is True
            and (
                not re.fullmatch(r"[0-9a-f]{64}", str(before.get("sha256", "")))
                or not isinstance(before.get("stage"), str)
            )
        ):
            raise WalIntegrityError(f"{transaction_id}: invalid before-image record")
        if before_exists is False and (
            before.get("sha256") is not None or before.get("stage") is not None
        ):
            raise WalIntegrityError(f"{transaction_id}: invalid absent before-image")
        intents.append(
            {"role": str(role), "path": path, "sha256": str(after["sha256"])}
        )
    if manifest.get("intent_sha256") != _sha_bytes(_canonical(intents)):
        raise WalIntegrityError(f"{transaction_id}: intent digest mismatch")
    return manifest


def planned_write_boundaries(artifacts: Iterable[JsonArtifact]) -> tuple[str, ...]:
    """Return every durable boundary a commit will expose to fault injection."""
    items = tuple(artifacts)
    boundaries: list[str] = []
    for index, artifact in enumerate(items):
        if artifact.path.is_file():
            boundaries.append(f"journal:before:{index}")
        boundaries.append(f"journal:after:{index}")
    boundaries.extend(("manifest:prepared:staged", "manifest:prepared:published"))
    boundaries.extend(("manifest:applying:staged", "manifest:applying:published"))
    for index in range(len(items)):
        boundaries.extend((f"target:{index}:staged", f"target:{index}:published"))
    boundaries.extend(("manifest:committed:staged", "manifest:committed:published"))
    boundaries.append("journal:committed:published")
    return tuple(boundaries)


class JsonWal:
    """Coordinate JSON state, event, receipt, handoff, and projection writes."""

    def __init__(
        self,
        journal_root: Path,
        allowed_root: Path,
        *,
        lock_timeout_seconds: float = 10.0,
        precommit_validator: PreCommitValidator | None = None,
    ) -> None:
        self.allowed_root = allowed_root.resolve()
        self.journal_root = journal_root.resolve()
        if not self.allowed_root.is_dir():
            raise ValueError("allowed root must be an existing directory")
        if not _inside(self.journal_root, self.allowed_root):
            raise ValueError("journal root must be inside the allowed root")
        self.lock_timeout_seconds = lock_timeout_seconds
        self.precommit_validator = precommit_validator

    @property
    def _lock_path(self) -> Path:
        return self.journal_root / ".wal.lock"

    @property
    def _transactions_root(self) -> Path:
        return self.journal_root / "transactions"

    @property
    def _rolled_back_root(self) -> Path:
        return self.journal_root / "rolled-back"

    @property
    def _committed_root(self) -> Path:
        return self.journal_root / "committed"

    def _normalize(
        self, artifacts: Iterable[JsonArtifact]
    ) -> tuple[tuple[JsonArtifact, Path, bytes], ...]:
        items = tuple(artifacts)
        if not 1 <= len(items) <= MAX_ARTIFACTS:
            raise ValueError(f"transaction must contain 1..{MAX_ARTIFACTS} artifacts")
        normalized: list[tuple[JsonArtifact, Path, bytes]] = []
        targets: set[Path] = set()
        total = 0
        for artifact in items:
            if artifact.role not in ARTIFACT_ROLES:
                raise ValueError(f"unsupported JSON artifact role: {artifact.role}")
            target = artifact.path.resolve()
            if not _inside(target, self.allowed_root):
                raise ValueError(f"artifact escapes allowed root: {artifact.path}")
            if _inside(target, self.journal_root):
                raise ValueError("transaction targets cannot be inside the WAL journal")
            if target in targets:
                raise ValueError(f"duplicate transaction target: {target}")
            targets.add(target)
            try:
                rendered = _canonical(artifact.value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"artifact is not strict JSON: {target}") from error
            total += len(rendered)
            if total > MAX_TRANSACTION_BYTES:
                raise ValueError("transaction payload exceeds the bounded byte limit")
            normalized.append((artifact, target, rendered))
        return tuple(normalized)

    def _read_existing(self, path: Path) -> bytes | None:
        if not path.exists():
            return None
        if not path.is_file():
            raise WalIntegrityError(f"JSON target is not a regular file: {path}")
        raw = path.read_bytes()
        try:
            json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise WalIntegrityError(
                f"existing JSON target is invalid: {path}"
            ) from error
        return raw

    def _write_manifest(
        self,
        transaction: Path,
        manifest: Mapping[str, object],
        phase: str,
        fault_injector: FaultInjector | None,
    ) -> dict[str, object]:
        updated = _sealed_manifest({**manifest, "phase": phase})
        _atomic_replace(
            transaction / "manifest.json",
            _canonical(updated),
            label=f"manifest:{phase}",
            fault_injector=fault_injector,
        )
        return updated

    def _load_manifest(self, transaction: Path) -> dict[str, object] | None:
        path = transaction / "manifest.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise WalIntegrityError(
                f"{transaction.name}: manifest is unreadable"
            ) from error
        return _validate_manifest(value, transaction.name)

    def _artifact_paths(
        self, transaction: Path, record: Mapping[str, object]
    ) -> tuple[Path, Path, Path | None, str, str | None]:
        try:
            relative = Path(str(record["path"]))
            target = (self.allowed_root / relative).resolve()
            after_record = record["after"]
            before_record = record["before"]
            if not isinstance(after_record, Mapping) or not isinstance(
                before_record, Mapping
            ):
                raise ValueError
            after = (transaction / str(after_record["stage"])).resolve()
            before = (
                (transaction / str(before_record["stage"])).resolve()
                if before_record.get("exists") is True
                else None
            )
            after_sha = str(after_record["sha256"])
            before_sha = (
                str(before_record["sha256"])
                if before_record.get("exists") is True
                else None
            )
        except (KeyError, TypeError, ValueError) as error:
            raise WalIntegrityError(
                f"{transaction.name}: malformed artifact record"
            ) from error
        if (
            relative.is_absolute()
            or not _inside(target, self.allowed_root)
            or _inside(target, self.journal_root)
            or not _inside(after, transaction)
            or (before is not None and not _inside(before, transaction))
            or not after.is_file()
        ):
            raise WalIntegrityError(
                f"{transaction.name}: artifact path escapes custody"
            )
        if _sha_bytes(after.read_bytes()) != after_sha:
            raise WalIntegrityError(f"{transaction.name}: staged after-image mismatch")
        if before is not None and (
            not before.is_file() or _sha_bytes(before.read_bytes()) != before_sha
        ):
            raise WalIntegrityError(f"{transaction.name}: staged before-image mismatch")
        return target, after, before, after_sha, before_sha

    def _apply(
        self,
        transaction: Path,
        manifest: Mapping[str, object],
        fault_injector: FaultInjector | None = None,
    ) -> None:
        artifacts = manifest["artifacts"]
        assert isinstance(artifacts, list)
        seen: set[Path] = set()
        for index, raw_record in enumerate(artifacts):
            if not isinstance(raw_record, Mapping):
                raise WalIntegrityError(
                    f"{transaction.name}: artifact record is not an object"
                )
            target, after, _before, after_sha, before_sha = self._artifact_paths(
                transaction, raw_record
            )
            if target in seen:
                raise WalIntegrityError(f"{transaction.name}: duplicate target")
            seen.add(target)
            current = target.read_bytes() if target.is_file() else None
            current_sha = _sha_bytes(current) if current is not None else None
            if current_sha == after_sha:
                continue
            if current_sha != before_sha:
                raise WalIntegrityError(
                    f"{transaction.name}: target changed outside transaction: {target}"
                )
            _atomic_replace(
                target,
                after.read_bytes(),
                label=f"target:{index}",
                fault_injector=fault_injector,
                prepared_path=target.with_name(
                    f".{target.name}.wal-{transaction.name}-{index}.prepared"
                ),
            )

    def _inspect_artifacts(
        self,
        transaction: Path,
        manifest: Mapping[str, object],
        *,
        require_after_images: bool,
    ) -> dict[str, int]:
        """Validate staged images and targets without changing any path."""
        artifacts = manifest["artifacts"]
        assert isinstance(artifacts, list)
        seen: set[Path] = set()
        targets_before = 0
        targets_after = 0
        for raw_record in artifacts:
            if not isinstance(raw_record, Mapping):
                raise WalIntegrityError(
                    f"{transaction.name}: artifact record is not an object"
                )
            target, _after, _before, after_sha, before_sha = self._artifact_paths(
                transaction, raw_record
            )
            if target in seen:
                raise WalIntegrityError(f"{transaction.name}: duplicate target")
            seen.add(target)
            if target.exists() and not target.is_file():
                raise WalIntegrityError(
                    f"{transaction.name}: target is not a regular file: {target}"
                )
            current = target.read_bytes() if target.is_file() else None
            current_sha = _sha_bytes(current) if current is not None else None
            if current_sha == after_sha:
                targets_after += 1
            elif current_sha == before_sha and not require_after_images:
                targets_before += 1
            else:
                label = (
                    "committed target drift"
                    if require_after_images
                    else "target changed outside transaction"
                )
                raise WalIntegrityError(
                    f"{transaction.name}: {label}: {target}"
                )
        return {
            "artifact_count": len(artifacts),
            "targets_before": targets_before,
            "targets_after": targets_after,
        }

    def _inspect_transaction(self, transaction: Path) -> dict[str, object]:
        manifest = self._load_manifest(transaction)
        if manifest is None:
            return {
                "transaction_id": transaction.name,
                "phase": "unprepared",
                "required_action": "rollback",
                "artifact_count": 0,
                "targets_before": 0,
                "targets_after": 0,
            }
        phase = str(manifest["phase"])
        detail = self._inspect_artifacts(
            transaction,
            manifest,
            require_after_images=phase == "committed",
        )
        return {
            "transaction_id": transaction.name,
            "phase": phase,
            "required_action": "archive_committed"
            if phase == "committed"
            else "roll_forward",
            **detail,
        }

    def _pending_transactions(self) -> tuple[Path, ...]:
        if not self._transactions_root.exists():
            return ()
        if not self._transactions_root.is_dir():
            raise WalIntegrityError("WAL transactions authority is not a directory")
        transactions = tuple(
            sorted(self._transactions_root.iterdir(), key=lambda path: path.name)
        )
        if len(transactions) > MAX_PENDING_TRANSACTIONS:
            raise WalIntegrityError("pending WAL transaction bound exceeded")
        for transaction in transactions:
            if (
                not transaction.is_dir()
                or transaction.is_symlink()
                or not _IDENTIFIER.fullmatch(transaction.name)
            ):
                raise WalIntegrityError(
                    f"unexpected directory in WAL authority: {transaction.name}"
                )
        return transactions

    def _inspection_fingerprint(self) -> str:
        if not self._transactions_root.exists():
            return "absent"
        records: list[dict[str, object]] = []
        total_bytes = 0
        paths = sorted(
            self._transactions_root.rglob("*"),
            key=lambda path: path.relative_to(self._transactions_root).as_posix(),
        )
        if len(paths) > MAX_INSPECTION_FILES:
            raise WalIntegrityError("WAL inspection file bound exceeded")
        for path in paths:
            relative = path.relative_to(self._transactions_root).as_posix()
            if path.is_symlink():
                raise WalIntegrityError(f"symlink in WAL authority: {relative}")
            if path.is_dir():
                records.append({"path": relative, "kind": "directory"})
                continue
            if not path.is_file():
                raise WalIntegrityError(f"non-regular WAL entry: {relative}")
            payload = path.read_bytes()
            total_bytes += len(payload)
            if total_bytes > MAX_INSPECTION_BYTES:
                raise WalIntegrityError("WAL inspection byte bound exceeded")
            records.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size": len(payload),
                    "sha256": _sha_bytes(payload),
                }
            )
        return _sha_bytes(_canonical(records))

    def _archive_unprepared(self, transaction: Path) -> Path:
        self._rolled_back_root.mkdir(parents=True, exist_ok=True)
        destination = self._rolled_back_root / transaction.name
        if destination.exists():
            raise WalIntegrityError(
                f"{transaction.name}: rolled-back transaction identity collision"
            )
        os.replace(transaction, destination)
        _fsync_directory(self._transactions_root)
        _fsync_directory(self._rolled_back_root)
        return destination

    def _archive_committed(
        self,
        transaction: Path,
        fault_injector: FaultInjector | None = None,
    ) -> Path:
        self._committed_root.mkdir(parents=True, exist_ok=True)
        destination = self._committed_root / transaction.name
        if destination.exists():
            raise WalIntegrityError(
                f"{transaction.name}: committed transaction identity collision"
            )
        os.replace(transaction, destination)
        _fsync_directory(self._transactions_root)
        _fsync_directory(self._committed_root)
        if fault_injector is not None:
            fault_injector("journal:committed:published")
        return destination

    def _recover_locked(self) -> dict[str, object]:
        self._transactions_root.mkdir(parents=True, exist_ok=True)
        completed: list[str] = []
        rolled_back: list[str] = []
        for transaction in self._pending_transactions():
            inspection = self._inspect_transaction(transaction)
            manifest = self._load_manifest(transaction)
            if manifest is None:
                self._archive_unprepared(transaction)
                rolled_back.append(transaction.name)
                continue
            if manifest["phase"] != "committed":
                self._apply(transaction, manifest)
                manifest = self._write_manifest(
                    transaction, manifest, "committed", None
                )
                self._inspect_artifacts(
                    transaction, manifest, require_after_images=True
                )
            elif inspection["required_action"] != "archive_committed":
                raise WalIntegrityError(
                    f"{transaction.name}: invalid committed recovery action"
                )
            self._archive_committed(transaction)
            completed.append(transaction.name)
        return {
            "schema_version": SCHEMA_VERSION,
            "completed": completed,
            "rolled_back": rolled_back,
            "valid": True,
        }

    def recover(self) -> dict[str, object]:
        """Recover every retained transaction under the process-bound WAL lock."""
        self.journal_root.mkdir(parents=True, exist_ok=True)
        with FileLock(self._lock_path, timeout_seconds=self.lock_timeout_seconds):
            return self._recover_locked()

    def inspect(self) -> dict[str, object]:
        """Inspect pending recovery without creating, locking, or changing paths."""
        before = self._inspection_fingerprint()
        transactions = [
            self._inspect_transaction(transaction)
            for transaction in self._pending_transactions()
        ]
        after = self._inspection_fingerprint()
        if before != after:
            raise WalIntegrityError("WAL changed during read-only inspection")
        would_complete = [
            str(item["transaction_id"])
            for item in transactions
            if item["required_action"] != "rollback"
        ]
        would_roll_back = [
            str(item["transaction_id"])
            for item in transactions
            if item["required_action"] == "rollback"
        ]
        return {
            "schema_version": SCHEMA_VERSION,
            "mode": "inspect",
            "valid": True,
            "requires_recovery": bool(transactions),
            "would_complete": would_complete,
            "would_roll_back": would_roll_back,
            "transactions": transactions,
            "inspection_sha256": after,
        }

    def commit(
        self,
        artifacts: Iterable[JsonArtifact],
        *,
        transaction_id: str | None = None,
        fault_injector: FaultInjector | None = None,
    ) -> dict[str, object]:
        """Durably commit related JSON artifacts or leave a recoverable WAL."""
        items = self._normalize(artifacts)
        identifier = transaction_id or f"tx-{uuid.uuid4().hex}"
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError("transaction_id must be a bounded identifier")
        self.journal_root.mkdir(parents=True, exist_ok=True)
        with FileLock(self._lock_path, timeout_seconds=self.lock_timeout_seconds):
            self._recover_locked()
            before_images = [self._read_existing(target) for _, target, _ in items]
            if self.precommit_validator is not None:
                transitions = tuple(
                    JsonTransition(
                        artifact.role,
                        target,
                        json.loads(before.decode("utf-8"))
                        if before is not None
                        else None,
                        json.loads(after.decode("utf-8")),
                    )
                    for (artifact, target, after), before in zip(
                        items, before_images, strict=True
                    )
                )
                self.precommit_validator(transitions)
            transaction = self._transactions_root / identifier
            if (
                transaction.exists()
                or (self._rolled_back_root / identifier).exists()
                or (self._committed_root / identifier).exists()
            ):
                raise ValueError(f"transaction_id has already been used: {identifier}")
            transaction.mkdir(parents=False)
            _fsync_directory(self._transactions_root)
            records: list[dict[str, object]] = []
            intents: list[dict[str, str]] = []
            for index, ((artifact, target, after), before) in enumerate(
                zip(items, before_images, strict=True)
            ):
                before_stage = f"before/{index:04d}.json"
                after_stage = f"after/{index:04d}.json"
                if before is not None:
                    _write_new(transaction / before_stage, before)
                    if fault_injector is not None:
                        fault_injector(f"journal:before:{index}")
                _write_new(transaction / after_stage, after)
                if fault_injector is not None:
                    fault_injector(f"journal:after:{index}")
                relative = target.relative_to(self.allowed_root).as_posix()
                after_sha = _sha_bytes(after)
                records.append(
                    {
                        "index": index,
                        "role": artifact.role,
                        "path": relative,
                        "before": {
                            "exists": before is not None,
                            "sha256": _sha_bytes(before)
                            if before is not None
                            else None,
                            "stage": before_stage if before is not None else None,
                        },
                        "after": {"sha256": after_sha, "stage": after_stage},
                    }
                )
                intents.append(
                    {"role": artifact.role, "path": relative, "sha256": after_sha}
                )
            manifest = self._write_manifest(
                transaction,
                {
                    "schema_version": SCHEMA_VERSION,
                    "transaction_id": identifier,
                    "recovery_policy": RECOVERY_POLICY,
                    "intent_sha256": _sha_bytes(_canonical(intents)),
                    "artifacts": records,
                },
                "prepared",
                fault_injector,
            )
            manifest = self._write_manifest(
                transaction, manifest, "applying", fault_injector
            )
            self._apply(transaction, manifest, fault_injector)
            manifest = self._write_manifest(
                transaction, manifest, "committed", fault_injector
            )
            committed = self._archive_committed(transaction, fault_injector)
            return {
                "schema_version": SCHEMA_VERSION,
                "transaction_id": identifier,
                "state": "committed",
                "artifact_count": len(records),
                "intent_sha256": manifest["intent_sha256"],
                "journal": committed.as_posix(),
            }
