"""Native projection custody seams; no producer or OS process is launched."""
from types import SimpleNamespace
import pytest
from scripts import regenerate_projections as driver
from runtime import operational_gap_ledger, process_supervisor, resource_lifecycle
from runtime.gremlin import enrollment


@pytest.fixture
def native_host_fixture(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    monkeypatch.setattr(driver, "_host_configuration_digest", lambda: "c" * 64)
    monkeypatch.setattr(driver, "_sandbox_digest", lambda: "b" * 64)
    monkeypatch.setattr(driver, "admit_driver", lambda value: None)
    admission = {"event_id": "fixture-admission", "event_sha256": "a" * 64,
                 "sequence": 12, "session_id": "fixture-session", "actor": "fixture-owner",
                 "gap_id": "fixture-gap", "effect_scopes": [{"effect": "read",
                 "scope": [".agentic_engineering_os_px/sandbox", ".agentic_engineering_os_px/runtime-core",
                           ".agentic_engineering_os_px/studios/authority", (tmp_path / "host-keys").as_posix()]}]}
    monkeypatch.setattr(operational_gap_ledger, "read_snapshot", lambda root: {"work_admissions": [admission]})
    monkeypatch.setattr(operational_gap_ledger, "guard_work_admission", lambda *a, **kw: {"valid": True})
    calls = []
    manager = SimpleNamespace(_processes={}, _process_jobs={}, _failed_creation_custody={}, _supervision_failures={})
    def create(parent, **metadata):
        path = parent / "registered-workspace"
        path.mkdir()
        calls.append(("workspace", metadata))
        return SimpleNamespace(resource_id="workspace-id", path=str(path))
    manager.create_workspace = create
    manager.update = lambda *args, **kwargs: calls.append(("update", args, kwargs))
    manager.reclaim = lambda *args, **kwargs: SimpleNamespace(resources_reclaimed=1, errors=[], cleanup_id="cleanup-id")
    monkeypatch.setattr(resource_lifecycle, "ResourceManager", lambda path: manager)
    nanny = SimpleNamespace(sandbox_policy_sha256="b" * 64, close_supervised_execution=lambda *args: calls.append(("closed", args)))
    monkeypatch.setattr(driver, "_configured_host", lambda: SimpleNamespace(nanny=nanny))
    monkeypatch.setattr(enrollment, "enroll_supervised_process", lambda *args, **kwargs: calls.append(("enrolled", args, kwargs)) or SimpleNamespace())
    capture = {}
    class Supervisor:
        def __init__(self, owner):
            assert owner is manager
        def run(self, command, **kwargs):
            capture.update(command=command, **kwargs)
            kwargs["assert_execution_current"](kwargs["execution_context"])
            kwargs["before_release"](SimpleNamespace(parent_resource_id="process-id"))
            return SimpleNamespace(exit_code=0, status="exited", tree_closed=True, resource_id="process-id",
                receipt_path="native-process-receipt.json", stdout=SimpleNamespace(text="normal output"),
                stderr=SimpleNamespace(text=""))
    monkeypatch.setattr(process_supervisor, "ProcessSupervisor", Supervisor)
    return manager, calls, capture


def test_configured_native_host_owns_release_context_and_cleanup(native_host_fixture):
    manager, calls, capture = native_host_fixture
    result = driver.run("index", "scripts/owner.py", (), admission_event_id="fixture-admission")
    assert capture["parent_resource_id"] == "workspace-id"
    assert capture["execution_context"].authority_reference_sha256 == "a" * 64
    assert capture["execution_context"].session_id == "fixture-session"
    assert capture["execution_context"].revision == 12
    assert capture["execution_context"].epoch == 12
    assert capture["deadline"] > 0
    assert calls[1][0] == "enrolled" and calls[2][0] == "closed"
    assert result["tree_closed"] and result["supervision_receipt"] == "native-process-receipt.json"
    assert result["workspace_cleanup_id"] == "cleanup-id"


def test_missing_commissioned_host_creates_no_workspace_or_process(native_host_fixture, monkeypatch):
    _, calls, capture = native_host_fixture
    def unavailable():
        raise ValueError("real commissioned host is unavailable")
    monkeypatch.setattr(driver, "_configured_host", unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        driver.run("index", "scripts/owner.py", (), admission_event_id="fixture-admission")
    assert calls == [] and capture == {}


def test_uncertain_native_custody_retains_real_owner_and_blocks_cleanup(native_host_fixture):
    manager, calls, _ = native_host_fixture
    manager._supervision_failures["actual-retained-owner"] = object()
    try:
        with pytest.raises(RuntimeError, match="retained process custody"):
            driver.run("index", "scripts/owner.py", (), admission_event_id="fixture-admission")
        retained = next(iter(driver.RETAINED_PROCESS_CUSTODY.values()))
        assert retained["manager"] is manager
        assert not any(call[0] == "update" for call in calls)
    finally:
        driver.RETAINED_PROCESS_CUSTODY.clear()


@pytest.mark.parametrize("configuration_present", [False, True])
def test_uncommissioned_host_loader_never_initializes_studio_identity_or_keys(tmp_path, monkeypatch, configuration_present):
    from runtime.gremlin.host_configuration import load_configured_gremlin_runtime, CONFIGURATION_RELATIVE
    monkeypatch.setenv("PX_STUDIO_KEY_ROOT", str(tmp_path / "host-keys"))
    if configuration_present:
        configuration = tmp_path / CONFIGURATION_RELATIVE
        configuration.parent.mkdir(parents=True)
        configuration.write_text('{"authentication":{},"schema_version":"uncommissioned"}')
    before = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises((FileNotFoundError, ValueError)):
        load_configured_gremlin_runtime(tmp_path, recovery_verifier=SimpleNamespace(verify=lambda *args: None))
    after = {path.relative_to(tmp_path).as_posix(): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before
    assert not (tmp_path / ".agentic_engineering_os_px/studios").exists()
    assert not (tmp_path / "host-keys").exists()


def test_changed_commissioned_host_or_policy_prevents_workspace_creation(native_host_fixture, monkeypatch):
    _, calls, capture = native_host_fixture
    monkeypatch.setattr(driver, "_sandbox_digest", lambda: "d" * 64)
    with pytest.raises(PermissionError, match="became stale"):
        driver.run("index", "scripts/owner.py", (), admission_event_id="fixture-admission")
    assert calls == [] and capture == {}


def test_cancelled_projection_creates_no_workspace_or_process(native_host_fixture):
    import threading
    _, calls, capture = native_host_fixture
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(PermissionError, match="cancelled"):
        driver.run("index", "scripts/owner.py", (), admission_event_id="fixture-admission", cancel_event=cancelled)
    assert calls == [] and capture == {}
