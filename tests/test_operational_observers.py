from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from runtime.operational_observers import (
    ManagedCommandObserverBackend,
    ObserverConsent,
    OperationalObserverController,
    UnsupportedEndpointSecurityBackend,
    build_linux_audit_plan,
    build_windows_etw_plan,
    probe_observers,
    validate_observer_registry,
)
from runtime.operational_visibility import (
    validate_operation_event,
    validate_route_registry,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG_SHA = "b" * 64
SCOPES = ("process-id:42", "executable-sha256:" + "a" * 64)


class FakeBackend:
    observer_id = "windows-etw"

    def __init__(self) -> None:
        self.available = True
        self.privileged = True
        self.platform_match = True
        self.configured = True
        self.configuration_sha256 = CONFIG_SHA
        self.auto_start = False
        self.health = "unconfigured"
        self.dropped_events = 0
        self.started = False
        self.stopped = False
        self.uninstalled = False
        self.records: list[dict[str, object]] = []
        self.fail_on: str | None = None

    def probe(self) -> dict[str, object]:
        if self.fail_on == "probe":
            raise RuntimeError("secret probe details")
        return {
            "available": self.available,
            "privileged": self.privileged,
            "platform_match": self.platform_match,
            "configured": self.configured,
            "configuration_sha256": self.configuration_sha256,
            "health": self.health,
            "dropped_events": self.dropped_events,
            "auto_start": self.auto_start,
        }

    def start(self, consent: ObserverConsent) -> None:
        if self.fail_on == "start":
            raise RuntimeError("secret start details")
        self.started = True
        self.health = "healthy"

    def read(self, limit: int) -> list[dict[str, object]]:
        if self.fail_on == "read":
            raise RuntimeError("secret read details")
        return self.records

    def stop(self) -> None:
        if self.fail_on == "stop":
            raise RuntimeError("secret stop details")
        self.stopped = True
        self.health = "unconfigured"

    def uninstall(self) -> None:
        if self.fail_on == "uninstall":
            raise RuntimeError("secret uninstall details")
        self.uninstalled = True


class FakeRunner:
    def __init__(self, return_code: int = 0) -> None:
        self.return_code = return_code
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: tuple[str, ...]) -> int:
        self.calls.append(arguments)
        return self.return_code


def _consent(**changes: object) -> ObserverConsent:
    value = ObserverConsent(
        consent_id="consent-1",
        observer_id="windows-etw",
        project_id="project-1",
        accountable_owner="owner-1",
        granted=True,
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        max_events=2,
        max_bytes=4_096,
        max_duration_seconds=300,
        allowed_effects=("read", "write", "process"),
        scope_refs=SCOPES,
        adapter_config_sha256=CONFIG_SHA,
    )
    return replace(value, **changes)


def _record(identifier: str, *, effect: str = "process") -> dict[str, object]:
    return {
        "observation_id": identifier,
        "observed_at": "2026-08-11T12:00:00Z",
        "operation": "process-start",
        "effect": effect,
        "scope_refs": list(SCOPES),
    }


def _controller(
    tmp_path: Path, *, emitter=None
) -> tuple[OperationalObserverController, FakeBackend]:
    allowed = tmp_path / "state"
    allowed.mkdir()
    controller = OperationalObserverController(
        allowed / "observers", allowed, engine_root=ROOT, event_emitter=emitter
    )
    backend = FakeBackend()
    controller.register_backend(backend)
    return controller, backend


def test_registry_and_route_claims_are_strict_and_honest() -> None:
    assert validate_observer_registry(ROOT) == {
        "schema_version": "1.0",
        "valid": True,
        "observer_count": 3,
        "errors": [],
    }
    routes = json.loads((ROOT / "registry/operation_route_registry.json").read_text())
    by_id = {row["route_id"]: row for row in routes["routes"]}
    assert by_id["os.windows.etw"]["coverage_tier"] == "B"
    assert by_id["os.linux.audit"]["instrumentation"]["kind"] == "observer"
    assert by_id["os.macos.endpoint-security"]["status"] == "unsupported"
    assert by_id["os.macos.endpoint-security"]["coverage_tier"] == "D"
    assert validate_route_registry(ROOT)["valid"] is True


def test_probe_is_read_only_and_reports_platform_limits() -> None:
    report = probe_observers(platform="win32")
    assert report["capture_started"] is False
    assert len(report["observers"]) == 3
    windows = next(row for row in report["observers"] if row["observer_id"] == "windows-etw")
    macos = next(row for row in report["observers"] if row["observer_id"] == "macos-endpoint-security")
    assert windows["health"] == "unconfigured"
    assert windows["active"] is False
    assert macos["health"] == "unsupported"
    assert "signed" in macos["support_limit"]
    assert "EndpointSecurity entitlement" in macos["support_limit"]


@pytest.mark.parametrize(
    ("attribute", "value", "error"),
    [
        ("privileged", False, "privilege"),
        ("available", False, "unavailable"),
        ("platform_match", False, "platform"),
        ("configured", False, "not configured"),
        ("configuration_sha256", "c" * 64, "configuration differs"),
        ("auto_start", True, "automatic start"),
    ],
)
def test_consent_platform_privilege_and_backend_checks_fail_closed(
    tmp_path: Path, attribute: str, value: object, error: str
) -> None:
    controller, backend = _controller(tmp_path)
    setattr(backend, attribute, value)
    with pytest.raises((PermissionError, RuntimeError), match=error):
        controller.enable(_consent())
    assert backend.started is False


def test_consent_requires_grant_scope_bounds_and_configuration() -> None:
    with pytest.raises(PermissionError, match="not granted"):
        _consent(granted=False).validate()
    with pytest.raises(ValueError, match="exact opaque scope"):
        _consent(scope_refs=()).validate()
    with pytest.raises(ValueError, match="configuration digest"):
        _consent(adapter_config_sha256=None).validate()
    with pytest.raises(ValueError, match="metadata-only"):
        _consent(classification="content_authorized").validate()
    with pytest.raises(PermissionError, match="expired"):
        _consent(
            expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        ).validate()


def test_capture_is_bounded_metadata_only_loss_aware_and_emits_canonical_event(
    tmp_path: Path,
) -> None:
    emitted: list[dict[str, object]] = []
    controller, backend = _controller(tmp_path, emitter=lambda event: emitted.append(dict(event)))
    consent = _consent()
    controller.enable(consent)
    backend.records = [
        _record("one"),
        _record("raw-path") | {"scope_refs": ["path:C:/secret.txt"]},
        _record("wrong-effect", effect="network"),
        _record("two"),
        _record("over-budget"),
    ]
    backend.dropped_events = 2
    receipt = controller.capture(consent, limit=10)
    assert [row["observation_id"] for row in receipt["observations"]] == ["one", "two"]
    assert receipt["dropped_in_batch"] == 5
    state = json.loads((controller.root / "state/windows-etw.json").read_text())
    assert state["captured_events"] == 2
    assert state["dropped_events"] == 5
    assert state["backend_dropped_events"] == 2
    assert state["health"] == "degraded"
    assert len(emitted) == 2
    assert validate_operation_event(ROOT, emitted[-1])["valid"] is True
    assert emitted[-1]["capture"] == {"classification": "metadata_only", "payload_included": False}
    assert receipt["event_delivery"]["status"] == "emitted"
    assert len(list((controller.root / "operation-event-outbox").glob("*.json"))) == 2


def test_backend_read_and_emitter_failures_are_sanitized_and_receipted(tmp_path: Path) -> None:
    def fail_emitter(event: object) -> None:
        raise RuntimeError("secret emitter payload")

    controller, backend = _controller(tmp_path, emitter=fail_emitter)
    consent = _consent()
    enabled = controller.enable(consent)
    assert enabled["event_delivery"] == {"status": "failed", "error_type": "RuntimeError"}
    backend.fail_on = "read"
    with pytest.raises(RuntimeError) as raised:
        controller.capture(consent)
    assert "secret read details" not in str(raised.value)
    state = json.loads((controller.root / "state/windows-etw.json").read_text())
    assert state["health"] == "degraded"
    assert state["last_error_type"] == "RuntimeError"
    assert any("capture_failed" in path.name for path in (controller.root / "receipts").glob("*.json"))
    failed_event = json.loads(
        next(
            path
            for path in (controller.root / "operation-event-outbox").glob("*.json")
            if "capture_failed" in path.name
        ).read_text()
    )
    assert failed_event["operation"]["result"] == "failure"


def test_enable_wal_failure_stops_new_native_session(tmp_path: Path) -> None:
    controller, backend = _controller(tmp_path)

    def fail_commit(*args: object, **kwargs: object) -> dict[str, object]:
        raise OSError("secret disk path")

    controller._commit = fail_commit  # type: ignore[method-assign]
    with pytest.raises(RuntimeError) as raised:
        controller.enable(_consent())
    assert "secret disk path" not in str(raised.value)
    assert backend.started is True
    assert backend.stopped is True


def test_consent_change_and_duration_expiry_block_capture_and_stop_backend(
    tmp_path: Path,
) -> None:
    controller, backend = _controller(tmp_path)
    consent = _consent()
    controller.enable(consent)
    with pytest.raises(PermissionError, match="consent changed"):
        controller.capture(replace(consent, consent_id="other"))
    path = controller.root / "state/windows-etw.json"
    state = json.loads(path.read_text())
    state["started_at"] = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(PermissionError, match="duration"):
        controller.capture(consent)
    assert backend.stopped is True
    expired_state = json.loads(path.read_text())
    assert expired_state["status"] == "expired"


def test_disable_and_uninstall_are_explicit_receipted_and_leave_no_session(tmp_path: Path) -> None:
    controller, backend = _controller(tmp_path)
    controller.enable(_consent())
    disabled = controller.disable("windows-etw", uninstall=True)
    assert disabled["action"] == "uninstall"
    assert backend.stopped is True
    assert backend.uninstalled is True
    state = json.loads((controller.root / "state/windows-etw.json").read_text())
    assert state["status"] == "uninstalled"
    assert len(list((controller.root / "receipts").glob("*.json"))) == 2
    health = controller.health("windows-etw")
    assert health["status"] == "uninstalled"
    assert health["payload_included"] is False
    assert health["backend_health"] == "unconfigured"


def test_fixed_windows_plan_uses_non_shell_runner_only_after_explicit_enable(tmp_path: Path) -> None:
    executable = tmp_path / "logman.exe"
    executable.write_bytes(b"fake")
    scope = ("project:px",)
    plan = build_windows_etw_plan(
        session_name="PacifyX-test", scope_refs=scope, executable=str(executable)
    )
    runner = FakeRunner()
    backend = ManagedCommandObserverBackend(
        plan, runner=runner, platform="win32", privileged=True
    )
    assert runner.calls == []
    allowed = tmp_path / "managed"
    allowed.mkdir()
    controller = OperationalObserverController(allowed / "state", allowed, engine_root=ROOT)
    controller.register_backend(backend)
    consent = replace(
        _consent(), scope_refs=scope, adapter_config_sha256=plan.configuration_sha256
    )
    controller.enable(consent)
    controller.disable("windows-etw", uninstall=True)
    assert runner.calls == [plan.commands["start"], plan.commands["stop"], plan.commands["uninstall"]]
    assert backend.active is False
    assert all(isinstance(call, tuple) for call in runner.calls)


def test_fixed_linux_plan_removes_only_exact_rule_and_never_uninstalls_tool(tmp_path: Path) -> None:
    executable = tmp_path / "auditctl"
    executable.write_bytes(b"fake")
    watched = tmp_path / "watched"
    watched.mkdir()
    scope = ("path-sha256:" + "d" * 64,)
    plan = build_linux_audit_plan(
        rule_key="pacifyx_test",
        watched_directory=watched,
        scope_refs=scope,
        executable=str(executable),
    )
    runner = FakeRunner()
    backend = ManagedCommandObserverBackend(plan, runner=runner, platform="linux", privileged=True)
    consent = replace(
        _consent(),
        observer_id="linux-audit-ebpf",
        scope_refs=scope,
        adapter_config_sha256=plan.configuration_sha256,
    )
    backend.start(consent)
    backend.stop()
    backend.uninstall()
    assert runner.calls == [plan.commands["start"], plan.commands["stop"]]
    assert f"dir={watched.resolve()}" in plan.commands["start"]
    assert plan.commands["stop"][1] == "-d"
    assert backend.active is False


def test_macos_endpoint_security_is_not_faked(tmp_path: Path) -> None:
    backend = UnsupportedEndpointSecurityBackend()
    assert backend.probe()["health"] == "unsupported"
    with pytest.raises(RuntimeError, match="unsupported"):
        backend.start(replace(_consent(), observer_id="macos-endpoint-security"))
    controller, _ = _controller(tmp_path)
    controller.register_backend(backend)
    with pytest.raises(RuntimeError, match="unsupported"):
        controller.enable(replace(_consent(), observer_id="macos-endpoint-security"))


def test_probe_and_shutdown_failures_never_expose_backend_details(tmp_path: Path) -> None:
    controller, backend = _controller(tmp_path)
    backend.fail_on = "probe"
    with pytest.raises(RuntimeError) as raised:
        controller.enable(_consent())
    assert "secret probe details" not in str(raised.value)
    backend.fail_on = None
    controller.enable(_consent())
    backend.fail_on = "stop"
    with pytest.raises(RuntimeError) as raised:
        controller.disable("windows-etw")
    assert "secret stop details" not in str(raised.value)
    state = json.loads((controller.root / "state/windows-etw.json").read_text())
    assert state["status"] == "blocked"
