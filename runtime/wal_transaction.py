"""Crash-consistent, bounded transactions over related artifacts.

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
import stat
import time
from typing import Callable, Iterable, Mapping
import uuid

from .file_lock import FileLock
from .json_io import bounded_canonical_json_bytes, decode_json_object, decode_json_value
from .input_files import read_file_image


SCHEMA_VERSION = "1.0"
RECOVERY_POLICY = "rollback-before-manifest-roll-forward-after-manifest"
ARTIFACT_ROLES = frozenset({"state", "event", "receipt", "handoff", "projection"})
MAX_ARTIFACTS = 128
MAX_TRANSACTION_BYTES = 64 * 1024 * 1024
MAX_PENDING_TRANSACTIONS = 128
MAX_INSPECTION_FILES = 4096
MAX_INSPECTION_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
_REPLACE_RETRY_DELAYS_SECONDS = (0.0, 0.01, 0.05, 0.15, 0.35, 0.75)
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class WalIntegrityError(RuntimeError):
    """Raised when a journal or target cannot be reconciled without data loss."""


class WalConflictError(WalIntegrityError):
    """The exact source generation validated by the caller is no longer current."""


@dataclass(frozen=True)
class JsonArtifact:
    """One JSON value and its semantic role in a coordinated transaction."""

    role: str
    path: Path
    value: object


@dataclass(frozen=True)
class JsonTextArtifact:
    """One exact UTF-8 JSON serialization, validated before it is staged."""

    role: str
    path: Path
    value: str


@dataclass(frozen=True)
class BytesArtifact:
    """One exact byte payload and its semantic role in a transaction."""

    role: str
    path: Path
    value: bytes


@dataclass(frozen=True)
class TextArtifact:
    """One exact UTF-8 text payload and its semantic role in a transaction."""

    role: str
    path: Path
    value: str


Artifact = JsonArtifact | JsonTextArtifact | BytesArtifact | TextArtifact


FaultInjector = Callable[[str], None]


@dataclass(frozen=True)
class JsonTransition:
    """Typed before/after values exposed to a fail-closed pre-commit guard."""

    role: str
    path: Path
    before: object | bytes | str | None
    after: object | bytes | str


PreCommitValidator = Callable[[tuple[JsonTransition, ...]], None]


def _canonical(value: object, *, max_bytes=None) -> bytes:
    return bounded_canonical_json_bytes(value, max_bytes=MAX_TRANSACTION_BYTES if max_bytes is None else max_bytes)


def _bounded_text(value, limit):
    if type(value) is not str or len(value) > limit:
        raise ValueError('transaction text exceeds byte budget')
    result = bytearray()
    for start in range(0, len(value), 16384):
        fragment = value[start:start + 16384].encode('utf-8')
        if len(result) + len(fragment) > limit:
            raise ValueError('transaction text exceeds byte budget')
        result.extend(fragment)
    return bytes(result)


def _bounded_artifacts(artifacts):
    items = []
    for artifact in artifacts:
        if len(items) >= MAX_ARTIFACTS:
            raise ValueError(f'transaction must contain 1..{MAX_ARTIFACTS} artifacts')
        if type(artifact) not in (JsonArtifact, JsonTextArtifact, TextArtifact, BytesArtifact):
            raise TypeError('unsupported artifact type')
        items.append(artifact)
    if not items:
        raise ValueError(f'transaction must contain 1..{MAX_ARTIFACTS} artifacts')
    return tuple(items)


def _bounded_image(path, *, limit=None):
    """Bound allocation before acquisition, then recheck the opened file image."""
    limit = MAX_TRANSACTION_BYTES if limit is None else limit
    if type(limit) is not int or limit < 0:
        raise WalIntegrityError('WAL aggregate byte budget exceeded')
    limit = min(limit, MAX_TRANSACTION_BYTES)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or _is_symlink_or_reparse(path) or before.st_size > limit:
        raise WalIntegrityError('WAL image is unsafe or exceeds byte budget')
    if limit == 0:
        raw = b''
    else:
        raw = bytes(read_file_image(path, before, limit=limit, deadline=time.monotonic() + 60))
    after = path.lstat()
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if signature(before) != signature(after) or len(raw) != after.st_size:
        raise WalIntegrityError('WAL image changed during acquisition')
    return raw


def _strict_json_loads(value: str) -> object:
    return decode_json_value(_bounded_text(value, MAX_TRANSACTION_BYTES), max_bytes=MAX_TRANSACTION_BYTES)


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _attach_outcome(error, name, outcome):
    """Best-effort diagnostics must never replace the causal exception."""
    try:
        setattr(error, name, dict(outcome))
    except BaseException:
        pass
    try:
        error.add_note(name + ': ' + json.dumps(outcome, sort_keys=True))
    except BaseException:
        pass


class _wal_lock:
    """Keep the causal failure if releasing its lock also fails."""

    def __init__(self, path, timeout):
        self.lock = FileLock(path, timeout_seconds=timeout)

    def __enter__(self):
        self.lock.__enter__()
        return self

    def __exit__(self, error_type, error, traceback):
        try:
            self.lock.__exit__(error_type, error, traceback)
        except BaseException as release_error:
            if error is None:
                raise
            _attach_outcome(error, 'wal_lock_release', {
                'acknowledgement': 'failed', 'error_type': type(release_error).__name__})
        return False


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


def _replace_with_bounded_permission_retry(source: Path, destination: Path) -> None:
    """Keep one replace atomic while tolerating bounded Windows handle races."""

    last_error: PermissionError | None = None
    for delay in _REPLACE_RETRY_DELAYS_SECONDS:
        if delay:
            time.sleep(delay)
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            last_error = error
    assert last_error is not None
    raise last_error


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
    _replace_with_bounded_permission_retry(temporary, path)
    _fsync_directory(path.parent)
    if fault_injector is not None:
        fault_injector(f"{label}:published")


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_symlink_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except FileNotFoundError:
        return False
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    return bool(reparse_flag and attributes & reparse_flag)


def _reject_nominal_link_chain(path: Path, root: Path, *, label: str) -> None:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes allowed root: {path}") from error
    current = root
    for part in relative.parts:
        current /= part
        if _is_symlink_or_reparse(current):
            raise WalIntegrityError(f"{label} traverses a symlink/reparse point: {current}")


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
            type(record.get("index")) is not int
            or record.get("index") != index
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
        suffixes = ("json", "txt", "bin")
        if after["stage"] not in {f"after/{index:04d}.{suffix}" for suffix in suffixes}:
            raise WalIntegrityError(f"{transaction_id}: noncanonical staged after-image")
        if before_exists and before["stage"] != after["stage"].replace("after/", "before/", 1):
            raise WalIntegrityError(f"{transaction_id}: noncanonical staged before-image")
        intents.append(
            {"role": str(role), "path": path, "sha256": str(after["sha256"])}
        )
    if manifest.get("intent_sha256") != _sha_bytes(_canonical(intents)):
        raise WalIntegrityError(f"{transaction_id}: intent digest mismatch")
    return manifest


def planned_write_boundaries(artifacts: Iterable[Artifact]) -> tuple[str, ...]:
    """Return every durable boundary a commit will expose to fault injection."""
    items = _bounded_artifacts(artifacts)
    boundaries: list[str] = ['intent:before_acceptance']
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
        if not self.allowed_root.is_dir():
            raise ValueError("allowed root must be an existing directory")
        journal_nominal = (
            journal_root
            if journal_root.is_absolute()
            else self.allowed_root / journal_root
        )
        journal_nominal = Path(os.path.abspath(journal_nominal))
        _reject_nominal_link_chain(
            journal_nominal,
            self.allowed_root,
            label="journal root",
        )
        self.journal_root = journal_nominal.resolve()
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
        self, artifacts: Iterable[Artifact]
    ) -> tuple[tuple[Artifact, Path, bytes], ...]:
        items = _bounded_artifacts(artifacts)
        if not 1 <= len(items) <= MAX_ARTIFACTS:
            raise ValueError(f"transaction must contain 1..{MAX_ARTIFACTS} artifacts")
        normalized: list[tuple[Artifact, Path, bytes]] = []
        targets: set[Path] = set()
        total = 0
        for artifact in items:
            if artifact.role not in ARTIFACT_ROLES:
                raise ValueError(f"unsupported JSON artifact role: {artifact.role}")
            target = self._safe_target(artifact.path, label="artifact")
            if _inside(target, self.journal_root):
                raise ValueError("transaction targets cannot be inside the WAL journal")
            if target in targets:
                raise ValueError(f"duplicate transaction target: {target}")
            targets.add(target)
            if isinstance(artifact, JsonArtifact):
                try:
                    rendered = _canonical(artifact.value, max_bytes=MAX_TRANSACTION_BYTES - total)
                except (TypeError, ValueError) as error:
                    raise ValueError(f"artifact is not strict JSON: {target}") from error
            elif isinstance(artifact, JsonTextArtifact):
                if not isinstance(artifact.value, str):
                    raise ValueError(f"JSON text artifact is not a string: {target}")
                if len(artifact.value) > MAX_TRANSACTION_BYTES - total:
                    raise ValueError('transaction text exceeds byte budget')
                rendered = _bounded_text(artifact.value, MAX_TRANSACTION_BYTES - total)
                try:
                    decode_json_value(rendered, max_bytes=MAX_TRANSACTION_BYTES)
                except ValueError as error:
                    raise ValueError(f"artifact is not strict JSON: {target}") from error
            elif isinstance(artifact, TextArtifact):
                if not isinstance(artifact.value, str):
                    raise ValueError(f"text artifact is not a string: {target}")
                if len(artifact.value) > MAX_TRANSACTION_BYTES - total:
                    raise ValueError('transaction text exceeds byte budget')
                rendered = _bounded_text(artifact.value, MAX_TRANSACTION_BYTES - total)
            elif isinstance(artifact, BytesArtifact):
                if not isinstance(artifact.value, bytes):
                    raise ValueError(f"byte artifact is not bytes: {target}")
                rendered = artifact.value
            else:
                raise TypeError(f"unsupported artifact type: {type(artifact).__name__}")
            total += len(rendered)
            if total > MAX_TRANSACTION_BYTES:
                raise ValueError("transaction payload exceeds the bounded byte limit")
            normalized.append((artifact, target, rendered))
        return tuple(normalized)

    def _safe_target(self, path: Path, *, label: str) -> Path:
        if ".." in path.parts:
            raise ValueError(f"{label} contains parent traversal: {path}")
        nominal = path if path.is_absolute() else self.allowed_root / path
        nominal = Path(os.path.abspath(nominal))
        _reject_nominal_link_chain(nominal, self.allowed_root, label=label)
        target = nominal.resolve(strict=False)
        if not _inside(target, self.allowed_root):
            raise ValueError(f"{label} escapes allowed root: {path}")
        return target

    def read_source_image(self, path: Path, *, limit=MAX_TRANSACTION_BYTES) -> bytes | None:
        """Capture one bounded raw input for parsing and exact commit expectations.

        This creates no lock or journal and does not assert a multi-file snapshot.
        Supply its digest (or None for absence) to commit for stale-intent refusal
        under the cooperating WAL writer lock.
        """
        target = self._safe_target(path, label='source image')
        if _inside(target, self.journal_root):
            raise ValueError('source image cannot be inside the WAL journal')
        return _bounded_image(target, limit=limit) if target.exists() else None

    def _read_existing(self, artifact: Artifact, path: Path, *, limit=MAX_TRANSACTION_BYTES) -> bytes | None:
        if not path.exists():
            return None
        if not path.is_file() or path.is_symlink():
            raise WalIntegrityError(f"target is not a regular file: {path}")
        raw = _bounded_image(path, limit=limit)
        if isinstance(artifact, (JsonArtifact, JsonTextArtifact)):
            try:
                _strict_json_loads(raw.decode("utf-8"))
            except (UnicodeError, ValueError) as error:
                raise WalIntegrityError(
                    f"existing JSON target is invalid: {path}"
                ) from error
        elif isinstance(artifact, TextArtifact):
            try:
                raw.decode("utf-8")
            except UnicodeError as error:
                raise WalIntegrityError(
                    f"existing text target is not UTF-8: {path}"
                ) from error
        return raw

    @staticmethod
    def _transition_value(artifact: Artifact, payload: bytes) -> object | bytes | str:
        if isinstance(artifact, (JsonArtifact, JsonTextArtifact)):
            return _strict_json_loads(payload.decode("utf-8"))
        if isinstance(artifact, TextArtifact):
            return payload.decode("utf-8")
        return payload

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
            value = decode_json_object(_bounded_image(path, limit=MAX_MANIFEST_BYTES), max_bytes=MAX_MANIFEST_BYTES)
        except (OSError, UnicodeError, ValueError) as error:
            raise WalIntegrityError(
                f"{transaction.name}: manifest is unreadable"
            ) from error
        return _validate_manifest(value, transaction.name)

    def _verify_retained_manifest(self, transaction, expected):
        if self._load_manifest(transaction) != expected:
            raise WalIntegrityError(f'{transaction.name}: retained manifest changed before acknowledgement')

    def _artifact_paths(
        self, transaction: Path, record: Mapping[str, object], *, image_reader=None
    ) -> tuple[Path, Path, Path | None, str, str | None]:
        try:
            relative = Path(str(record["path"]))
            if relative.is_absolute():
                raise ValueError
            target = self._safe_target(relative, label="recovery target")
            after_record = record["after"]
            before_record = record["before"]
            if not isinstance(after_record, Mapping) or not isinstance(
                before_record, Mapping
            ):
                raise ValueError
            after_nominal = transaction / str(after_record["stage"])
            _reject_nominal_link_chain(
                after_nominal, transaction, label="staged after-image"
            )
            after = after_nominal.resolve()
            before_nominal = transaction / str(before_record["stage"])
            if before_record.get("exists") is True:
                _reject_nominal_link_chain(
                    before_nominal,
                    transaction,
                    label="staged before-image",
                )
                before = before_nominal.resolve()
            else:
                before = None
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
        read = image_reader or _bounded_image
        if _sha_bytes(read(after)) != after_sha:
            raise WalIntegrityError(f"{transaction.name}: staged after-image mismatch")
        if before is not None and (
            not before.is_file() or _sha_bytes(read(before)) != before_sha
        ):
            raise WalIntegrityError(f"{transaction.name}: staged before-image mismatch")
        return target, after, before, after_sha, before_sha

    def _acquire_artifacts(self, transaction, manifest, *, require_after_images=False):
        """Acquire and validate the complete bounded image set before target effects.

        Immutable bytes are request-local. This is not a filesystem-wide snapshot
        or a generation token; cooperative writers remain bound to the WAL lock.
        """
        manifest = _validate_manifest(manifest, transaction.name)
        cache = {}
        remaining = MAX_INSPECTION_BYTES
        def read(path):
            nonlocal remaining
            if path not in cache:
                image = _bounded_image(path, limit=remaining)
                remaining -= len(image)
                cache[path] = image
            return cache[path]
        acquired = []
        seen = set()
        for record in manifest['artifacts']:
            target, after, _before, after_sha, before_sha = self._artifact_paths(
                transaction, record, image_reader=read)
            if target in seen:
                raise WalIntegrityError(f"{transaction.name}: duplicate target")
            seen.add(target)
            if target.exists() and not target.is_file():
                raise WalIntegrityError(f"{transaction.name}: target is not a regular file: {target}")
            current = read(target) if target.exists() else None
            current_sha = _sha_bytes(current) if current is not None else None
            if current_sha != after_sha and (require_after_images or current_sha != before_sha):
                label = 'committed target drift' if require_after_images else 'target changed outside transaction'
                raise WalIntegrityError(f"{transaction.name}: {label}: {target}")
            acquired.append((target, cache[after], after_sha, before_sha, current_sha))
        return tuple(acquired)

    def _apply(
        self,
        transaction: Path,
        manifest: Mapping[str, object],
        fault_injector: FaultInjector | None = None,
    ) -> None:
        acquired = self._acquire_artifacts(transaction, manifest)
        for index, (target, after, after_sha, before_sha, _observed) in enumerate(acquired):
            # Recheck each target at its publication boundary. Staged bytes are
            # never reopened after their verified acquisition.
            current = _bounded_image(target) if target.exists() else None
            current_sha = _sha_bytes(current) if current is not None else None
            if current_sha == after_sha:
                continue
            if current_sha != before_sha:
                raise WalIntegrityError(f"{transaction.name}: target changed outside transaction: {target}")
            _atomic_replace(target, after, label=f"target:{index}",
                fault_injector=fault_injector,
                prepared_path=target.with_name(f".{target.name}.wal-{transaction.name}-{index}.prepared"))


    def _inspect_artifacts(
        self,
        transaction: Path,
        manifest: Mapping[str, object],
        *,
        require_after_images: bool,
    ) -> dict[str, int]:
        """Validate one acquired staged/target image set without changing paths."""
        acquired = self._acquire_artifacts(transaction, manifest,
            require_after_images=require_after_images)
        targets_after = sum(current == after_sha for _, _, after_sha, _, current in acquired)
        return {'artifact_count': len(acquired), 'targets_after': targets_after,
                'targets_before': len(acquired) - targets_after}


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
        transactions = []
        with os.scandir(self._transactions_root) as entries:
            for entry in entries:
                if len(transactions) >= MAX_PENDING_TRANSACTIONS:
                    raise WalIntegrityError('pending WAL transaction bound exceeded')
                transactions.append(Path(entry.path))
        transactions.sort(key=lambda path: path.name)
        for transaction in transactions:
            if (
                not transaction.is_dir()
                or transaction.is_symlink()
                or not _IDENTIFIER.fullmatch(transaction.name)
            ):
                raise WalIntegrityError(
                    f"unexpected directory in WAL authority: {transaction.name}"
                )
        if len(transactions) > 1:
            raise WalIntegrityError('pending legacy WAL chronology is unknown; explicit recovery disposition required')
        return tuple(transactions)

    def _inspection_fingerprint(self) -> str:
        if not self._transactions_root.exists():
            return "absent"
        records: list[dict[str, object]] = []
        total_bytes = 0
        paths = []
        pending = [self._transactions_root]
        while pending:
            parent = pending.pop()
            if len(parent.relative_to(self._transactions_root).parts) > 128:
                raise WalIntegrityError('WAL inspection depth bound exceeded')
            with os.scandir(parent) as entries:
                for entry in entries:
                    if len(paths) >= MAX_INSPECTION_FILES:
                        raise WalIntegrityError('WAL inspection file bound exceeded')
                    path = Path(entry.path)
                    if _is_symlink_or_reparse(path):
                        raise WalIntegrityError('link in WAL authority')
                    paths.append(path)
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(path)
        paths.sort(key=lambda path: path.relative_to(self._transactions_root).as_posix())
        for path in paths:
            relative = path.relative_to(self._transactions_root).as_posix()
            if path.is_symlink():
                raise WalIntegrityError(f"symlink in WAL authority: {relative}")
            if path.is_dir():
                records.append({"path": relative, "kind": "directory"})
                continue
            if not path.is_file():
                raise WalIntegrityError(f"non-regular WAL entry: {relative}")
            payload = _bounded_image(path, limit=MAX_INSPECTION_BYTES - total_bytes)
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
            if path.name == 'manifest.json' and len(path.relative_to(self._transactions_root).parts) == 2:
                manifest = _validate_manifest(decode_json_object(payload, max_bytes=MAX_MANIFEST_BYTES), path.parent.name)
                for artifact in manifest['artifacts']:
                    target = self._safe_target(Path(artifact['path']), label='inspection target')
                    raw = _bounded_image(target, limit=MAX_INSPECTION_BYTES - total_bytes) if target.exists() else None
                    total_bytes += len(raw) if raw is not None else 0
                    records.append({'path': artifact['path'], 'kind': 'target',
                                    'sha256': _sha_bytes(raw) if raw is not None else None})
        return _sha_bytes(_canonical(records))

    def _archive_unprepared(self, transaction: Path) -> Path:
        self._rolled_back_root.mkdir(parents=True, exist_ok=True)
        destination = self._rolled_back_root / transaction.name
        if destination.exists():
            raise WalIntegrityError(
                f"{transaction.name}: rolled-back transaction identity collision"
            )
        _replace_with_bounded_permission_retry(transaction, destination)
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
        _replace_with_bounded_permission_retry(transaction, destination)
        _fsync_directory(self._transactions_root)
        _fsync_directory(self._committed_root)
        if fault_injector is not None:
            fault_injector("journal:committed:published")
        return destination

    def _recover_locked(self) -> dict[str, object]:
        completed: list[str] = []
        rolled_back: list[str] = []
        outcome = {
            "schema_version": SCHEMA_VERSION,
            "completed": completed,
            "rolled_back": rolled_back,
            "valid": False,
            "active_transaction": None,
            "active_phase": "initializing",
            "target_effects_may_have_occurred": False,
            "journal_effects_may_have_occurred": True,
        }
        try:
            self._transactions_root.mkdir(parents=True, exist_ok=True)
            outcome['active_phase'] = 'inventory'
            for transaction in self._pending_transactions():
                outcome.update(active_transaction=transaction.name, active_phase='inspecting',
                               active_target_effects_may_have_occurred=False)
                manifest = self._load_manifest(transaction)
                if manifest is None:
                    outcome['active_phase'] = 'archiving_unprepared'
                    self._archive_unprepared(transaction)
                    rolled_back.append(transaction.name)
                    continue
                if manifest["phase"] != "committed":
                    outcome.update(active_phase='applying', target_effects_may_have_occurred=True,
                                   active_target_effects_may_have_occurred=True)
                    self._apply(transaction, manifest)
                    outcome['active_phase'] = 'publishing_committed_manifest'
                    manifest = self._write_manifest(transaction, manifest, "committed", None)
                    self._inspect_artifacts(transaction, manifest, require_after_images=True)
                else:
                    self._inspect_artifacts(transaction, manifest, require_after_images=True)
                outcome['active_phase'] = 'archiving_committed'
                self._archive_committed(transaction)
                completed.append(transaction.name)
        except BaseException as error:
            _attach_outcome(error, 'wal_recovery', outcome)
            raise
        outcome.update(valid=True, active_transaction=None, active_phase='settled',
                       target_effects_may_have_occurred=bool(completed))
        return outcome

    def recover(self) -> dict[str, object]:
        """Recover every retained transaction under the process-bound WAL lock."""
        outcome = {'state': 'not_started', 'acknowledgement': 'pending'}
        try:
            self.journal_root.mkdir(parents=True, exist_ok=True)
            with _wal_lock(self._lock_path, self.lock_timeout_seconds):
                outcome = self._recover_locked()
                outcome['acknowledgement'] = 'pending'
        except BaseException as error:
            outcome = dict(getattr(error, 'wal_recovery', outcome))
            outcome['acknowledgement'] = 'failed'
            if hasattr(error, 'wal_lock_release'):
                outcome['lock_release'] = error.wal_lock_release
            _attach_outcome(error, 'wal_recovery', outcome)
            raise
        outcome['acknowledgement'] = 'acknowledged'
        return outcome

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

    def _expectations(self, value, *, targets=None):
        if value is None:
            return None
        if type(value) is not dict or len(value) > MAX_INSPECTION_FILES:
            raise ValueError('expected source images must be a bounded actual object')
        normalized = {}
        for name, digest in value.items():
            if type(name) is not str or not name or len(name) > 4096:
                raise ValueError('invalid expected image path')
            path = self._safe_target(Path(name), label='expected input')
            relative = path.relative_to(self.allowed_root).as_posix()
            if relative in normalized or name != relative:
                raise ValueError('expected image paths must be canonical and unique')
            if digest is not None and (type(digest) is not str or re.fullmatch(r'[0-9a-f]{64}', digest) is None):
                raise ValueError('expected image must be an exact digest or explicit absence')
            normalized[relative] = digest
        if targets is not None and set(normalized) != set(targets):
            raise ValueError('expected before-images must cover the exact target set')
        return normalized

    def commit(self, artifacts: Iterable[Artifact], *, transaction_id=None,
               fault_injector=None, expected_before=None, expected_inputs=None):
        """Commit with explicit old-recovery and new-transaction effect outcomes.

        Callers that computed an after-image earlier must supply exact raw
        expected_before images. Legacy callers without them retain only WAL
        crash recovery, not protection from stale read/modify/write intent.
        """
        outcome = {'recovery': {'state': 'not_requested'}, 'transaction_phase': 'not_admitted',
                   'intent_accepted': False, 'publication': 'not_started', 'acknowledgement': 'pending'}
        try:
            result = self._commit(artifacts, transaction_id=transaction_id,
                                  fault_injector=fault_injector, expected_before=expected_before,
                                  expected_inputs=expected_inputs, outcome=outcome)
        except BaseException as error:
            outcome['acknowledgement'] = 'failed'
            if hasattr(error, 'wal_lock_release'):
                outcome['lock_release'] = error.wal_lock_release
            _attach_outcome(error, 'wal_outcome', outcome)
            raise
        outcome['acknowledgement'] = 'acknowledged'
        return {**result, 'outcome': outcome}

    def _commit(
        self,
        artifacts: Iterable[Artifact],
        *,
        transaction_id: str | None = None,
        fault_injector: FaultInjector | None = None,
        expected_before=None, expected_inputs=None, outcome=None,
    ) -> dict[str, object]:
        """Durably commit related JSON artifacts or leave a recoverable WAL."""
        items = self._normalize(artifacts)
        identifier = transaction_id or f"tx-{uuid.uuid4().hex}"
        if not _IDENTIFIER.fullmatch(identifier):
            raise ValueError("transaction_id must be a bounded identifier")
        targets = [target.relative_to(self.allowed_root).as_posix() for _artifact, target, _after in items]
        expected_before = self._expectations(expected_before, targets=targets)
        expected_inputs = self._expectations(expected_inputs)
        self.journal_root.mkdir(parents=True, exist_ok=True)
        with _wal_lock(self._lock_path, self.lock_timeout_seconds):
            outcome['recovery'] = {'state': 'started', 'effects_may_have_occurred': True}
            try:
                outcome['recovery'] = self._recover_locked()
            except BaseException as error:
                outcome['recovery'] = getattr(error, 'wal_recovery', outcome['recovery'])
                raise
            if fault_injector is not None:
                fault_injector('intent:before_acceptance')
            before_images = []
            image_bytes = sum(len(after) for _artifact, _target, after in items)
            for artifact, target, _after in items:
                before = self._read_existing(artifact, target, limit=MAX_TRANSACTION_BYTES - image_bytes)
                image_bytes += len(before) if before is not None else 0
                before_images.append(before)
            if expected_before is not None:
                actual = {name: _sha_bytes(raw) if raw is not None else None
                          for name, raw in zip(targets, before_images, strict=True)}
                if actual != expected_before:
                    raise WalConflictError('validated before-image generation changed')
            if expected_inputs is not None:
                input_bytes = 0
                for name, expected in expected_inputs.items():
                    target = self._safe_target(Path(name), label='expected input')
                    raw = _bounded_image(target, limit=MAX_INSPECTION_BYTES - input_bytes) if target.exists() else None
                    input_bytes += len(raw) if raw is not None else 0
                    if (_sha_bytes(raw) if raw is not None else None) != expected:
                        raise WalConflictError('validated read dependency changed: ' + name)
            if self.precommit_validator is not None:
                transitions = tuple(
                    JsonTransition(
                        artifact.role,
                        target,
                        self._transition_value(artifact, before)
                        if before is not None
                        else None,
                        self._transition_value(artifact, after),
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
            outcome.update(intent_accepted=True, transaction_phase='preparing',
                           transaction_id=identifier, expected_before_supplied=expected_before is not None)
            transaction.mkdir(parents=False)
            _fsync_directory(self._transactions_root)
            records: list[dict[str, object]] = []
            intents: list[dict[str, str]] = []
            for index, ((artifact, target, after), before) in enumerate(
                zip(items, before_images, strict=True)
            ):
                suffix = (
                    ".json"
                    if isinstance(artifact, (JsonArtifact, JsonTextArtifact))
                    else ".txt"
                    if isinstance(artifact, TextArtifact)
                    else ".bin"
                )
                before_stage = f"before/{index:04d}{suffix}"
                after_stage = f"after/{index:04d}{suffix}"
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
            outcome.update(transaction_phase='applying', publication='may_have_occurred')
            self._apply(transaction, manifest, fault_injector)
            outcome['publication'] = 'targets_published'
            self._verify_retained_manifest(transaction, manifest)
            manifest = self._write_manifest(
                transaction, manifest, "committed", fault_injector
            )
            outcome['transaction_phase'] = 'committed'
            self._verify_retained_manifest(transaction, manifest)
            self._inspect_artifacts(transaction, manifest, require_after_images=True)
            committed = self._archive_committed(transaction, fault_injector)
            outcome['journal'] = committed.as_posix()
            self._verify_retained_manifest(committed, manifest)
            self._inspect_artifacts(committed, manifest, require_after_images=True)
            return {
                "schema_version": SCHEMA_VERSION,
                "transaction_id": identifier,
                "state": "committed",
                "artifact_count": len(records),
                "intent_sha256": manifest["intent_sha256"],
                "journal": committed.as_posix(),
            }
