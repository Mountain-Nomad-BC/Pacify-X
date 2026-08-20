"""Durable lifecycle state, explicit migrations, and resume reconciliation."""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Callable, Iterable, Mapping, Sequence

from .wal_transaction import JsonArtifact, JsonWal


CURRENT_STATE_SCHEMA_VERSION = "2.0"
SUPPORTED_STATE_SCHEMA_VERSIONS = ("1.0", CURRENT_STATE_SCHEMA_VERSION)
MIGRATION_RECEIPT_SCHEMA_VERSION = "px.durable-state-migration-receipt/1.0"
BACKUP_SCHEMA_VERSION = "px.durable-state-migration-backup/1.0"

_V1_FIELDS = frozenset(
    {
        "schema_version",
        "package_id",
        "completed_steps",
        "selected_skills",
        "pending_approvals",
        "evidence_refs",
        "idempotency_keys",
    }
)
_V2_FIELDS = _V1_FIELDS | {"interrupted_steps"}
_VERSION = re.compile(r"(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\Z")


class DurableStateIntegrityError(ValueError):
    """Raised when authoritative durable state is malformed or ambiguous."""


class DurableStateVersionError(DurableStateIntegrityError):
    """Raised when a state version cannot be safely read or migrated."""


@dataclass(frozen=True, slots=True)
class DurableState:
    package_id: str
    completed_steps: tuple[str, ...]
    selected_skills: tuple[tuple[str, str], ...]
    pending_approvals: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    idempotency_keys: tuple[str, ...]
    interrupted_steps: tuple[str, ...] = ()


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


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_version(value: object, *, label: str) -> tuple[int, int]:
    if not isinstance(value, str):
        raise DurableStateVersionError(f"{label} schema_version must be a string")
    match = _VERSION.fullmatch(value)
    if match is None:
        raise DurableStateVersionError(f"{label} schema_version is invalid: {value!r}")
    return int(match["major"]), int(match["minor"])


def _source_version(payload: Mapping[str, object]) -> tuple[str, bool]:
    """Return the declared version and whether this is historical unversioned v1."""
    declared = payload.get("schema_version")
    if declared is None:
        # PACIFY-X releases before D06 wrote exactly the v1 fields without a
        # schema marker. This compatibility is intentionally narrow.
        fields = frozenset(payload)
        if fields not in {
            _V1_FIELDS - {"schema_version"},
            _V2_FIELDS - {"schema_version"},
        }:
            raise DurableStateVersionError(
                "unversioned durable state does not match the historical v1 shape"
            )
        return "1.0", True
    version = str(declared)
    parsed = _parse_version(declared, label="durable state")
    current = _parse_version(CURRENT_STATE_SCHEMA_VERSION, label="current")
    if parsed > current:
        raise DurableStateVersionError(
            f"durable state {version} is newer than supported "
            f"{CURRENT_STATE_SCHEMA_VERSION}; downgrade refused"
        )
    if version not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        raise DurableStateVersionError(
            f"unsupported durable state schema_version: {version}"
        )
    return version, False


def _require_string_sequence(payload: Mapping[str, object], field: str) -> list[str]:
    value = payload.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise DurableStateIntegrityError(f"{field} must be an array of strings")
    return list(value)


def _validate_payload(
    payload: Mapping[str, object], version: str, *, historical_unversioned: bool = False
) -> None:
    expected = _V1_FIELDS if version == "1.0" else _V2_FIELDS
    if historical_unversioned:
        allowed = {_V1_FIELDS - {"schema_version"}, _V2_FIELDS - {"schema_version"}}
        if frozenset(payload) not in allowed:
            raise DurableStateIntegrityError(
                "historical durable state fields are not exact"
            )
    elif frozenset(payload) != expected:
        raise DurableStateIntegrityError(
            f"durable state {version} fields are not exact"
        )
    package_id = payload.get("package_id")
    if not isinstance(package_id, str) or not package_id.strip():
        raise DurableStateIntegrityError("package_id must be a non-empty string")
    for field in (
        "completed_steps",
        "pending_approvals",
        "evidence_refs",
        "idempotency_keys",
    ):
        _require_string_sequence(payload, field)
    if version == CURRENT_STATE_SCHEMA_VERSION or "interrupted_steps" in payload:
        _require_string_sequence(payload, "interrupted_steps")
    selected = payload.get("selected_skills")
    if not isinstance(selected, list) or any(
        not isinstance(item, list)
        or len(item) != 2
        or any(not isinstance(part, str) for part in item)
        for item in selected
    ):
        raise DurableStateIntegrityError(
            "selected_skills must be an array of two-string arrays"
        )


def _decode(path: Path) -> tuple[dict[str, object], bytes, str, bool]:
    if not path.is_file():
        raise DurableStateIntegrityError("durable state target is not a regular file")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DurableStateIntegrityError(
            "durable state is not valid UTF-8 JSON"
        ) from error
    if not isinstance(value, dict):
        raise DurableStateIntegrityError("durable state must be a JSON object")
    version, historical = _source_version(value)
    _validate_payload(value, version, historical_unversioned=historical)
    return value, raw, version, historical


def _state_payload(state: DurableState) -> dict[str, object]:
    return {"schema_version": CURRENT_STATE_SCHEMA_VERSION, **asdict(state)}


def _to_state(payload: Mapping[str, object]) -> DurableState:
    return DurableState(
        str(payload["package_id"]),
        tuple(payload["completed_steps"]),  # type: ignore[arg-type]
        tuple(tuple(item) for item in payload["selected_skills"]),  # type: ignore[arg-type]
        tuple(payload["pending_approvals"]),  # type: ignore[arg-type]
        tuple(payload["evidence_refs"]),  # type: ignore[arg-type]
        tuple(payload["idempotency_keys"]),  # type: ignore[arg-type]
        tuple(payload.get("interrupted_steps", ())),  # type: ignore[arg-type]
    )


def _migration_root(path: Path) -> Path:
    return path.parent / ".migrations" / path.name


def persist_state(state: DurableState, path: Path) -> None:
    """Persist current state, refusing implicit migration or downgrade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _state_payload(state)
    content = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if path.exists():
        if not path.is_file():
            raise ValueError("durable state target is not a file")
        _, raw, version, historical = _decode(path)
        if historical or version != CURRENT_STATE_SCHEMA_VERSION:
            raise DurableStateVersionError(
                "existing durable state requires explicit migration before replacement"
            )
        digest = _sha256(raw)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        history = path.parent / ".history" / path.name / f"{stamp}-{digest}.json"
        history.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(history))
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def migrate_state(
    path: Path, *, target_version: str = CURRENT_STATE_SCHEMA_VERSION
) -> dict[str, object]:
    """Migrate one authoritative state via a backup/state/receipt WAL commit."""
    target = _parse_version(target_version, label="target")
    current = _parse_version(CURRENT_STATE_SCHEMA_VERSION, label="current")
    if target_version not in SUPPORTED_STATE_SCHEMA_VERSIONS:
        raise DurableStateVersionError(
            f"unsupported migration target schema_version: {target_version}"
        )
    migration_root = _migration_root(path)
    wal = JsonWal(migration_root / "wal", path.parent)
    wal.recover()
    payload, raw, source_version, historical = _decode(path)
    source = _parse_version(source_version, label="source")
    if target < source:
        raise DurableStateVersionError(
            f"migration {source_version} to {target_version}: downgrade refused"
        )
    if target < current:
        raise DurableStateVersionError(
            f"migration target {target_version} is older than current "
            f"{CURRENT_STATE_SCHEMA_VERSION}; downgrade refused"
        )
    if source_version == target_version and not historical:
        return {
            "schema_version": MIGRATION_RECEIPT_SCHEMA_VERSION,
            "state_path": path.resolve().as_posix(),
            "from_version": source_version,
            "to_version": target_version,
            "migrated": False,
            "reason": "already_current",
            "state_sha256": _sha256(raw),
        }

    migrated = dict(payload)
    migrated["schema_version"] = CURRENT_STATE_SCHEMA_VERSION
    migrated.setdefault("interrupted_steps", [])
    _validate_payload(migrated, CURRENT_STATE_SCHEMA_VERSION)
    source_sha256 = _sha256(raw)
    target_sha256 = _sha256(_canonical(migrated))
    migration_id = f"durable-{source_sha256[:24]}-to-2.0"
    backup_path = migration_root / "backups" / f"{source_sha256}.json"
    receipt_path = migration_root / "receipts" / f"{migration_id}.json"
    backup = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "state_path": path.resolve().as_posix(),
        "source_version": source_version,
        "historical_unversioned": historical,
        "source_sha256": source_sha256,
        "source_bytes_base64": base64.b64encode(raw).decode("ascii"),
    }
    receipt = {
        "schema_version": MIGRATION_RECEIPT_SCHEMA_VERSION,
        "migration_id": migration_id,
        "state_path": path.resolve().as_posix(),
        "from_version": source_version,
        "to_version": CURRENT_STATE_SCHEMA_VERSION,
        "source_sha256": source_sha256,
        "target_sha256": target_sha256,
        "backup_path": backup_path.resolve().as_posix(),
        "steps": ["declare_schema_version", "add_interrupted_steps_default"],
        "migrated": True,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    wal.commit(
        (
            JsonArtifact("state", backup_path, backup),
            JsonArtifact("state", path, migrated),
            JsonArtifact("receipt", receipt_path, receipt),
        ),
        transaction_id=migration_id,
    )
    return receipt


def load_state(path: Path) -> DurableState:
    """Load only the current schema; callers must request migrations explicitly."""
    payload, _, version, historical = _decode(path)
    if historical or version != CURRENT_STATE_SCHEMA_VERSION:
        raise DurableStateVersionError(
            f"durable state {version} requires explicit migration to "
            f"{CURRENT_STATE_SCHEMA_VERSION}"
        )
    return _to_state(payload)


def reconcile_resume(
    state: DurableState,
    *,
    actual_evidence: Iterable[str],
    requested_idempotency_key: str | None = None,
) -> tuple[bool, tuple[str, ...]]:
    reasons: list[str] = []
    if set(state.evidence_refs) - set(actual_evidence):
        reasons.append("recorded evidence is missing from runtime")
    if state.interrupted_steps:
        reasons.append("interrupted steps are non-certifying")
    if (
        requested_idempotency_key
        and requested_idempotency_key in state.idempotency_keys
    ):
        reasons.append("effect idempotency key has already completed")
    return not reasons, tuple(sorted(reasons))


RECOVERY_REPORT_SCHEMA_VERSION = "px.recovery-report/1.0"
RECOVERY_DECISION_SCHEMA_VERSION = "px.recovery-decision/1.0"


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """A bounded, non-authorizing response to one normalized failure."""

    failure_class: str
    action: str
    next_state: str
    retry_delay_seconds: int | None
    retry_remaining: int
    circuit_open: bool
    fallback: str | None
    rollback_plan: str | None
    reasons: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    forensic_state: str = "retained"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": RECOVERY_DECISION_SCHEMA_VERSION,
            **asdict(self),
        }


_FAILURE_CLASSES = frozenset(
    {
        "transient",
        "capacity",
        "dependency",
        "persistence",
        "verification",
        "policy_denial",
        "permission_denial",
        "invariant",
        "irreversible",
        "unknown",
    }
)


def choose_recovery(
    *,
    failure_class: str,
    failure_signature: str,
    trace_signatures: Sequence[str],
    attempts: int,
    retry_budget: int,
    fallbacks: Sequence[str] = (),
    rollback_available: bool = False,
    state_changed: bool = False,
    idempotent: bool = False,
    circuit_threshold: int = 3,
    evidence_refs: Sequence[str] = (),
) -> RecoveryDecision:
    """Choose a distinct recovery path without generic or denial retries.

    The caller supplies the retained failure-signature trace, making circuit state
    reconstructable instead of hiding it in process-local memory.
    """
    normalized = failure_class.strip().lower()
    if normalized not in _FAILURE_CLASSES:
        normalized = "unknown"
    if not failure_signature.strip():
        raise ValueError("failure_signature must be non-empty")
    if attempts < 0 or retry_budget < 0 or circuit_threshold < 1:
        raise ValueError("recovery counters must be non-negative and bounded")
    repetitions = sum(item == failure_signature for item in trace_signatures)
    circuit_open = repetitions >= circuit_threshold
    remaining = max(0, retry_budget - attempts)
    reasons: list[str] = [f"normalized failure class: {normalized}"]
    fallback = next((item for item in fallbacks if item.strip()), None)

    if normalized in {"policy_denial", "permission_denial", "irreversible"}:
        reasons.append("denial or irreversible uncertainty is not retryable")
        action, next_state = "stop", "blocked"
    elif circuit_open:
        reasons.append("matching failure circuit is open")
        action, next_state = "escalate", "blocked"
    elif state_changed and rollback_available:
        reasons.append("partial state change requires explicit rollback")
        action, next_state = "rollback", "recovering"
    elif normalized == "persistence" and rollback_available:
        reasons.append("persistence failure has a verified rollback path")
        action, next_state = "rollback", "recovering"
    elif fallback is not None and normalized in {
        "capacity",
        "dependency",
        "verification",
        "transient",
    }:
        reasons.append("a named distinct fallback is available")
        action, next_state = "alternate", "recovering"
    elif normalized in {"transient", "capacity", "dependency"} and idempotent:
        if remaining:
            reasons.append("bounded idempotent retry remains")
            action, next_state = "retry", "recovering"
        else:
            reasons.append("retry budget is exhausted")
            action, next_state = "escalate", "blocked"
    elif normalized in {"invariant", "verification", "persistence"}:
        reasons.append("integrity-related failure requires human or alternate evidence")
        action, next_state = "escalate", "blocked"
    else:
        reasons.append("failure is not proven safe to retry")
        action, next_state = "stop", "blocked"

    retry_delay = min(60, 2 ** min(attempts, 5)) if action == "retry" else None
    return RecoveryDecision(
        normalized,
        action,
        next_state,
        retry_delay,
        remaining - 1 if action == "retry" else remaining,
        circuit_open,
        fallback if action == "alternate" else None,
        "restore retained before-images, then revalidate postconditions"
        if action == "rollback"
        else None,
        tuple(reasons),
        tuple(str(item) for item in evidence_refs),
    )


@dataclass(frozen=True, slots=True)
class RecoveryConfiguration:
    """Explicitly configured authorities inspected by startup/run recovery."""

    project_root: Path
    wal_targets: tuple[tuple[Path, Path], ...] = ()
    durable_state_paths: tuple[Path, ...] = ()
    event_bus_reconcilers: tuple[Callable[[bool], Mapping[str, object]], ...] = ()
    agent_session_reconcilers: tuple[Callable[[bool], Mapping[str, object]], ...] = ()
    resource_reconcilers: tuple[Callable[[bool], Mapping[str, object]], ...] = ()


class RecoveryCoordinator:
    """Reconcile only named authorities and preserve failures for inspection."""

    def __init__(self, configuration: RecoveryConfiguration) -> None:
        self.configuration = configuration

    @staticmethod
    def _component(
        component: str,
        status: str,
        *,
        configured: bool = True,
        detail: Mapping[str, object] | None = None,
        error: BaseException | None = None,
    ) -> dict[str, object]:
        result: dict[str, object] = {
            "component": component,
            "configured": configured,
            "status": status,
        }
        if detail is not None:
            result["detail"] = dict(detail)
        if error is not None:
            # Preserve classification and forensic location, never exception text.
            result["error_class"] = type(error).__name__
        return result

    def reconcile(self, *, apply: bool = False) -> dict[str, object]:
        """Run a deterministic reconciliation pass over configured authorities."""
        from .state_invariants import validate_coordination_startup

        components: list[dict[str, object]] = []
        for index, (journal_root, allowed_root) in enumerate(
            self.configuration.wal_targets
        ):
            try:
                wal = JsonWal(journal_root, allowed_root)
                detail = wal.recover() if apply else wal.inspect()
                requires_recovery = bool(detail.get("requires_recovery"))
                components.append(
                    self._component(
                        f"wal[{index}]",
                        "degraded" if requires_recovery else "healthy",
                        detail=detail,
                    )
                )
            except (OSError, ValueError, RuntimeError) as error:
                components.append(
                    self._component(f"wal[{index}]", "blocked", error=error)
                )

        for index, state_path in enumerate(self.configuration.durable_state_paths):
            try:
                try:
                    state = load_state(state_path)
                    detail: dict[str, object] = {
                        "schema_version": CURRENT_STATE_SCHEMA_VERSION,
                        "package_id": state.package_id,
                        "migrated": False,
                    }
                except DurableStateVersionError:
                    if not apply:
                        components.append(
                            self._component(
                                f"durable_state[{index}]",
                                "degraded",
                                detail={
                                    "migration_required": True,
                                    "path": str(state_path),
                                },
                            )
                        )
                        continue
                    receipt = migrate_state(state_path)
                    state = load_state(state_path)
                    detail = {
                        "schema_version": CURRENT_STATE_SCHEMA_VERSION,
                        "package_id": state.package_id,
                        "migrated": bool(receipt.get("migrated")),
                        "receipt": receipt,
                    }
                components.append(
                    self._component(f"durable_state[{index}]", "healthy", detail=detail)
                )
            except (OSError, ValueError, RuntimeError) as error:
                components.append(
                    self._component(f"durable_state[{index}]", "blocked", error=error)
                )

        try:
            invariant = validate_coordination_startup(self.configuration.project_root)
            components.append(
                self._component(
                    "coordination_invariants",
                    "healthy" if invariant.get("valid") else "blocked",
                    configured=bool(invariant.get("configured")),
                    detail=invariant,
                )
            )
        except (OSError, ValueError, RuntimeError) as error:
            components.append(
                self._component("coordination_invariants", "blocked", error=error)
            )

        callback_groups = (
            ("event_bus", self.configuration.event_bus_reconcilers),
            ("agent_sessions", self.configuration.agent_session_reconcilers),
        )
        for label, callbacks in callback_groups:
            if not callbacks:
                components.append(self._component(label, "healthy", configured=False))
            for index, callback in enumerate(callbacks):
                try:
                    detail = dict(callback(apply))
                    status = "healthy" if detail.get("valid", True) else "blocked"
                    components.append(
                        self._component(f"{label}[{index}]", status, detail=detail)
                    )
                except (OSError, ValueError, RuntimeError) as error:
                    components.append(
                        self._component(f"{label}[{index}]", "blocked", error=error)
                    )

        if not self.configuration.resource_reconcilers:
            components.append(self._component("resources", "healthy", configured=False))
        for index, callback in enumerate(self.configuration.resource_reconcilers):
            try:
                detail = dict(callback(apply))
                status = "healthy" if detail.get("valid", True) else "degraded"
                if int(detail.get("cleanup_failures", 0)):
                    status = "blocked"
                components.append(
                    self._component(f"resources[{index}]", status, detail=detail)
                )
            except (OSError, ValueError, RuntimeError) as error:
                components.append(
                    self._component(f"resources[{index}]", "blocked", error=error)
                )

        statuses = {str(item["status"]) for item in components}
        status = (
            "blocked"
            if "blocked" in statuses
            else "degraded"
            if "degraded" in statuses
            else "healthy"
        )
        report = {
            "schema_version": RECOVERY_REPORT_SCHEMA_VERSION,
            "valid": status == "healthy",
            "status": status,
            "mode": "apply" if apply else "dry_run",
            "forensic_state": "retained",
            "components": components,
        }
        report["human_summary"] = (
            f"Recovery doctor: {status}; {len(components)} component checks; "
            f"mode={report['mode']}."
        )
        return report
