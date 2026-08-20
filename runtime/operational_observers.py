"""Consent-gated, bounded operating-system observer lifecycle controls.

The adapters in this module are deliberately inert until ``enable`` receives a
valid, unexpired consent record whose scope and admitted configuration digest
match the backend.  Native commands are always passed as fixed argument vectors
to a non-shell runner.  Observer records are metadata-only; payloads, raw paths,
command lines, terminal output, and credentials are not accepted.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
from itertools import islice
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Protocol

from .contracts import ContractValidationError, validate_instance
from .file_lock import FileLock
from .operational_visibility import validate_operation_event
from .wal_transaction import JsonArtifact, JsonWal


MAX_CAPTURE_EVENTS = 10_000
MAX_CAPTURE_BYTES = 16 * 1024 * 1024
MAX_CAPTURE_SECONDS = 3_600
ALLOWED_EFFECTS = frozenset({"read", "write", "network", "process"})
ALLOWED_SCOPE_PREFIXES = (
    "process-id:",
    "executable-sha256:",
    "path-sha256:",
    "endpoint-sha256:",
    "project:",
)
OBSERVER_REGISTRY_SCHEMA = Path("contracts/operations/os-observer-registry.schema.json")
OBSERVER_REGISTRY = Path("registry/os_observer_registry.json")
WINDOWS_KERNEL_PROCESS_PROVIDER = "{22fb2cd6-0e7b-422b-a0c7-2fad1fd0e716}"
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SESSION_NAME = re.compile(r"^PacifyX-[A-Za-z0-9_-]{1,48}$")
AUDIT_KEY = re.compile(r"^pacifyx_[a-z0-9_]{1,40}$")

OBSERVER_SPECS = {
    "windows-etw": {
        "platform": "win32",
        "mechanism": "ETW",
        "route_id": "os.windows.etw",
        "commands": ("logman",),
        "privilege": "administrator_or_provider_specific_acl",
        "support_limit": (
            "Lifecycle control is implemented for the admitted kernel-process "
            "provider; event decoding requires an admitted metadata source."
        ),
    },
    "linux-audit-ebpf": {
        "platform": "linux",
        "mechanism": "Linux Audit",
        "route_id": "os.linux.audit",
        "commands": ("auditctl",),
        "privilege": "root_or_cap_audit_control",
        "support_limit": (
            "An exact directory watch is implemented; audit decoding requires "
            "an admitted metadata source and eBPF programs remain unsupported."
        ),
    },
    "macos-endpoint-security": {
        "platform": "darwin",
        "mechanism": "EndpointSecurity",
        "route_id": "os.macos.endpoint-security",
        "commands": (),
        "privilege": "signed_system_extension_and_endpointsecurity_entitlement",
        "support_limit": (
            "Unsupported without a separately signed, notarized, user-approved "
            "system extension carrying Apple's EndpointSecurity entitlement."
        ),
    },
}


def _now() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("observer time is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("observer time is invalid") from error
    if parsed.tzinfo is None:
        raise ValueError("observer time is invalid")
    return parsed.astimezone(timezone.utc)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _platform_privileged(platform: str) -> bool | None:
    if platform == "win32":
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return None
    if platform in {"linux", "darwin"}:
        geteuid = getattr(os, "geteuid", None)
        return bool(geteuid() == 0) if geteuid else None
    return None


def load_observer_registry(root: Path) -> dict[str, object]:
    """Load the versioned observer registry through its strict schema boundary."""
    value = json.loads((root / OBSERVER_REGISTRY).read_text(encoding="utf-8"))
    validate_instance(value, root / OBSERVER_REGISTRY_SCHEMA)
    return value


def validate_observer_registry(root: Path) -> dict[str, object]:
    """Validate contract shape and implementation/route semantic alignment."""
    errors: list[str] = []
    try:
        registry = load_observer_registry(root)
    except (ContractValidationError, OSError, UnicodeError, ValueError) as error:
        return {
            "schema_version": "1.0",
            "valid": False,
            "observer_count": 0,
            "errors": [str(error)],
        }
    seen: set[str] = set()
    for adapter in registry["adapters"]:  # type: ignore[index]
        observer_id = str(adapter["observer_id"])
        if observer_id in seen:
            errors.append(f"{observer_id}: duplicate observer")
        seen.add(observer_id)
        spec = OBSERVER_SPECS.get(observer_id)
        if spec is None:
            errors.append(f"{observer_id}: implementation is not admitted")
            continue
        for field in ("platform", "mechanism", "route_id"):
            if adapter[field] != spec[field]:
                errors.append(f"{observer_id}: {field} differs from implementation")
        if adapter["auto_start"] is not False:
            errors.append(f"{observer_id}: automatic start is forbidden")
        if observer_id == "macos-endpoint-security":
            if adapter["status"] != "unsupported" or adapter["command_profiles"]:
                errors.append(f"{observer_id}: unsupported boundary is overstated")
    missing = set(OBSERVER_SPECS) - seen
    errors.extend(f"{observer_id}: missing observer declaration" for observer_id in sorted(missing))
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "observer_count": len(seen),
        "errors": errors,
    }


def probe_observers(*, platform: str | None = None) -> dict[str, object]:
    """Return current, metadata-only readiness without starting a collector."""
    active_platform = platform or sys.platform
    privileged = _platform_privileged(active_platform)
    rows = []
    for observer_id, spec in OBSERVER_SPECS.items():
        matching = spec["platform"] == active_platform
        commands = {name: shutil.which(name) for name in spec["commands"]}
        available = bool(commands) and all(commands.values())
        unsupported = observer_id == "macos-endpoint-security" or not matching
        rows.append(
            {
                "observer_id": observer_id,
                "route_id": spec["route_id"],
                "mechanism": spec["mechanism"],
                "platform_match": matching,
                "privileged": privileged if matching else None,
                "commands": commands,
                "collector_available": matching and available and not unsupported,
                "configured": False,
                "consent_granted": False,
                "active": False,
                "health": "unsupported" if unsupported else "unconfigured",
                "support_limit": spec["support_limit"],
            }
        )
    return {
        "schema_version": "px.os-observer-probe/1.0",
        "platform": active_platform,
        "privileged": privileged,
        "observers": rows,
        "capture_started": False,
    }


@dataclass(frozen=True, slots=True)
class ObserverConsent:
    consent_id: str
    observer_id: str
    project_id: str
    accountable_owner: str
    granted: bool
    expires_at: str
    max_events: int
    max_bytes: int
    max_duration_seconds: int
    allowed_effects: tuple[str, ...]
    classification: str = "metadata_only"
    scope_refs: tuple[str, ...] = ()
    adapter_config_sha256: str | None = None

    def validate(
        self, *, now: datetime | None = None, require_fresh: bool = True
    ) -> None:
        if not all(
            isinstance(value, str) and value.strip() and len(value) <= 160
            for value in (
                self.consent_id,
                self.observer_id,
                self.project_id,
                self.accountable_owner,
            )
        ):
            raise ValueError("observer consent identities are required")
        if self.observer_id not in OBSERVER_SPECS:
            raise ValueError("observer consent names an unknown adapter")
        if not self.granted:
            raise PermissionError("observer consent is not granted")
        if self.classification != "metadata_only":
            raise ValueError("OS observer capture is metadata-only")
        if not 1 <= self.max_events <= MAX_CAPTURE_EVENTS:
            raise ValueError("observer event bound is invalid")
        if not 1 <= self.max_bytes <= MAX_CAPTURE_BYTES:
            raise ValueError("observer byte bound is invalid")
        if not 1 <= self.max_duration_seconds <= MAX_CAPTURE_SECONDS:
            raise ValueError("observer duration bound is invalid")
        effects = set(self.allowed_effects)
        if not effects or len(effects) != len(self.allowed_effects) or effects - ALLOWED_EFFECTS:
            raise ValueError("observer effects are empty, duplicated, or unsupported")
        if not self.scope_refs or len(self.scope_refs) > 16 or any(
            not isinstance(item, str)
            or len(item) > 200
            or not item.startswith(ALLOWED_SCOPE_PREFIXES)
            for item in self.scope_refs
        ):
            raise ValueError("observer consent requires exact opaque scope references")
        if not isinstance(self.adapter_config_sha256, str) or not HEX_SHA256.fullmatch(
            self.adapter_config_sha256
        ):
            raise ValueError("observer consent requires an admitted configuration digest")
        expiry = _parse_time(self.expires_at)
        if require_fresh and expiry <= (now or datetime.now(timezone.utc)):
            raise PermissionError("observer consent is expired")


class ObserverBackend(Protocol):
    observer_id: str

    def probe(self) -> Mapping[str, object]: ...

    def start(self, consent: ObserverConsent) -> None: ...

    def read(self, limit: int) -> Sequence[Mapping[str, object]]: ...

    def stop(self) -> None: ...

    def uninstall(self) -> None: ...


class CommandRunner(Protocol):
    def run(self, arguments: tuple[str, ...]) -> int: ...


class NonShellCommandRunner:
    """Run one admitted argument vector without a shell or captured output."""

    def run(self, arguments: tuple[str, ...]) -> int:
        completed = subprocess.run(
            arguments,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
        )
        return int(completed.returncode)


@dataclass(frozen=True, slots=True)
class ObserverCommandPlan:
    observer_id: str
    platform: str
    scope_refs: tuple[str, ...]
    commands: Mapping[str, tuple[str, ...]]
    configuration_sha256: str

    def __post_init__(self) -> None:
        if self.observer_id not in OBSERVER_SPECS:
            raise ValueError("observer plan identity is unknown")
        if self.platform != OBSERVER_SPECS[self.observer_id]["platform"]:
            raise ValueError("observer plan platform is invalid")
        if set(self.commands) != {"start", "stop", "uninstall"}:
            raise ValueError("observer plan command profiles are incomplete")
        if any(not args or not all(isinstance(arg, str) and arg for arg in args) for args in self.commands.values()):
            raise ValueError("observer plan arguments are invalid")
        if not self.scope_refs or len(self.scope_refs) > 16 or any(
            not isinstance(item, str)
            or len(item) > 200
            or not item.startswith(ALLOWED_SCOPE_PREFIXES)
            for item in self.scope_refs
        ):
            raise ValueError("observer plan scope references are invalid")
        if not HEX_SHA256.fullmatch(self.configuration_sha256):
            raise ValueError("observer plan configuration digest is invalid")


def _plan_digest(
    observer_id: str,
    scope_refs: tuple[str, ...],
    commands: Mapping[str, tuple[str, ...]],
) -> str:
    return _sha(
        {
            "schema_version": "px.os-observer-command-plan/1.0",
            "observer_id": observer_id,
            "scope_refs": list(scope_refs),
            "commands": {key: list(value) for key, value in sorted(commands.items())},
        }
    )


def build_windows_etw_plan(
    *,
    session_name: str,
    scope_refs: tuple[str, ...],
    executable: str | None = None,
) -> ObserverCommandPlan:
    """Build the only admitted ETW profile; this does not execute or start it."""
    if not SESSION_NAME.fullmatch(session_name):
        raise ValueError("ETW session name is outside the admitted profile")
    command = executable or shutil.which("logman")
    if not command:
        raise RuntimeError("ETW logman backend is unavailable")
    commands = {
        "start": (
            command,
            "create",
            "trace",
            session_name,
            "-p",
            WINDOWS_KERNEL_PROCESS_PROVIDER,
            "0xffffffffffffffff",
            "5",
            "-ets",
        ),
        "stop": (command, "stop", session_name, "-ets"),
        "uninstall": (command, "delete", session_name),
    }
    digest = _plan_digest("windows-etw", scope_refs, commands)
    return ObserverCommandPlan("windows-etw", "win32", scope_refs, commands, digest)


def build_linux_audit_plan(
    *,
    rule_key: str,
    watched_directory: Path,
    scope_refs: tuple[str, ...],
    executable: str | None = None,
) -> ObserverCommandPlan:
    """Build one exact Audit watch profile; eBPF programs are not admitted here."""
    if not AUDIT_KEY.fullmatch(rule_key):
        raise ValueError("Linux Audit key is outside the admitted profile")
    watched = watched_directory.resolve(strict=True)
    if not watched.is_dir():
        raise ValueError("Linux Audit scope must be an existing directory")
    command = executable or shutil.which("auditctl")
    if not command:
        raise RuntimeError("Linux Audit backend is unavailable")
    rule = ("-a", "always,exit", "-F", f"dir={watched}", "-F", "perm=wa", "-k", rule_key)
    remove_rule = ("-d", "always,exit", "-F", f"dir={watched}", "-F", "perm=wa", "-k", rule_key)
    commands = {
        "start": (command, *rule),
        "stop": (command, *remove_rule),
        # Uninstall means removing only the exact PACIFY-X-owned rule, never the tool.
        "uninstall": (command, *remove_rule),
    }
    digest = _plan_digest("linux-audit-ebpf", scope_refs, commands)
    return ObserverCommandPlan("linux-audit-ebpf", "linux", scope_refs, commands, digest)


class ManagedCommandObserverBackend:
    """Explicit lifecycle adapter for a fixed, admitted native command plan."""

    def __init__(
        self,
        plan: ObserverCommandPlan,
        *,
        runner: CommandRunner | None = None,
        metadata_source: Callable[[int], Sequence[Mapping[str, object]]] | None = None,
        platform: str | None = None,
        privileged: bool | None = None,
    ) -> None:
        self.plan = plan
        self.observer_id = plan.observer_id
        self.runner = runner or NonShellCommandRunner()
        self.metadata_source = metadata_source
        self.platform = platform or sys.platform
        self.privileged = _platform_privileged(self.platform) if privileged is None else privileged
        self.active = False
        self.dropped_events = 0

    def probe(self) -> Mapping[str, object]:
        executable = self.plan.commands["start"][0]
        available = Path(executable).is_file() or shutil.which(executable) is not None
        platform_match = self.platform == self.plan.platform
        return {
            "available": available and platform_match,
            "privileged": self.privileged,
            "platform_match": platform_match,
            "configured": True,
            "configuration_sha256": self.plan.configuration_sha256,
            "health": "healthy" if self.active else "unconfigured",
            "dropped_events": self.dropped_events,
            "auto_start": False,
        }

    def start(self, consent: ObserverConsent) -> None:
        consent.validate()
        if self.active:
            raise RuntimeError("observer backend is already active")
        probe = self.probe()
        if (
            probe["platform_match"] is not True
            or probe["available"] is not True
            or probe["configured"] is not True
            or probe["privileged"] is not True
            or probe["auto_start"] is not False
            or probe["configuration_sha256"] != consent.adapter_config_sha256
        ):
            raise PermissionError("observer plan is not admitted on this host")
        if consent.scope_refs != self.plan.scope_refs:
            raise PermissionError("observer consent scope differs from admitted plan")
        if self.runner.run(self.plan.commands["start"]) != 0:
            raise RuntimeError("observer native start failed")
        self.active = True

    def read(self, limit: int) -> Sequence[Mapping[str, object]]:
        if not self.active:
            raise RuntimeError("observer backend is inactive")
        return () if self.metadata_source is None else self.metadata_source(limit)

    def stop(self) -> None:
        if not self.active:
            return
        if self.runner.run(self.plan.commands["stop"]) != 0:
            raise RuntimeError("observer native stop failed")
        self.active = False

    def uninstall(self) -> None:
        if self.observer_id == "linux-audit-ebpf" and not self.active:
            # stop() already removed the one exact PX-owned rule. Never remove
            # or modify the host audit tooling itself.
            return
        if self.runner.run(self.plan.commands["uninstall"]) != 0:
            raise RuntimeError("observer native uninstall failed")
        self.active = False


class UnsupportedEndpointSecurityBackend:
    """Truthful macOS boundary: Python alone cannot provide this entitlement."""

    observer_id = "macos-endpoint-security"

    def probe(self) -> Mapping[str, object]:
        return {
            "available": False,
            "privileged": False,
            "platform_match": sys.platform == "darwin",
            "configured": False,
            "configuration_sha256": None,
            "health": "unsupported",
            "dropped_events": 0,
            "auto_start": False,
        }

    def start(self, consent: ObserverConsent) -> None:
        raise RuntimeError("macOS EndpointSecurity backend is unsupported")

    def read(self, limit: int) -> Sequence[Mapping[str, object]]:
        return ()

    def stop(self) -> None:
        return None

    def uninstall(self) -> None:
        return None


def _validate_observation(
    value: Mapping[str, object], consent: ObserverConsent
) -> dict[str, object]:
    expected = {"observation_id", "observed_at", "operation", "effect", "scope_refs"}
    if set(value) != expected:
        raise ValueError("OS observation fields are not exact")
    for field in expected - {"scope_refs"}:
        if not isinstance(value[field], str) or not str(value[field]).strip() or len(str(value[field])) > 160:
            raise ValueError("OS observation scalar fields are invalid")
    _parse_time(value["observed_at"])
    if value["effect"] not in consent.allowed_effects:
        raise PermissionError("OS observation effect exceeds consent")
    scopes = value["scope_refs"]
    if (
        not isinstance(scopes, list)
        or not scopes
        or len(scopes) > 16
        or any(
            not isinstance(item, str)
            or len(item) > 200
            or not item.startswith(ALLOWED_SCOPE_PREFIXES)
            or item not in consent.scope_refs
            for item in scopes
        )
    ):
        raise ValueError("OS observation scope exceeds exact consent")
    return dict(value)


EventEmitter = Callable[[Mapping[str, object]], object]


class OperationalObserverController:
    """Persist consented observer state and bounded loss-aware capture receipts."""

    def __init__(
        self,
        root: Path,
        allowed_root: Path,
        *,
        engine_root: Path | None = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self.allowed_root = allowed_root.resolve(strict=True)
        self.root = root.resolve()
        if not _inside(self.root, self.allowed_root) or self.root == self.allowed_root:
            raise ValueError("observer state must be below its allowed root")
        self.engine_root = (engine_root or Path(__file__).resolve().parents[1]).resolve()
        self.event_emitter = event_emitter
        self.wal = JsonWal(self.root / ".wal", self.allowed_root)
        self.backends: dict[str, ObserverBackend] = {}

    def _state_path(self, observer_id: str) -> Path:
        return self.root / "state" / f"{observer_id}.json"

    def register_backend(self, backend: ObserverBackend) -> None:
        if backend.observer_id not in OBSERVER_SPECS:
            raise ValueError("backend observer identity is unknown")
        if backend.observer_id in self.backends:
            raise ValueError("backend observer identity is duplicated")
        self.backends[backend.observer_id] = backend

    def _operation_event(
        self,
        observer_id: str,
        state: Mapping[str, object],
        action: str,
        observed_effects: Sequence[str],
    ) -> dict[str, object]:
        observed_at = _now()
        digest = _sha(state)
        event = {
            "schema_version": "px.operation-event/1",
            "event_id": f"observer-{observer_id}-{int(state['revision']):08d}-{action}",
            "correlation_id": f"observer-consent:{state['consent_id']}",
            "parent_correlation_id": None,
            "actor": {
                "actor_id": observer_id,
                "actor_kind": "operating_system",
                "session_id": str(state["consent_id"]),
                "harness": "pacify-x-os-observer",
                "accountable_owner": str(state["accountable_owner"]),
            },
            "work": {
                "project_id": str(state["project_id"]),
                "task_id": "O10",
                "claim_id": None,
                "orchestration_id": None,
            },
            "source": {
                "route_id": OBSERVER_SPECS[observer_id]["route_id"],
                "component": "runtime.operational_observers",
                "host_id": None,
                "coverage_tier": "B",
            },
            "operation": {
                "name": f"os-observer.{action}",
                "lifecycle": "failed" if action.endswith("_failed") else "completed",
                "result": "failure" if action.endswith("_failed") else "success",
            },
            "effects": {
                "declared": list(state["allowed_effects"]),
                "observed": sorted(set(observed_effects)),
                "scope_refs": list(state["scope_refs"]),
            },
            "provider": None,
            "time": {
                "observed_at": observed_at,
                "started_at": state.get("started_at"),
                "duration_ms": max(
                    0,
                    int(
                        (
                            _parse_time(observed_at)
                            - _parse_time(state["started_at"])
                        ).total_seconds()
                        * 1000
                    ),
                ),
                "freshness": "live",
            },
            "integrity": {
                "input_sha256": str(state["consent_sha256"]),
                "output_sha256": digest,
                "previous_event_sha256": None,
            },
            "capture": {"classification": "metadata_only", "payload_included": False},
        }
        validation = validate_operation_event(self.engine_root, event)
        if not validation["valid"]:
            raise ValueError("observer operation event is invalid")
        return event

    def _commit(
        self,
        observer_id: str,
        state: Mapping[str, object],
        action: str,
        *,
        observed_effects: Sequence[str] = (),
    ) -> dict[str, object]:
        event = self._operation_event(observer_id, state, action, observed_effects)
        event_sha256 = _sha(event)
        receipt = {
            "schema_version": "px.os-observer-receipt/1.0",
            "observer_id": observer_id,
            "action": action,
            "state_revision": state["revision"],
            "state_sha256": _sha(state),
            "operation_event_id": event["event_id"],
            "operation_event_sha256": event_sha256,
            "recorded_at": _now(),
        }
        transaction = self.wal.commit(
            (
                JsonArtifact("state", self._state_path(observer_id), dict(state)),
                JsonArtifact(
                    "receipt",
                    self.root / "receipts" / f"{observer_id}-{int(state['revision']):08d}-{action}.json",
                    receipt,
                ),
                JsonArtifact(
                    "event",
                    self.root / "operation-event-outbox" / f"{event['event_id']}.json",
                    event,
                ),
            ),
            transaction_id=f"observer-{observer_id}-{int(state['revision']):08d}-{action}",
        )
        delivery: dict[str, object] = {"status": "outbox_only", "error_type": None}
        if self.event_emitter is not None:
            try:
                emitted = self.event_emitter(event)
                delivery = {"status": "emitted", "error_type": None, "receipt": emitted}
            except BaseException as error:
                delivery = {"status": "failed", "error_type": type(error).__name__}
        return {**receipt, "transaction": transaction, "event_delivery": delivery}

    def _probe_backend(self, backend: ObserverBackend, consent: ObserverConsent) -> dict[str, object]:
        try:
            probe = dict(backend.probe())
        except BaseException as error:
            raise RuntimeError(f"observer backend probe failed ({type(error).__name__})") from None
        required = {
            "available",
            "privileged",
            "platform_match",
            "configured",
            "configuration_sha256",
            "health",
            "dropped_events",
            "auto_start",
        }
        if not required <= set(probe):
            raise ValueError("observer backend probe is incomplete")
        if probe["auto_start"] is not False:
            raise PermissionError("observer backend automatic start is forbidden")
        if probe["platform_match"] is not True:
            raise RuntimeError("observer backend platform does not match")
        if probe["available"] is not True:
            raise RuntimeError("observer backend is unavailable")
        if probe["configured"] is not True:
            raise RuntimeError("observer backend is not configured")
        if probe["privileged"] is not True:
            raise PermissionError("observer backend lacks required privilege")
        if probe["configuration_sha256"] != consent.adapter_config_sha256:
            raise PermissionError("observer backend configuration differs from consent")
        if not isinstance(probe["dropped_events"], int) or probe["dropped_events"] < 0:
            raise ValueError("observer backend drop counter is invalid")
        if probe["health"] not in {"healthy", "degraded", "unconfigured"}:
            raise ValueError("observer backend health is invalid")
        return probe

    def enable(self, consent: ObserverConsent) -> dict[str, object]:
        consent.validate()
        if consent.observer_id == "macos-endpoint-security":
            raise RuntimeError("macOS EndpointSecurity backend is unsupported")
        backend = self.backends.get(consent.observer_id)
        if backend is None:
            raise RuntimeError("observer backend is not installed")
        probe = self._probe_backend(backend, consent)
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(self.root / ".observer.lock", timeout_seconds=10):
            self.wal.recover()
            if self._state_path(consent.observer_id).exists():
                raise ValueError("observer already has retained state")
            try:
                backend.start(consent)
            except BaseException as error:
                raise RuntimeError(f"observer backend start failed ({type(error).__name__})") from None
            state = {
                "schema_version": "px.os-observer-state/1.0",
                "observer_id": consent.observer_id,
                "project_id": consent.project_id,
                "accountable_owner": consent.accountable_owner,
                "consent_id": consent.consent_id,
                "consent_sha256": _sha(asdict(consent)),
                "adapter_config_sha256": consent.adapter_config_sha256,
                "status": "active",
                "health": "healthy",
                "revision": 1,
                "started_at": _now(),
                "expires_at": consent.expires_at,
                "max_events": consent.max_events,
                "max_bytes": consent.max_bytes,
                "max_duration_seconds": consent.max_duration_seconds,
                "allowed_effects": list(consent.allowed_effects),
                "scope_refs": list(consent.scope_refs),
                "captured_events": 0,
                "captured_bytes": 0,
                "dropped_events": 0,
                "backend_dropped_events": int(probe["dropped_events"]),
                "last_error_type": None,
            }
            try:
                return self._commit(
                    consent.observer_id,
                    state,
                    "enable",
                    observed_effects=("process",),
                )
            except BaseException as error:
                # A native session must never outlive failure to retain its owner
                # state and receipt. This is best-effort rollback with sanitized
                # failure reporting; the process supervisor can reconcile a rare
                # rollback failure from the registered native session name.
                try:
                    backend.stop()
                except BaseException as rollback_error:
                    raise RuntimeError(
                        "observer enable commit and rollback failed "
                        f"({type(error).__name__}/{type(rollback_error).__name__})"
                    ) from None
                raise RuntimeError(
                    f"observer enable commit failed ({type(error).__name__})"
                ) from None

    def _load_active_state(self, consent: ObserverConsent) -> dict[str, object]:
        try:
            state = json.loads(self._state_path(consent.observer_id).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ValueError("observer state is unreadable") from error
        if state.get("status") != "active" or state.get("consent_sha256") != _sha(asdict(consent)):
            raise PermissionError("observer state is inactive or consent changed")
        return state

    def _expire_if_needed(
        self,
        backend: ObserverBackend,
        consent: ObserverConsent,
        state: dict[str, object],
    ) -> None:
        now = datetime.now(timezone.utc)
        elapsed = (now - _parse_time(state["started_at"])).total_seconds()
        consent_expired = _parse_time(consent.expires_at) <= now
        duration_expired = elapsed > int(state["max_duration_seconds"])
        if not consent_expired and not duration_expired:
            return
        try:
            backend.stop()
            error_type = None
            status = "expired"
            health = "unconfigured"
        except BaseException as error:
            error_type = type(error).__name__
            status = "blocked"
            health = "degraded"
        state.update(
            {
                "revision": int(state["revision"]) + 1,
                "status": status,
                "health": health,
                "last_error_type": error_type,
            }
        )
        self._commit(consent.observer_id, state, "expire")
        if error_type is not None:
            raise RuntimeError(
                f"expired observer shutdown failed ({error_type})"
            ) from None
        raise PermissionError("observer consent or capture duration has expired")

    def capture(self, consent: ObserverConsent, *, limit: int = 100) -> dict[str, object]:
        consent.validate(require_fresh=False)
        if not 1 <= limit <= 1_000:
            raise ValueError("observer read limit is invalid")
        backend = self.backends.get(consent.observer_id)
        if backend is None:
            raise RuntimeError("observer backend is not installed")
        with FileLock(self.root / ".observer.lock", timeout_seconds=10):
            self.wal.recover()
            state = self._load_active_state(consent)
            self._expire_if_needed(backend, consent, state)
            try:
                raw_records = backend.read(limit)
            except BaseException as error:
                state.update(
                    {
                        "revision": int(state["revision"]) + 1,
                        "health": "degraded",
                        "last_error_type": type(error).__name__,
                    }
                )
                self._commit(consent.observer_id, state, "capture_failed")
                raise RuntimeError(f"observer backend read failed ({type(error).__name__})") from None
            records: list[dict[str, object]] = []
            dropped = 0
            byte_count = 0
            bounded = list(islice(iter(raw_records), limit + 1))
            if len(bounded) > limit:
                dropped += 1
                bounded = bounded[:limit]
            for raw in bounded:
                try:
                    record = _validate_observation(raw, consent)
                    size = len(_canonical(record))
                except (PermissionError, TypeError, ValueError):
                    dropped += 1
                    continue
                if (
                    int(state["captured_events"]) + len(records) + 1 > consent.max_events
                    or int(state["captured_bytes"]) + byte_count + size > consent.max_bytes
                ):
                    dropped += 1
                    continue
                records.append(record)
                byte_count += size
            try:
                after_probe = dict(backend.probe())
                backend_drops = after_probe.get("dropped_events")
                if not isinstance(backend_drops, int) or backend_drops < int(state["backend_dropped_events"]):
                    raise ValueError("observer backend drop counter regressed")
                dropped += backend_drops - int(state["backend_dropped_events"])
                state["backend_dropped_events"] = backend_drops
                backend_health = after_probe.get("health")
            except BaseException as error:
                dropped += 1
                backend_health = "degraded"
                state["last_error_type"] = type(error).__name__
            observed_effects = [str(record["effect"]) for record in records]
            state.update(
                {
                    "revision": int(state["revision"]) + 1,
                    "captured_events": int(state["captured_events"]) + len(records),
                    "captured_bytes": int(state["captured_bytes"]) + byte_count,
                    "dropped_events": int(state["dropped_events"]) + dropped,
                    "health": "degraded" if dropped or backend_health == "degraded" else "healthy",
                }
            )
            receipt = self._commit(
                consent.observer_id,
                state,
                "capture",
                observed_effects=observed_effects,
            )
            return {**receipt, "observations": records, "dropped_in_batch": dropped}

    def health(self, observer_id: str) -> dict[str, object]:
        """Return bounded retained health and loss counters without observations."""
        if observer_id not in OBSERVER_SPECS:
            raise ValueError("observer identity is unknown")
        backend = self.backends.get(observer_id)
        if backend is None:
            raise RuntimeError("observer backend is not installed")
        with FileLock(self.root / ".observer.lock", timeout_seconds=10):
            self.wal.recover()
            try:
                state = json.loads(
                    self._state_path(observer_id).read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("observer state is unreadable") from error
            try:
                probe = dict(backend.probe())
                backend_health = probe.get("health")
                backend_drops = probe.get("dropped_events")
                if backend_health not in {
                    "healthy",
                    "degraded",
                    "unconfigured",
                    "unsupported",
                } or not isinstance(backend_drops, int):
                    raise ValueError("observer backend health is invalid")
                error_type = None
            except BaseException as error:
                backend_health = "unknown"
                backend_drops = None
                error_type = type(error).__name__
            return {
                "schema_version": "px.os-observer-health/1.0",
                "observer_id": observer_id,
                "status": state.get("status", "unknown"),
                "retained_health": state.get("health", "unknown"),
                "backend_health": backend_health,
                "captured_events": state.get("captured_events", 0),
                "captured_bytes": state.get("captured_bytes", 0),
                "dropped_events": state.get("dropped_events", 0),
                "backend_dropped_events": backend_drops,
                "error_type": error_type,
                "payload_included": False,
            }

    def disable(self, observer_id: str, *, uninstall: bool = False) -> dict[str, object]:
        backend = self.backends.get(observer_id)
        if backend is None:
            raise RuntimeError("observer backend is not installed")
        with FileLock(self.root / ".observer.lock", timeout_seconds=10):
            self.wal.recover()
            try:
                state = json.loads(self._state_path(observer_id).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as error:
                raise ValueError("observer state is unreadable") from error
            if state.get("status") != "active":
                raise ValueError("observer state is not active")
            try:
                backend.stop()
                if uninstall:
                    backend.uninstall()
            except BaseException as error:
                state.update(
                    {
                        "revision": int(state["revision"]) + 1,
                        "status": "blocked",
                        "health": "degraded",
                        "last_error_type": type(error).__name__,
                    }
                )
                self._commit(observer_id, state, "uninstall_failed" if uninstall else "disable_failed")
                raise RuntimeError(f"observer shutdown failed ({type(error).__name__})") from None
            state.update(
                {
                    "revision": int(state["revision"]) + 1,
                    "status": "uninstalled" if uninstall else "disabled",
                    "health": "unconfigured",
                    "last_error_type": None,
                }
            )
            return self._commit(
                observer_id,
                state,
                "uninstall" if uninstall else "disable",
                observed_effects=("process",),
            )
