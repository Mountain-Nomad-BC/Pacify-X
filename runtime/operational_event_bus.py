"""Durable local publication and replay for canonical operational events."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import threading
import time
from typing import Any, Mapping

from .file_lock import FileLock
from .operational_visibility import validate_operation_event, validate_route_registry
from .wal_transaction import JsonArtifact, JsonWal


ZERO_SHA256 = "0" * 64


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


class OperationalEventBus:
    """Publish one ordered operation stream below an explicitly bounded root."""

    def __init__(self, engine_root: Path, bus_root: Path, allowed_root: Path) -> None:
        self.engine_root = engine_root.resolve(strict=True)
        self.allowed_root = allowed_root.resolve(strict=True)
        self.root = bus_root.resolve()
        try:
            self.root.relative_to(self.allowed_root)
        except ValueError as error:
            raise ValueError("event bus root must stay below allowed root") from error
        self.wal = JsonWal(self.root / "wal", self.allowed_root)
        self._condition = threading.Condition()
        self._route_registry_identity: tuple[int, int, int] | None = None
        self._route_tiers: dict[str, str] = {}

    @property
    def _state_path(self) -> Path:
        return self.root / "state.json"

    @property
    def _head_path(self) -> Path:
        return self.root / ".authority" / "head.json"

    def _state(self) -> dict[str, object]:
        if not self._state_path.is_file():
            return {
                "schema_version": "px.operation-bus-state/1.0",
                "revision": 0,
                "event_count": 0,
                "head_sha256": ZERO_SHA256,
            }
        try:
            value = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("operational event bus state is unreadable") from error
        expected = {"schema_version", "revision", "event_count", "head_sha256"}
        if (
            not isinstance(value, dict)
            or set(value) != expected
            or value.get("schema_version") != "px.operation-bus-state/1.0"
            or not isinstance(value.get("revision"), int)
            or value.get("revision", -1) < 0
            or value.get("event_count") != value.get("revision")
            or not isinstance(value.get("head_sha256"), str)
        ):
            raise ValueError("operational event bus state is invalid")
        return value

    def _route_tier(self, route_id: str) -> str:
        path = self.engine_root / "registry/operation_route_registry.json"
        stat = path.stat()
        identity = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if identity != self._route_registry_identity:
            report = validate_route_registry(self.engine_root)
            if not report["valid"]:
                raise ValueError("operation route registry is invalid")
            registry = json.loads(path.read_text(encoding="utf-8"))
            self._route_tiers = {
                str(route["route_id"]): str(route["coverage_tier"])
                for route in registry["routes"]
            }
            self._route_registry_identity = identity
        if route_id in self._route_tiers:
            return self._route_tiers[route_id]
        raise ValueError(f"operation route is not admitted: {route_id}")

    def head(self) -> dict[str, Any]:
        """Return the current anchored event without replaying full ancestry.

        This is the operational synchronization primitive.  It validates the
        canonical state, protected head, current anchor, current event, and the
        immediately preceding link.  Full forensic ancestry remains owned by
        :meth:`replay` and is never replaced by this bounded check.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []
        envelope: dict[str, object] | None = None
        with FileLock(self.root / ".publish.lock", timeout_seconds=10):
            self.wal.recover()
            state = self._state()
            revision = int(state["revision"])
            if revision == 0:
                if self._head_path.exists():
                    errors.append("protected head exists for an empty event bus")
                return {
                    "schema_version": "px.operation-head-read/1.0",
                    "valid": not errors,
                    "revision": 0,
                    "event_sha256": None,
                    "event": None,
                    "verification_scope": "anchored-current-head",
                    "errors": errors,
                }
            try:
                envelope_path = self.root / "events" / f"{revision:08d}.json"
                envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
                event = envelope["event"]
                event_sha256 = str(envelope["event_sha256"])
                expected_head = {
                    "schema_version": "px.operation-bus-head/1.0",
                    "revision": revision,
                    "event_sha256": event_sha256,
                }
                anchor = (
                    self.root
                    / ".authority"
                    / "anchors"
                    / f"{revision:08d}-{event_sha256}.json"
                )
                if (
                    set(envelope)
                    != {"schema_version", "revision", "event_sha256", "event"}
                    or envelope["schema_version"] != "px.operation-envelope/1.0"
                    or envelope["revision"] != revision
                    or event_sha256 != _sha(event)
                    or state["head_sha256"] != event_sha256
                    or json.loads(self._head_path.read_text(encoding="utf-8"))
                    != expected_head
                    or json.loads(anchor.read_text(encoding="utf-8")) != expected_head
                ):
                    raise ValueError("current event, state, head, or anchor mismatch")
                validation = validate_operation_event(self.engine_root, event)
                if not validation["valid"]:
                    raise ValueError("current event contract invalid")
                previous_sha = event["integrity"]["previous_event_sha256"]
                if revision == 1:
                    if previous_sha is not None:
                        raise ValueError("first event has unexpected ancestry")
                else:
                    previous_path = self.root / "events" / f"{revision - 1:08d}.json"
                    previous = json.loads(previous_path.read_text(encoding="utf-8"))
                    if (
                        previous.get("schema_version") != "px.operation-envelope/1.0"
                        or previous.get("revision") != revision - 1
                        or previous.get("event_sha256") != _sha(previous.get("event"))
                        or previous_sha != previous.get("event_sha256")
                    ):
                        raise ValueError("current event previous link mismatch")
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                errors.append(str(error))
        return {
            "schema_version": "px.operation-head-read/1.0",
            "valid": not errors,
            "revision": int(state["revision"]),
            "event_sha256": None if envelope is None else envelope.get("event_sha256"),
            "event": None if envelope is None else envelope.get("event"),
            "verification_scope": "anchored-current-head",
            "errors": errors,
        }

    def publish(
        self, event: Mapping[str, object], *, link_current_head: bool = False
    ) -> dict[str, object]:
        """Validate and atomically publish one event plus all canonical projections."""
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self.root / ".publish.lock", timeout_seconds=10):
            recovery = self.wal.recover()
            state = self._state()
            operation = deepcopy(dict(event))
            source = operation.get("source")
            integrity = operation.get("integrity")
            if not isinstance(source, dict) or not isinstance(integrity, dict):
                raise ValueError("operation source and integrity must be objects")
            tier = self._route_tier(str(source.get("route_id", "")))
            if source.get("coverage_tier") != tier:
                raise ValueError("operation event coverage tier differs from registry")
            expected_previous = (
                None if state["event_count"] == 0 else state["head_sha256"]
            )
            if link_current_head:
                integrity["previous_event_sha256"] = expected_previous
            if integrity.get("previous_event_sha256") != expected_previous:
                raise ValueError("operation event previous digest differs from bus head")
            validation = validate_operation_event(self.engine_root, operation)
            if not validation["valid"]:
                raise ValueError("invalid operation event: " + "; ".join(validation["errors"]))
            revision = int(state["revision"]) + 1
            event_sha256 = _sha(operation)
            envelope = {
                "schema_version": "px.operation-envelope/1.0",
                "revision": revision,
                "event_sha256": event_sha256,
                "event": operation,
            }
            next_state = {
                "schema_version": "px.operation-bus-state/1.0",
                "revision": revision,
                "event_count": revision,
                "head_sha256": event_sha256,
            }
            head = {
                "schema_version": "px.operation-bus-head/1.0",
                "revision": revision,
                "event_sha256": event_sha256,
            }
            receipt = {
                "schema_version": "px.operation-receipt/1.0",
                "event_id": operation["event_id"],
                "correlation_id": operation["correlation_id"],
                "revision": revision,
                "event_sha256": event_sha256,
                "transaction_recovery": recovery,
            }
            projection = {
                "schema_version": "px.operation-revision/1.0",
                "revision": revision,
                "event_id": operation["event_id"],
                "lifecycle": operation["operation"]["lifecycle"],
                "result": operation["operation"]["result"],
                "event_sha256": event_sha256,
            }
            suffix = hashlib.sha256(str(operation["event_id"]).encode()).hexdigest()[:12]
            transaction_id = f"operation-{revision:08d}-{suffix}"
            artifacts = (
                JsonArtifact("event", self.root / "events" / f"{revision:08d}.json", envelope),
                JsonArtifact("receipt", self.root / "receipts" / f"{operation['event_id']}.json", receipt),
                JsonArtifact("state", self._state_path, next_state),
                JsonArtifact("state", self._head_path, head),
                JsonArtifact("state", self.root / ".authority" / "anchors" / f"{revision:08d}-{event_sha256}.json", head),
                JsonArtifact("projection", self.root / "projections" / "revision.json", projection),
            )
            transaction = self.wal.commit(artifacts, transaction_id=transaction_id)
        with self._condition:
            self._condition.notify_all()
        return {**receipt, "transaction": transaction}

    def publish_batch(
        self, events: list[Mapping[str, object]], *, link_current_head: bool = False
    ) -> list[dict[str, object]]:
        """Publish a bounded ingress batch while linking each event under the lock."""
        if len(events) > 1_000:
            raise ValueError("operational event batch exceeds 1000 events")
        return [
            self.publish(event, link_current_head=link_current_head) for event in events
        ]

    def replay(self, *, after_revision: int = 0, limit: int = 1000) -> dict[str, Any]:
        """Replay a bounded verified suffix while preserving degraded ancestry."""
        if after_revision < 0 or not 0 <= limit <= 10_000:
            raise ValueError("invalid replay boundary")
        self.root.mkdir(parents=True, exist_ok=True)
        self.wal.recover()
        records: list[dict[str, object]] = []
        errors: list[str] = []
        previous = ZERO_SHA256
        paths = sorted((self.root / "events").glob("*.json")) if (self.root / "events").is_dir() else []
        for expected, path in enumerate(paths, start=1):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if set(envelope) != {"schema_version", "revision", "event_sha256", "event"}:
                    raise ValueError("envelope fields are not exact")
                event = envelope["event"]
                expected_previous = None if expected == 1 else previous
                if (
                    envelope["schema_version"] != "px.operation-envelope/1.0"
                    or envelope["revision"] != expected
                    or path.name != f"{expected:08d}.json"
                    or envelope["event_sha256"] != _sha(event)
                    or event["integrity"]["previous_event_sha256"] != expected_previous
                ):
                    raise ValueError("event ancestry or digest mismatch")
                validation = validate_operation_event(self.engine_root, event)
                if not validation["valid"]:
                    raise ValueError("event contract invalid")
            except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
                errors.append(f"{path.name}: {error}")
                break
            previous = str(envelope["event_sha256"])
            records.append(envelope)
        state = self._state()
        if not errors and records:
            expected_head = {
                "schema_version": "px.operation-bus-head/1.0",
                "revision": len(records),
                "event_sha256": previous,
            }
            try:
                head = json.loads(self._head_path.read_text(encoding="utf-8"))
                anchor = self.root / ".authority" / "anchors" / f"{len(records):08d}-{previous}.json"
                if head != expected_head or json.loads(anchor.read_text(encoding="utf-8")) != expected_head:
                    raise ValueError("protected head or anchor mismatch")
                if state["revision"] != len(records) or state["head_sha256"] != previous:
                    raise ValueError("bus state differs from event ancestry")
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
                errors.append(str(error))
        selected = [record for record in records if int(record["revision"]) > after_revision]
        if limit:
            selected = selected[-limit:]
        else:
            selected = []
        return {
            "schema_version": "px.operation-replay/1.0",
            "valid": not errors,
            "revision": state["revision"],
            "valid_prefix_count": len(records),
            "events": selected,
            "errors": errors,
        }

    def wait_for_revision(self, after_revision: int, timeout_seconds: float) -> dict[str, Any]:
        """Wait without polling the backend and then return a verified replay delta."""
        if timeout_seconds <= 0 or timeout_seconds > 300:
            raise ValueError("subscription timeout must be between zero and 300 seconds")
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while int(self._state()["revision"]) <= after_revision:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
        return self.replay(after_revision=after_revision)
