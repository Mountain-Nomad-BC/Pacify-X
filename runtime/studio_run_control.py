"""Authenticated durable control state for Studio agent and workflow runs.

The controller records PX governance decisions without replacing host execution
authority.  Every material state change is an immutable, hash-chained event and
the mutable head is only a verified projection of that history.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from typing import Mapping
from uuid import uuid4

from .file_lock import FileLock
from .studio_authority import StudioAuthorityStore
from .studio_models import canonical_bytes, verify_safe_ancestors, write_json_atomic


RUN_STATES = frozenset(
    {
        "queued",
        "running",
        "pause_requested",
        "paused",
        "cancel_requested",
        "finalizing",
        "cancelled",
        "succeeded",
        "failed",
        "interrupted",
    }
)
TERMINAL_STATES = frozenset({"cancelled", "succeeded", "failed"})
TRANSITIONS = {
    "queued": frozenset({"running", "cancel_requested", "finalizing", "cancelled", "failed"}),
    "running": frozenset(
        {
            "running",
            "pause_requested",
            "cancel_requested",
            "finalizing",
            "succeeded",
            "failed",
            "interrupted",
        }
    ),
    "pause_requested": frozenset(
        {"paused", "cancel_requested", "finalizing", "cancelled", "failed", "interrupted"}
    ),
    "paused": frozenset({"running", "cancel_requested", "cancelled"}),
    "cancel_requested": frozenset({"finalizing", "cancelled", "failed", "interrupted"}),
    "interrupted": frozenset({"running", "cancel_requested", "cancelled"}),
    "finalizing": frozenset({"cancelled", "succeeded", "failed"}),
    "cancelled": frozenset(),
    "succeeded": frozenset(),
    "failed": frozenset(),
}


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("run-control timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("run-control timestamp lacks an offset")
    return parsed.astimezone(timezone.utc)


def _hash(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class DurableRunControl:
    """Own one bounded namespace of authenticated Studio run histories."""

    def __init__(self, project_root: Path, root: Path) -> None:
        self.project_root = project_root.resolve(strict=True)
        self.root = root
        verify_safe_ancestors(self.project_root, self.root / "placeholder")
        self.root.mkdir(parents=True, exist_ok=True)
        verify_safe_ancestors(self.project_root, self.root / "placeholder")
        self.authority = StudioAuthorityStore(self.project_root)
        self.lock_path = self.root / ".run-control.lock"

    @classmethod
    def open_existing(cls, project_root: Path, root: Path) -> "DurableRunControl":
        """Open an existing run namespace without creating locks, roots, or keys."""
        instance = cls.__new__(cls)
        instance.project_root = project_root.resolve(strict=True)
        instance.root = root
        verify_safe_ancestors(instance.project_root, instance.root / "placeholder")
        if not instance.root.is_dir() or instance.root.is_symlink():
            raise FileNotFoundError("Studio run namespace is unavailable")
        instance.authority = StudioAuthorityStore.open_existing(instance.project_root)
        instance.lock_path = instance.root / ".run-control.lock"
        return instance

    def _run_root(self, run_id: str) -> Path:
        if not run_id.startswith("run-") or not run_id[4:].isalnum():
            raise ValueError("invalid Studio run identity")
        target = self.root / run_id
        verify_safe_ancestors(self.project_root, target / "head.json")
        return target

    def _read_signed(self, path: Path) -> dict[str, object]:
        if not path.is_file():
            raise FileNotFoundError(f"durable run record is missing: {path.name}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise PermissionError("durable run record must be an object")
        return self.authority.verify_receipt(raw)

    def _read_unlocked(self, run_id: str) -> dict[str, object]:
        root = self._run_root(run_id)
        head = self._read_signed(root / "head.json")
        self._validate_head(head, expected_run_id=run_id)
        events = sorted((root / "events").glob("*.json"))
        if len(events) != int(head["sequence"]):
            raise PermissionError("durable run event sequence is incomplete")
        previous: str | None = None
        latest: dict[str, object] | None = None
        for sequence, path in enumerate(events, start=1):
            event = self._read_signed(path)
            if (
                int(event.get("sequence", 0)) != sequence
                or path.name != f"{sequence:08d}.json"
                or event.get("previous_event_sha256") != previous
            ):
                raise PermissionError("durable run event ancestry is invalid")
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            if event.get("event_sha256") != _hash(unsigned):
                raise PermissionError("durable run event identity is invalid")
            previous = str(event["event_sha256"])
            latest = event
        if latest is None or previous != head.get("last_event_sha256"):
            raise PermissionError("durable run head is not anchored to its history")
        projected = latest.get("state")
        if not isinstance(projected, Mapping) or {
            **dict(projected),
            "last_event_sha256": latest["event_sha256"],
        } != head:
            raise PermissionError("durable run head differs from canonical history")
        return dict(head)

    @staticmethod
    def _validate_head(
        head: Mapping[str, object], *, expected_run_id: str | None = None
    ) -> None:
        required = {
            "schema_version",
            "run_id",
            "kind",
            "subject_id",
            "version",
            "owner",
            "revision_sha256",
            "request_sha256",
            "state",
            "sequence",
            "created_utc",
            "updated_utc",
            "heartbeat_utc",
            "resume_count",
            "checkpoint",
            "failure",
            "authority_state",
            "last_event_sha256",
        }
        if set(head) != required:
            raise PermissionError("durable run head contract is invalid")
        if expected_run_id is not None and head.get("run_id") != expected_run_id:
            raise PermissionError("durable run identity mismatch")
        if head.get("schema_version") != "px.studio-durable-run/1.0":
            raise PermissionError("durable run schema is unsupported")
        if head.get("kind") not in {"agent", "workflow"}:
            raise PermissionError("durable run kind is invalid")
        if head.get("state") not in RUN_STATES:
            raise PermissionError("durable run state is invalid")
        if (
            not isinstance(head.get("sequence"), int)
            or int(head["sequence"]) < 1
            or not isinstance(head.get("resume_count"), int)
            or int(head["resume_count"]) < 0
            or not isinstance(head.get("checkpoint"), Mapping)
            or head.get("authority_state") != "codex-host-retained"
        ):
            raise PermissionError("durable run control fields are invalid")
        for field in ("revision_sha256", "request_sha256", "last_event_sha256"):
            value = str(head.get(field) or "")
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise PermissionError(f"durable run {field} is invalid")
        for field in ("created_utc", "updated_utc", "heartbeat_utc"):
            _parse_time(head[field])

    def create(
        self,
        *,
        kind: str,
        subject_id: str,
        version: str,
        owner: str,
        revision_sha256: str,
        request_sha256: str,
        checkpoint: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if kind not in {"agent", "workflow"} or not all(
            str(value).strip() for value in (subject_id, version, owner)
        ):
            raise ValueError("durable run identity is incomplete")
        for value in (revision_sha256, request_sha256):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
                raise ValueError("durable run content identity is invalid")
        run_id = f"run-{uuid4().hex}"
        timestamp = _now()
        provisional = {
            "schema_version": "px.studio-durable-run/1.0",
            "run_id": run_id,
            "kind": kind,
            "subject_id": subject_id,
            "version": version,
            "owner": owner,
            "revision_sha256": revision_sha256,
            "request_sha256": request_sha256,
            "state": "queued",
            "sequence": 1,
            "created_utc": timestamp,
            "updated_utc": timestamp,
            "heartbeat_utc": timestamp,
            "resume_count": 0,
            "checkpoint": dict(checkpoint or {}),
            "failure": None,
            "authority_state": "codex-host-retained",
            "last_event_sha256": "0" * 64,
        }
        with FileLock(self.lock_path, timeout_seconds=10):
            root = self._run_root(run_id)
            root.mkdir(parents=True, exist_ok=False)
            (root / "events").mkdir()
            return self._publish_unlocked(
                root, provisional, actor=owner, operation="create", previous=None
            )

    def _publish_unlocked(
        self,
        root: Path,
        state: Mapping[str, object],
        *,
        actor: str,
        operation: str,
        previous: Mapping[str, object] | None,
    ) -> dict[str, object]:
        if not actor.strip():
            raise ValueError("durable run transition requires an identified actor")
        sequence = int(state["sequence"])
        previous_hash = (
            str(previous["last_event_sha256"]) if previous is not None else None
        )
        projected_state = {
            key: value for key, value in state.items() if key != "last_event_sha256"
        }
        event_unsigned = {
            "schema_version": "px.studio-durable-run-event/1.0",
            "run_id": state["run_id"],
            "sequence": sequence,
            "operation": operation,
            "actor": actor,
            "previous_event_sha256": previous_hash,
            "state": projected_state,
            "recorded_utc": str(state["updated_utc"]),
        }
        event_sha = _hash(event_unsigned)
        next_state = {**dict(state), "last_event_sha256": event_sha}
        event = {**event_unsigned, "event_sha256": event_sha}
        signed_event = self.authority.sign_receipt(event)
        event_path = root / "events" / f"{sequence:08d}.json"
        if event_path.exists():
            raise FileExistsError("durable run event sequence already exists")
        write_json_atomic(event_path, signed_event)
        write_json_atomic(root / "head.json", self.authority.sign_receipt(next_state))
        return dict(next_state)

    def read(self, run_id: str) -> dict[str, object]:
        with FileLock(self.lock_path, timeout_seconds=10):
            return self._read_unlocked(run_id)

    def read_snapshot(self, run_id: str) -> dict[str, object]:
        """Verify an atomic durable snapshot without creating an advisory lock."""
        return self._read_unlocked(run_id)

    def list_runs(
        self,
        *,
        kind: str | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        """Return authenticated durable heads without trusting directory metadata."""
        if kind is not None and kind not in {"agent", "workflow"}:
            raise ValueError("invalid Studio run kind")
        limit = max(1, min(int(limit), 500))
        rows: list[dict[str, object]] = []
        invalid: list[dict[str, str]] = []
        with FileLock(self.lock_path, timeout_seconds=10):
            roots = sorted(
                (path for path in self.root.glob("run-*") if path.is_dir()),
                key=lambda path: path.name,
                reverse=True,
            )
            for root in roots:
                try:
                    state = self._read_unlocked(root.name)
                except (OSError, ValueError, PermissionError) as error:
                    invalid.append(
                        {
                            "run_id": root.name,
                            "error": type(error).__name__,
                            "message": str(error)[:300],
                        }
                    )
                    continue
                if kind is not None and state.get("kind") != kind:
                    continue
                rows.append(state)
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        page = rows[:limit]
        return {
            "schema_version": "px.studio-run-list/1.0",
            "kind": kind or "all",
            "runs": page,
            "returned": len(page),
            "total_authenticated": len(rows),
            "has_more": len(rows) > len(page),
            "invalid": invalid,
        }

    def list_snapshots(
        self, *, kind: str | None = None, limit: int = 100
    ) -> dict[str, object]:
        """List verified atomic heads without creating or updating lock state."""
        if kind is not None and kind not in {"agent", "workflow"}:
            raise ValueError("invalid Studio run kind")
        limit = max(1, min(int(limit), 500))
        rows: list[dict[str, object]] = []
        invalid: list[dict[str, str]] = []
        roots = sorted(
            (path for path in self.root.glob("run-*") if path.is_dir() and not path.is_symlink()),
            key=lambda path: path.name,
            reverse=True,
        )[:500]
        for root in roots:
            try:
                state = self._read_unlocked(root.name)
            except (OSError, ValueError, PermissionError) as error:
                invalid.append({"run_id": root.name, "error": type(error).__name__, "message": str(error)[:300]})
                continue
            if kind is None or state.get("kind") == kind:
                rows.append(state)
        rows.sort(key=lambda row: str(row.get("updated_utc") or ""), reverse=True)
        return {
            "schema_version": "px.studio-run-list/1.0",
            "kind": kind or "all",
            "runs": rows[:limit],
            "returned": min(len(rows), limit),
            "total_authenticated": len(rows),
            "has_more": len(rows) > limit,
            "invalid": invalid,
        }

    def _recover_projection_unlocked(
        self, run_id: str
    ) -> tuple[dict[str, object], bool]:
        """Repair only one provable event-ahead-of-head crash window.

        Events are published before the replaceable head.  Therefore exactly one
        authenticated trailing event is a valid interrupted publication.  Any
        other difference is ambiguous and remains fail-closed.
        """
        root = self._run_root(run_id)
        head_path = root / "head.json"
        events = sorted((root / "events").glob("*.json"))
        if head_path.is_file():
            head = self._read_signed(head_path)
            self._validate_head(head, expected_run_id=run_id)
            expected_count = int(head["sequence"])
            if len(events) == expected_count:
                return self._read_unlocked(run_id), False
            if len(events) != expected_count + 1:
                raise PermissionError(
                    "durable run divergence exceeds one trailing event"
                )
        else:
            head = None
            expected_count = 0
            if len(events) != 1:
                raise PermissionError(
                    "durable run missing-head recovery requires exactly one event"
                )

        previous_hash: str | None = None
        previous_state: dict[str, object] | None = None
        trailing: dict[str, object] | None = None
        for sequence, path in enumerate(events, start=1):
            event = self._read_signed(path)
            unsigned = {
                key: value for key, value in event.items() if key != "event_sha256"
            }
            if (
                int(event.get("sequence", 0)) != sequence
                or path.name != f"{sequence:08d}.json"
                or event.get("previous_event_sha256") != previous_hash
                or event.get("event_sha256") != _hash(unsigned)
            ):
                raise PermissionError(
                    "durable run trailing event authentication or ancestry is invalid"
                )
            projected = event.get("state")
            if not isinstance(projected, Mapping):
                raise PermissionError("durable run event projection is invalid")
            candidate = {
                **dict(projected),
                "last_event_sha256": event["event_sha256"],
            }
            self._validate_head(candidate, expected_run_id=run_id)
            if sequence == expected_count:
                if head is None or candidate != head:
                    raise PermissionError(
                        "durable run retained head is not its event projection"
                    )
                previous_state = candidate
            elif sequence == expected_count + 1:
                trailing = candidate
            previous_hash = str(event["event_sha256"])

        if trailing is None:
            raise PermissionError("durable run trailing event is unavailable")
        if head is None:
            if (
                trailing["sequence"] != 1
                or trailing["state"] != "queued"
                or events[0].name != "00000001.json"
            ):
                raise PermissionError("durable run initial event cannot restore a head")
        else:
            if previous_state != head:
                raise PermissionError("durable run recovery base is not current")
            immutable = (
                "schema_version",
                "run_id",
                "kind",
                "subject_id",
                "version",
                "owner",
                "revision_sha256",
                "request_sha256",
                "created_utc",
                "authority_state",
            )
            if any(trailing[field] != head[field] for field in immutable):
                raise PermissionError("durable run trailing event changes immutable identity")
            if trailing["state"] not in TRANSITIONS[str(head["state"])]:
                raise PermissionError("durable run trailing event transition is illegal")
            if int(trailing["sequence"]) != int(head["sequence"]) + 1:
                raise PermissionError("durable run trailing event sequence is invalid")

        write_json_atomic(head_path, self.authority.sign_receipt(trailing))
        return self._read_unlocked(run_id), True

    def recover_projection(
        self, run_id: str, *, actor: str, approved: bool
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError(
                "durable run projection recovery requires explicit host approval"
            )
        if not actor.strip():
            raise ValueError("durable run projection recovery requires an actor")
        with FileLock(self.lock_path, timeout_seconds=10):
            state, repaired = self._recover_projection_unlocked(run_id)
            receipt = {
                "schema_version": "px.studio-run-projection-recovery/1.0",
                "run_id": run_id,
                "projection_repaired": repaired,
                "state": state["state"],
                "sequence": state["sequence"],
                "recovered_by": actor,
                "authority_state": "codex-host-retained",
            }
            if repaired:
                signed = self.authority.sign_receipt(receipt)
                receipt_path = (
                    self._run_root(run_id)
                    / "recovery-receipts"
                    / f"{int(state['sequence']):08d}-{state['last_event_sha256']}.json"
                )
                write_json_atomic(receipt_path, signed)
                receipt["receipt"] = receipt_path.relative_to(
                    self.project_root
                ).as_posix()
            return receipt

    def peek(self, run_id: str) -> dict[str, object]:
        """Read the authenticated head cheaply for a hot cancellation poll."""
        with FileLock(self.lock_path, timeout_seconds=10):
            head = self._read_signed(self._run_root(run_id) / "head.json")
            self._validate_head(head, expected_run_id=run_id)
            return head

    def transition(
        self,
        run_id: str,
        target: str,
        *,
        actor: str,
        approved: bool,
        checkpoint: Mapping[str, object] | None = None,
        failure: Mapping[str, object] | None = None,
        operation: str | None = None,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("durable run transition requires explicit host approval")
        if target not in RUN_STATES:
            raise ValueError("unsupported durable run state")
        with FileLock(self.lock_path, timeout_seconds=10):
            current = self._read_unlocked(run_id)
            if target not in TRANSITIONS[str(current["state"])]:
                raise ValueError(
                    f"illegal durable run transition: {current['state']} -> {target}"
                )
            timestamp = _now()
            next_state = {
                **current,
                "state": target,
                "sequence": int(current["sequence"]) + 1,
                "updated_utc": timestamp,
                "heartbeat_utc": timestamp,
                "checkpoint": dict(
                    checkpoint if checkpoint is not None else current["checkpoint"]
                ),
                "failure": dict(failure) if failure is not None else None,
                "resume_count": int(current["resume_count"])
                + (1 if target == "running" and current["state"] in {"paused", "interrupted"} else 0),
                "last_event_sha256": current["last_event_sha256"],
            }
            return self._publish_unlocked(
                self._run_root(run_id),
                next_state,
                actor=actor,
                operation=operation or f"transition.{target}",
                previous=current,
            )

    def heartbeat(
        self,
        run_id: str,
        *,
        actor: str,
        checkpoint: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        with FileLock(self.lock_path, timeout_seconds=10):
            current = self._read_unlocked(run_id)
            if current["state"] != "running":
                return current
            timestamp = _now()
            next_state = {
                **current,
                "sequence": int(current["sequence"]) + 1,
                "updated_utc": timestamp,
                "heartbeat_utc": timestamp,
                "checkpoint": dict(
                    checkpoint if checkpoint is not None else current["checkpoint"]
                ),
            }
            return self._publish_unlocked(
                self._run_root(run_id),
                next_state,
                actor=actor,
                operation="heartbeat",
                previous=current,
            )

    def reconcile(
        self,
        *,
        actor: str,
        approved: bool,
        stale_after_seconds: float = 60.0,
    ) -> dict[str, object]:
        if not approved:
            raise PermissionError("run reconciliation requires explicit host approval")
        if stale_after_seconds < 1:
            raise ValueError("run reconciliation stale bound must be positive")
        checked = interrupted = 0
        projection_repairs = 0
        now = datetime.now(timezone.utc)
        for root in sorted(self.root.glob("run-*")):
            if not root.is_dir():
                continue
            projection = self.recover_projection(
                root.name, actor=actor, approved=True
            )
            projection_repairs += int(projection["projection_repaired"] is True)
            state = self.read(root.name)
            checked += 1
            if state["state"] not in {"running", "pause_requested", "cancel_requested"}:
                continue
            age = (now - _parse_time(state["heartbeat_utc"])).total_seconds()
            if age <= stale_after_seconds:
                continue
            self.transition(
                root.name,
                "interrupted",
                actor=actor,
                approved=True,
                failure={
                    "code": "OWNER_HEARTBEAT_STALE",
                    "heartbeat_age_seconds": round(age, 3),
                    "recovery": "resume requires fresh explicit host approval and identical request identity",
                },
                operation="reconcile.interrupted",
            )
            interrupted += 1
        return {
            "schema_version": "px.studio-run-reconciliation/1.0",
            "checked": checked,
            "interrupted": interrupted,
            "projection_repairs": projection_repairs,
            "valid": True,
            "authority_state": "codex-host-retained",
        }


class DurableControlSignal:
    """ProcessSupervisor cancellation-token adapter backed by durable state."""

    def __init__(
        self,
        control: DurableRunControl,
        run_id: str,
        *,
        heartbeat_interval_seconds: float = 15.0,
    ) -> None:
        self.control = control
        self.run_id = run_id
        self.requested_state: str | None = None
        self.heartbeat_interval_seconds = max(1.0, heartbeat_interval_seconds)
        self._last_heartbeat = time.monotonic()

    def is_set(self) -> bool:
        state = self.control.peek(self.run_id)
        current = str(state["state"])
        if current in {"pause_requested", "cancel_requested"}:
            self.requested_state = current
            return True
        now = time.monotonic()
        if current == "running" and now - self._last_heartbeat >= self.heartbeat_interval_seconds:
            self.control.heartbeat(
                self.run_id,
                actor=str(state["owner"]),
                checkpoint=state["checkpoint"],
            )
            self._last_heartbeat = now
        return False
