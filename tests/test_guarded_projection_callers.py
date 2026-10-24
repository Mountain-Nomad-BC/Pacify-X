"""Canonical projection CLIs must use the admitted publication boundary."""
import importlib
from pathlib import Path

import pytest


CASES = (
    ("build_historical_external_references", "historical_external_references"),
    ("build_registry_envelope_inventory", "registry_envelope_inventory"),
    ("build_test_group_index", "test_group_index"),
    ("build_effect_surface_ownership", "effect_surface_ownership"),
    ("build_python_surface_ownership", "python_surface_ownership"),
    ("build_artifact_reachability", "artifact_reachability"),
    ("build_provider_route_index", "provider_route_scan"),
    ("build_contract_ownership_registry", "contract_ownership"),
)


def _builder_inputs(monkeypatch, module, name):
    if name == "build_contract_ownership_registry":
        monkeypatch.setattr(module, "build", lambda *a: {"contract_count": 0, "records": []})
    elif name == "build_historical_external_references":
        monkeypatch.setattr(module, "discover_historical_references", lambda *a, **k: [])
    elif name == "build_registry_envelope_inventory":
        monkeypatch.setattr(module, "build_inventory", lambda *a: {"records": []})
    elif name == "build_test_group_index":
        monkeypatch.setattr(module, "build_test_group_index", lambda *a: {
            "test_file_count": 1, "tracked_python_file_count": 2, "verified_file_count": 0})
    elif name == "build_effect_surface_ownership":
        monkeypatch.setattr(module, "discover_effect_surfaces", lambda *a: [])
    elif name == "build_artifact_reachability":
        monkeypatch.setattr(module, "build_artifact_reachability", lambda *a: {"record_count": 0})
    elif name == "build_provider_route_index":
        monkeypatch.setattr(module, "build_provider_route_index", lambda *a: {
            "records": [], "report": {"valid": True, "violation_count": 0}})
    else:
        monkeypatch.setattr(module, "certify_exact_tools", lambda *a: {"valid": True})
        monkeypatch.setattr(module, "certify_python_surfaces", lambda *a, **k: {
            "valid": True, "map_current": False, "python_file_count": 1,
            "syntax_valid_count": 1, "packaged_file_count": 0,
            "direct_behavior_count": 0, "evidence_association_count": 0,
            "source_only_structural_count": 1, "errors": []})


@pytest.mark.parametrize("name,target", CASES)
def test_cli_routes_exact_payload_and_explicit_admission(monkeypatch, tmp_path, name, target):
    module = importlib.import_module("scripts." + name)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _builder_inputs(monkeypatch, module, name)
    observed = []
    def publish(root, relative, image, *, admission_event_id):
        observed.append((root, relative, image, admission_event_id))
    monkeypatch.setattr(module, "publish_guarded_registry_projection", publish)
    argv = [name, "--admission-event-id", "native-admission"]
    if name == "build_registry_envelope_inventory":
        argv += ["--root", str(tmp_path)]
    monkeypatch.setattr("sys.argv", argv)
    assert module.main() == 0
    assert len(observed) == 1
    assert observed[0][0] == tmp_path
    assert observed[0][1] == "registry/" + target + ".json"
    assert isinstance(observed[0][2], dict)
    assert observed[0][3] == "native-admission"
    assert not (tmp_path / "registry").exists()


@pytest.mark.parametrize("name,target", CASES)
def test_missing_admission_cannot_publish(monkeypatch, tmp_path, name, target):
    from runtime.guarded_registry_projection import GuardedProjectionError
    module = importlib.import_module("scripts." + name)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    _builder_inputs(monkeypatch, module, name)
    monkeypatch.setattr("sys.argv", [name, "--root", str(tmp_path)]
                        if name == "build_registry_envelope_inventory" else [name])
    expected = GuardedProjectionError if name == "build_registry_envelope_inventory" else SystemExit
    with pytest.raises(expected):
        module.main()
    assert not (tmp_path / "registry").exists()
