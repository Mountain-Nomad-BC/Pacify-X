from pathlib import Path
import json
import pytest

from runtime.mutating_producer_registry import build_registry, default_classification, validate_registry


def test_import_does_not_prove_actual_lease_use(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/producer.py").write_text(
        "from runtime.file_lock import FileLock\ndef mutate(p):\n    p.write_text('unguarded')\n")
    assert default_classification(tmp_path, "runtime/producer.py", ("filesystem_mutation",)) is None
    assert build_registry(tmp_path)["unclassified"] == ["runtime/producer.py"]


def test_script_location_does_not_exempt_unguarded_mutation(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/producer.py").write_text("def mutate(p):\n    p.write_text('unguarded')\n")
    assert build_registry(tmp_path)["unclassified"] == ["scripts/producer.py"]


def test_old_claim_cannot_override_current_source_authority(tmp_path):
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/producer.py").write_text("def mutate(p):\n    p.write_text('unguarded')\n")
    (tmp_path / "registry").mkdir()
    (tmp_path / "registry/mutating_producers.json").write_text(json.dumps({
        "schema_version": "px.mutating-producer-registry/1.0",
        "producers": {"runtime/producer.py": {"classification": "leased",
            "reason": "canonical_lease_intent_owner"}}}))
    assert build_registry(tmp_path)["unclassified"] == ["runtime/producer.py"]
    result = validate_registry(tmp_path)
    assert result["valid"] is False
    assert any("no current source-backed" in error for error in result["errors"])


def test_reviewed_control_custody_source_drift_fails_closed(tmp_path):
    relative = "runtime/gremlin/audit.py"
    source = Path(__file__).resolve().parents[1] / relative
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    assert default_classification(tmp_path, relative, ("filesystem_mutation",)) == {
        "classification": "exempt", "reason": "canonical_control_audit_custody"}
    target.write_bytes(source.read_bytes() + b"\n# unreviewed drift\n")
    assert default_classification(tmp_path, relative, ("filesystem_mutation",)) is None


def test_publisher_requires_explicit_admission_before_mutation(tmp_path):
    import pytest
    from runtime.mutating_producer_registry import publish_registry, MutatingProducerError
    with pytest.raises(MutatingProducerError, match="explicit current work admission"):
        publish_registry(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_publisher_real_custody_and_intent_close_in_isolated_fixture(tmp_path, monkeypatch):
    import runtime.mutating_producer_registry as owner
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    from runtime.resource_lifecycle import ResourceManager
    import runtime.guarded_registry_projection as guarded
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    result = owner.publish_registry(tmp_path, admission_event_id="unit-fixture-authority")
    row = EffectIntentLedger(tmp_path).fence(result["effect_intent_key"])
    assert row["disposition"] == "committed"
    assert row["result_sha256"] == result["result_sha256"]
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    manager = ResourceManager(tmp_path / ".agentic_engineering_os_px/resource-lifecycle/resources.json")
    assert all(not record.active for record in manager.ledger.load())
    assert not list((tmp_path / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces").glob(".producer-publication-*"))


def test_publisher_write_failure_settles_intent_and_temporary_custody(tmp_path, monkeypatch):
    import pytest
    import runtime.mutating_producer_registry as owner
    import runtime.studio_models as writer
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    import runtime.guarded_registry_projection as guarded
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    def failed_write(path, image):
        path.write_text("partial")
        raise OSError("controlled disk failure")
    monkeypatch.setattr(writer, "write_json_atomic", failed_write)
    with pytest.raises(OSError, match="controlled disk failure"):
        owner.publish_registry(tmp_path, admission_event_id="unit-fixture-authority")
    document = EffectIntentLedger(tmp_path)._load()
    assert len(document["intents"]) == 1
    assert document["intents"][0]["state"] == "failed"
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    assert not (tmp_path / "registry/mutating_producers.json").exists()
    assert not list((tmp_path / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces").glob(".producer-publication-*"))


def test_publication_commit_failure_keeps_uncertain_intent(tmp_path, monkeypatch):
    import pytest
    import runtime.mutating_producer_registry as owner
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore
    import runtime.guarded_registry_projection as guarded
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    def failed_commit(self, **kwargs):
        raise OSError("controlled settlement failure")
    monkeypatch.setattr(EffectIntentLedger, "commit", failed_commit)
    with pytest.raises(OSError, match="controlled settlement failure"):
        owner.publish_registry(tmp_path, admission_event_id="unit-fixture-authority")
    document = EffectIntentLedger(tmp_path)._load()
    assert document["intents"][0]["state"] == "in_flight"
    assert (tmp_path / "registry/mutating_producers.json").is_file()
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    assert not list((tmp_path / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces").glob(".producer-publication-*"))


def test_publication_cannot_omit_native_custody_write_scopes(tmp_path, monkeypatch):
    import pytest
    import runtime.operational_gap_ledger as authority
    import runtime.mutating_producer_registry as owner
    scope = ["registry"]
    snapshot = {"work_admissions": [{"event_id": "admission:fixture",
        "gap_id": "gap:fixture", "effect_scopes": [{"effect": "write", "scope": scope}]}]}
    monkeypatch.setattr(authority, "read_snapshot", lambda root: snapshot)
    calls = []
    monkeypatch.setattr(authority, "guard_work_admission", lambda value, **kwargs: calls.append(kwargs))
    with pytest.raises(owner.MutatingProducerError, match="runtime-core"):
        owner.publish_registry(tmp_path, admission_event_id="admission:fixture")
    assert calls[0]["scope"] == scope
    assert list(tmp_path.iterdir()) == []


def test_resource_manager_constructor_failure_releases_acquired_lease(tmp_path, monkeypatch):
    import pytest
    import runtime.guarded_registry_projection as guarded
    import runtime.resource_lifecycle as lifecycle
    from runtime.scope_lease import ScopeLeaseStore
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    def failed_constructor(*args, **kwargs):
        raise OSError("controlled constructor failure")
    monkeypatch.setattr(lifecycle, "ResourceManager", failed_constructor)
    with pytest.raises(OSError, match="controlled constructor failure"):
        guarded.publish_guarded_registry_projection(tmp_path, "registry/unit.json", {},
            admission_event_id="unit-fixture-authority")
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    assert not (tmp_path / "registry/unit.json").exists()


def test_secondary_cleanup_failure_preserves_primary_and_uncertain_custody(tmp_path, monkeypatch):
    import pytest
    import runtime.guarded_registry_projection as guarded
    import runtime.studio_models as writer
    from runtime.resource_lifecycle import ResourceManager
    from runtime.scope_lease import ScopeLeaseStore
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    def failed_write(path, image):
        path.write_text("partial")
        raise OSError("primary write failure")
    def failed_cleanup(self, *args, **kwargs):
        raise PermissionError("secondary cleanup failure")
    monkeypatch.setattr(writer, "write_json_atomic", failed_write)
    monkeypatch.setattr(ResourceManager, "reclaim_ephemeral_path", failed_cleanup)
    with pytest.raises(OSError, match="primary write failure") as refused:
        guarded.publish_guarded_registry_projection(tmp_path, "registry/unit.json", {},
            admission_event_id="unit-fixture-authority")
    assert any("secondary cleanup failure" in note for note in refused.value.__notes__)
    assert ScopeLeaseStore(tmp_path).active(effect="write") == ()
    manager = ResourceManager(tmp_path / ".agentic_engineering_os_px/resource-lifecycle/resources.json")
    assert any(record.active for record in manager.ledger.load())
    assert list((tmp_path / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces").glob(".producer-publication-*"))


def test_hostile_exception_annotation_cannot_mask_primary(tmp_path, monkeypatch):
    import pytest
    import runtime.guarded_registry_projection as guarded
    import runtime.studio_models as writer
    from runtime.resource_lifecycle import ResourceManager
    class HostileFailure(RuntimeError):
        def add_note(self, note):
            raise RuntimeError("hostile note method")
        def __setattr__(self, name, value):
            if name == "__notes__":
                raise RuntimeError("hostile note attribute")
            super().__setattr__(name, value)
    primary = HostileFailure("actual primary failure")
    monkeypatch.setattr(guarded, "_admit_projection_write", lambda root, event: None)
    def failed_write(*args):
        raise primary
    def failed_cleanup(self, *args, **kwargs):
        raise PermissionError("actual cleanup failure")
    monkeypatch.setattr(writer, "write_json_atomic", failed_write)
    monkeypatch.setattr(ResourceManager, "reclaim_ephemeral_path", failed_cleanup)
    with pytest.raises(HostileFailure) as refused:
        guarded.publish_guarded_registry_projection(tmp_path, "registry/unit.json", {},
            admission_event_id="unit-fixture-authority")
    assert refused.value is primary
    assert not list((tmp_path / "registry").glob(".producer-publication-*"))
    assert list((tmp_path / ".agentic_engineering_os_px/resource-lifecycle/publication-workspaces").glob(".producer-publication-*"))


def test_effect_discovery_keeps_actual_aliased_guarded_publishers(tmp_path):
    from runtime.effect_surface import discover_effect_surfaces
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/publisher.py").write_text(
        "from runtime.guarded_registry_projection import publish_guarded_registry_projection as emit\n"
        "def main(root, image, admission):\n"
        "    emit(root, 'registry/unit.json', image, admission_event_id=admission)\n")
    rows = discover_effect_surfaces(tmp_path)
    assert len(rows) == 1
    assert rows[0]["path"] == "scripts/publisher.py"
    assert rows[0]["effect"] == "filesystem_mutation"


def test_unused_import_and_unrelated_same_name_are_not_guarded_effects(tmp_path):
    from runtime.effect_surface import discover_effect_surfaces
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/unused.py").write_text(
        "from runtime.guarded_registry_projection import publish_guarded_registry_projection\n")
    (tmp_path / "scripts/unrelated.py").write_text(
        "from unrelated import publish_guarded_registry_projection\n"
        "publish_guarded_registry_projection()\n")
    assert discover_effect_surfaces(tmp_path) == []


@pytest.mark.parametrize('caller', ['scripts/build_effect_surface_ownership.py',
                                  'scripts/build_contract_ownership_registry.py',
                                  'scripts/build_agency_agent_graph.py',
                                  'scripts/build_semantic_capability_index.py'])
def test_reviewed_publication_delegation_requires_exact_caller_and_owner(tmp_path, caller):
    import shutil
    from runtime.mutating_producer_registry import default_classification
    source_root = Path(__file__).resolve().parents[1]
    owner = "runtime/guarded_registry_projection.py"
    for relative in (caller, owner):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, target)
    assert default_classification(tmp_path, caller, ("filesystem_mutation",)) == {
        "classification": "leased", "reason": "canonical_lease_intent_delegate"}
    original = (tmp_path / caller).read_bytes()
    (tmp_path / caller).write_bytes(original + b"\n# unreviewed caller drift\n")
    assert default_classification(tmp_path, caller, ("filesystem_mutation",)) is None
    (tmp_path / caller).write_bytes(original)
    with (tmp_path / owner).open("ab") as file:
        file.write(b"\n# unreviewed owner drift\n")
    assert default_classification(tmp_path, caller, ("filesystem_mutation",)) is None


def test_native_bootstrap_custody_is_not_claimed_as_execution_leasing(tmp_path):
    import shutil
    source_root = Path(__file__).resolve().parents[1]
    for relative in ("runtime/file_lock.py", "runtime/guarded_registry_projection.py"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / relative, target)
    assert default_classification(tmp_path, "runtime/file_lock.py", ("filesystem_mutation",)) == {
        "classification": "exempt", "reason": "canonical_control_custody_owner"}
    assert default_classification(tmp_path, "runtime/guarded_registry_projection.py", ("filesystem_mutation",)) == {
        "classification": "leased", "reason": "canonical_lease_intent_owner"}


def test_native_owner_filename_cannot_impersonate_custody(tmp_path):
    target = tmp_path / "runtime/file_lock.py"
    target.parent.mkdir()
    target.write_text("def write(p):\n    p.write_text('unguarded')\n")
    assert default_classification(tmp_path, "runtime/file_lock.py", ("filesystem_mutation",)) is None
