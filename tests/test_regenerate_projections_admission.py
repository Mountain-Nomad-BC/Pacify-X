"""Projection routing tests never invoke builders, processes, or publication."""
import pytest
from scripts import regenerate_projections as driver


@pytest.mark.parametrize("mode", ["relative", "absolute", "mixed", "sibling"])
def test_native_execute_scopes_use_physical_component_containment(tmp_path, monkeypatch, mode):
    from runtime.operational_gap_ledger import append_event
    from tests.test_operational_gap_ledger import initialize, card, evidence

    initialize(tmp_path)
    append_event(tmp_path, "card_discovered", card(), actor="unit")
    checkpoint = append_event(tmp_path, "work_checkpoint", {
        "active_gap_id": "PX-GAP-0001", "learned": "Native driver scope fixture.",
        "next_action": card()["next_action"], "unresolved_branch_gap_ids": [],
        "newly_discovered_gap_ids": [], "evidence": evidence("unit"),
    }, actor="unit")
    write = ["registry", ".agentic_engineering_os_px/runtime-core", ".agentic_engineering_os_px/resource-lifecycle"]
    execute = ["scripts"]
    if mode == "absolute":
        write = [str(tmp_path / path) for path in write]
        execute = [str(tmp_path / "scripts")]
    elif mode == "mixed":
        execute = [str(tmp_path / "scripts"), "unused"]
    elif mode == "sibling":
        execute = [str(tmp_path / "scripts-other")]
    admission = append_event(tmp_path, "work_admitted", {
        "gap_id": "PX-GAP-0001", "checkpoint_event_id": checkpoint["event_id"],
        "session_id": "pxsession.driver-unit", "expires_utc": "2099-01-01T00:00:00Z",
        "effect_scopes": [{"effect": "write", "scope": write}, {"effect": "execute", "scope": execute}],
        "authority": "Disposable driver fixture only.", "expected_effect": "Check admission; no builders executed.",
        "rollback": "Retain disposable test fixture until teardown.", "evidence": evidence("unit"),
    }, actor="unit")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    if mode == "sibling":
        with pytest.raises(ValueError, match="execute scope omits"):
            driver.admit_driver(admission["event_id"])
    else:
        driver.admit_driver(admission["event_id"])


def clean_report():
    return {"build_claims_valid": True, "registry_envelopes_valid": True,
            "registry_valid": True, "provider_route_violations": [],
            "stale_generated_projections": []}


def test_check_only_never_requires_or_creates_admission(monkeypatch):
    monkeypatch.setattr(driver, "verify", clean_report)
    monkeypatch.setattr(driver, "admit_driver", lambda *_: pytest.fail("check-only admission side effect"))
    monkeypatch.setattr(driver, "run", lambda *_: pytest.fail("check-only launched a producer"))
    assert driver.main(["--check-only"]) == 0


def test_mutation_without_explicit_admission_stops_before_owner(monkeypatch):
    monkeypatch.setattr(driver, "run", lambda *_: pytest.fail("unadmitted owner launched"))
    with pytest.raises(SystemExit) as caught:
        driver.main([])
    assert caught.value.code == 2


def test_native_admission_is_forwarded_unchanged_to_guarded_owner(monkeypatch, tmp_path):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    scripts = ["scripts/build_test_group_index.py", "scripts/build_registry_envelope_inventory.py"]
    for script in scripts:
        path = tmp_path / script
        path.parent.mkdir(exist_ok=True)
        path.write_text("# inert existence fixture")
    monkeypatch.setattr(driver, "PROJECTIONS", tuple((str(i), script, (), True) for i, script in enumerate(scripts)))
    calls = []
    monkeypatch.setattr(driver, "admit_driver", lambda value: calls.append(("admit", value)))
    def run(label, script, argv, **supervision):
        calls.append(("run", script, argv))
        return {"label": label, "exit_code": 0}
    monkeypatch.setattr(driver, "run", run)
    monkeypatch.setattr(driver, "verify", clean_report)
    assert driver.main(["--admission-event-id", "actual-host-supplied-id"]) == 0
    assert calls == [("admit", "actual-host-supplied-id"),
                     *[("run", script, ("--admission-event-id", "actual-host-supplied-id")) for script in scripts]]


@pytest.mark.parametrize("failure", ["missing", "nonzero"])
def test_first_hard_dependency_failure_stops_later_side_effects(monkeypatch, tmp_path, failure):
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    first = tmp_path / "first.py"
    if failure != "missing":
        first.write_text("# inert existence fixture")
    (tmp_path / "second.py").write_text("# inert existence fixture")
    monkeypatch.setattr(driver, "PROJECTIONS", (("first", "first.py", (), True), ("second", "second.py", (), True)))
    monkeypatch.setattr(driver, "admit_driver", lambda value: None)
    calls = []
    def run(label, script, argv, **supervision):
        calls.append(label)
        return {"label": label, "exit_code": 2}
    monkeypatch.setattr(driver, "run", run)
    monkeypatch.setattr(driver, "verify", lambda: pytest.fail("post-failure dependency validation reached"))
    assert driver.main(["--admission-event-id", "supplied-id"]) == 1
    assert calls == ([] if failure == "missing" else ["first"])


def test_legacy_authoritative_bypass_is_unavailable(monkeypatch):
    monkeypatch.setattr(driver, "admit_driver", lambda *_: pytest.fail("unsafe path proceeded"))
    monkeypatch.setattr(driver, "run", lambda *_: pytest.fail("unsafe path launched"))
    with pytest.raises(SystemExit) as caught:
        driver.main(["--authoritative", "--admission-event-id", "supplied-id"])
    assert caught.value.code == 2


def test_rejected_native_admission_never_launches_an_owner(monkeypatch):
    def rejected(value):
        raise ValueError("native work session is expired")
    monkeypatch.setattr(driver, "admit_driver", rejected)
    monkeypatch.setattr(driver, "run", lambda *_: pytest.fail("rejected admission launched a producer"))
    with pytest.raises(ValueError, match="expired"):
        driver.main(["--admission-event-id", "expired-id"])


def test_check_only_refuses_failed_registry_dependency(monkeypatch):
    value = clean_report()
    value["registry_valid"] = False
    monkeypatch.setattr(driver, "verify", lambda: value)
    monkeypatch.setattr(driver, "run", lambda *_: pytest.fail("read-only check launched owner"))
    assert driver.main(["--check-only"]) == 1
