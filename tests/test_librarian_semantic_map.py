"""Normal Archivist map consumers must preserve explicit identity and freshness."""
import hashlib
import json

import pytest

from runtime.librarian_semantic_map import load_semantic_map, describe_entity
from runtime import librarian_semantic_map as archivist


def project(tmp_path):
    for name in ("registry/graphs", "contracts", "knowledge/nsai"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "registry/models.json").write_text(json.dumps({"models": [
        {"model_id": "worker-one", "description": "Initial description", "status": "declared"}]}))
    return tmp_path


def test_normal_description_exposes_typed_current_locator(tmp_path):
    semantic_map = load_semantic_map(project(tmp_path))
    description = describe_entity(semantic_map, "registry:model:worker-one")
    locator = description["canonical_locator"]
    assert locator["entity_id"] == description["canonical_entity_id"]
    assert locator["location"]["reference"] == "registry/models.json"
    assert locator["revision"] == 1
    assert locator["schema_version"] == "px.semantic-locator/2.0"


def test_normal_description_resolves_exact_current_path_and_bound_alias(tmp_path):
    semantic_map = load_semantic_map(project(tmp_path))
    named = describe_entity(semantic_map, "registry:model:worker-one")
    by_path = describe_entity(semantic_map, "registry/models.json")
    assert by_path["found"] and by_path["canonical_entity_id"] == named["canonical_entity_id"]
    assert by_path["canonical_lifecycle"] == "proposed"
    reference = named["compact_reference"]
    by_alias = describe_entity(semantic_map, reference["alias"], table_sha256=reference["table_sha256"])
    assert by_alias["canonical_entity_id"] == named["canonical_entity_id"]
    with pytest.raises(ValueError, match="binding"):
        describe_entity(semantic_map, reference["alias"])


def test_normal_consumer_restores_old_locator_without_recycling_revision(tmp_path, monkeypatch):
    root = project(tmp_path)
    before = load_semantic_map(root)
    snapshot = before.locator_snapshot_bytes()
    identifier = before.get("registry:model:worker-one").canonical_entity_id
    (root / "registry/models.json").rename(root / "registry/renamed-model-catalog.json")
    monkeypatch.setattr(archivist, "REGISTRY_ENTITY_SOURCES", {"registry/renamed-model-catalog.json": "model"})
    after = load_semantic_map(root, locator_snapshot=snapshot)
    assert after.resolve_reference("registry/models.json") == ()
    old = describe_entity(after, "registry/models.json", include_history=True)
    current = describe_entity(after, "registry/renamed-model-catalog.json")
    assert old["canonical_entity_id"] == current["canonical_entity_id"] == identifier
    assert current["canonical_locator"]["revision"] == 2
    stable = load_semantic_map(root, locator_snapshot=after.locator_snapshot_bytes())
    assert stable.map_sha256 == after.map_sha256
    assert stable.locator_snapshot_bytes() == after.locator_snapshot_bytes()


def test_shared_source_path_is_explicitly_ambiguous(tmp_path):
    root = project(tmp_path)
    (root / "registry/models.json").write_text(json.dumps({"models": [
        {"model_id": "worker-one"}, {"model_id": "worker-two"}]}))
    semantic_map = load_semantic_map(root)
    description = describe_entity(semantic_map, "registry/models.json")
    assert not description["found"] and description["resolution_status"] == "ambiguous"
    assert len(description["candidate_entity_ids"]) == 2
    assert len(semantic_map.resolve_reference("registry/models.json")) == 2


def test_reused_historical_path_preserves_both_canonical_candidates(tmp_path, monkeypatch):
    root = project(tmp_path)
    original = load_semantic_map(root)
    snapshot = original.locator_snapshot_bytes()
    (root / "registry/models.json").rename(root / "registry/renamed-model-catalog.json")
    (root / "registry/models.json").write_text(json.dumps({"models": [{"model_id": "worker-two"}]}))
    monkeypatch.setattr(archivist, "REGISTRY_ENTITY_SOURCES", {
        "registry/models.json": "model", "registry/renamed-model-catalog.json": "model"})
    current = load_semantic_map(root, locator_snapshot=snapshot)
    resolved = describe_entity(current, "registry/models.json")
    assert resolved["entity_id"] == "registry:model:worker-two"
    ambiguous = describe_entity(current, "registry/models.json", include_history=True)
    assert not ambiguous["found"] and ambiguous["resolution_status"] == "ambiguous"
    assert len(ambiguous["candidate_entity_ids"]) == 2


def test_removed_owner_blocks_history_restore_instead_of_losing_identity(tmp_path):
    from runtime.semantic_locator import SemanticLocatorError
    root = project(tmp_path)
    snapshot = load_semantic_map(root).locator_snapshot_bytes()
    (root / "registry/models.json").write_text(json.dumps({"models": []}))
    with pytest.raises(SemanticLocatorError, match="unknown entity"):
        load_semantic_map(root, locator_snapshot=snapshot)


def test_snapshot_and_reference_consumers_reject_stale_map(tmp_path):
    root = project(tmp_path)
    semantic_map = load_semantic_map(root)
    (root / "registry/models.json").write_text(json.dumps({"models": [{"model_id": "worker-two"}]}))
    with pytest.raises(ValueError, match="blocked"):
        semantic_map.locator_snapshot_bytes()
    with pytest.raises(ValueError, match="blocked"):
        semantic_map.resolve_reference("registry/models.json", include_history=True)


def test_reference_controls_are_validated_for_canonical_ids_too(tmp_path):
    semantic_map = load_semantic_map(project(tmp_path))
    identifier = semantic_map.get("registry:model:worker-one").canonical_entity_id
    for kwargs in ({"include_history": 1}, {"locator_kind": "unknown"}):
        with pytest.raises(ValueError):
            semantic_map.resolve_reference(identifier, **kwargs)
        with pytest.raises(ValueError):
            describe_entity(semantic_map, identifier, **kwargs)


def test_published_canonical_metadata_cannot_mutate_a_fresh_map(tmp_path):
    semantic_map = load_semantic_map(project(tmp_path))
    entity_id = semantic_map.get("registry:model:worker-one").canonical_entity_id
    before = json.loads(json.dumps(semantic_map.canonical_entities[entity_id]))
    exposed = semantic_map.canonical_entities[entity_id]
    exposed["identity_basis"]["qualifier"] = "forged-record"
    assert semantic_map.canonical_entities[entity_id] == before
    locations = semantic_map.canonical_locators
    locations[entity_id]["location"]["reference"] = "forged/location"
    assert semantic_map.canonical_locators[entity_id]["location"]["reference"] == "registry/models.json"
    with pytest.raises(TypeError):
        semantic_map.counts["canonical_entities"] = 99
    assert semantic_map.projection_status().state == "fresh"


def test_normal_description_exposes_bound_compact_reference_and_locator_relation(tmp_path):
    semantic_map = load_semantic_map(project(tmp_path))
    description = describe_entity(semantic_map, "registry:model:worker-one")
    reference = description["compact_reference"]
    with pytest.raises(ValueError, match="binding"):
        semantic_map.get(reference["alias"])
    resolved = semantic_map.resolve_compact_reference(reference["alias"], table_sha256=reference["table_sha256"])
    assert resolved.canonical_entity_id == description["canonical_entity_id"] == reference["entity_id"]
    relation = description["canonical_relations"][0]
    assert relation["source_entity_id"] == reference["entity_id"]
    assert relation["relation_kind"] == "located_at"
    assert relation["external_target"] == "registry/models.json"
    stale_alias = reference["alias"].rsplit(":", 1)[0] + ":2"
    assert semantic_map.resolve_compact_reference(stale_alias, table_sha256=reference["table_sha256"]) is None
    rebuilt = load_semantic_map(tmp_path)
    assert rebuilt.compact_table_sha256 == semantic_map.compact_table_sha256
    assert rebuilt.compact_addresses == semantic_map.compact_addresses


def test_compact_reference_cannot_be_resolved_against_an_unbound_or_rebuilt_table(tmp_path):
    root = project(tmp_path)
    original = load_semantic_map(root)
    ref = describe_entity(original, "registry:model:worker-one")["compact_reference"]
    with pytest.raises(ValueError, match="binding"):
        original.resolve_compact_reference(ref["alias"], table_sha256="0" * 64)
    path = root / "registry/models.json"
    data = json.loads(path.read_text())
    data["models"].append({"model_id": "worker-two"})
    path.write_text(json.dumps(data))
    rebuilt = load_semantic_map(root)
    with pytest.raises(ValueError, match="binding"):
        rebuilt.resolve_compact_reference(ref["alias"], table_sha256=ref["table_sha256"])
    with pytest.raises(ValueError, match="projection.*blocked"):
        original.resolve_compact_reference(ref["alias"], table_sha256=ref["table_sha256"])


def test_changed_operational_facts_invalidate_archivist_map_generation(tmp_path):
    root = project(tmp_path)
    before = load_semantic_map(root)
    path = root / "registry/models.json"
    value = json.loads(path.read_text())
    value["models"][0]["description"] = "Changed operational description"
    path.write_text(json.dumps(value))
    after = load_semantic_map(root)
    assert set(before.entities) == set(after.entities)
    assert before.map_sha256 != after.map_sha256


def test_long_source_description_remains_available_without_invalid_canonical_terms(tmp_path):
    root = project(tmp_path)
    description = "current operational evidence " * 30
    (root / "registry/models.json").write_text(json.dumps({"models": [
        {"model_id": "worker-one", "description": description}]}))
    semantic_map = load_semantic_map(root)
    entity = semantic_map.get("registry:model:worker-one")
    assert description.strip() in entity.terms
    assert all(len(term) <= 300 for term in semantic_map.canonical_entities[entity.canonical_entity_id]["terms"])


def test_duplicate_declared_entities_fail_before_silent_replacement(tmp_path):
    root = project(tmp_path)
    path = root / "registry/models.json"
    value = json.loads(path.read_text())
    value["models"].append({"model_id": "worker-one", "description": "A different owner"})
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="duplicate semantic entity"):
        load_semantic_map(root)


def test_retained_archivist_map_cannot_serve_changed_source_as_fresh(tmp_path):
    root = project(tmp_path)
    semantic_map = load_semantic_map(root)
    path = root / "registry/models.json"
    value = json.loads(path.read_text())
    value["models"][0]["description"] = "New facts after the map was captured"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="projection.*blocked"):
        describe_entity(semantic_map, "registry:model:worker-one")


def test_normal_description_exposes_scope_bound_vector_and_observed_freshness(tmp_path):
    root = project(tmp_path)
    semantic_map = load_semantic_map(root)
    description = describe_entity(semantic_map, "registry:model:worker-one")
    assert description["context_generation_vector"]["scope"] == "archivist-map-metadata"
    assert description["projection_status"]["state"] == "fresh"
    assert description["context_generation_vector"]["vector"]["runtime_epoch"] is None


@pytest.mark.parametrize("raw", ['{"models":[],"models":[]}', '{"models":[{"model_id":"worker","value":NaN}]}'])
def test_ambiguous_or_nonfinite_metadata_cannot_acquire_generation_freshness(tmp_path, raw):
    root = project(tmp_path)
    (root / "registry/models.json").write_text(raw)
    with pytest.raises(ValueError):
        load_semantic_map(root)


def test_graph_relationship_resolves_through_normal_description(tmp_path):
    root = project(tmp_path)
    (root / "registry/graphs/capability_graph.json").write_text(json.dumps({
        "nodes": [{"id": "one"}, {"id": "two"}],
        "edges": [{"source": "one", "target": "two", "relation": "calls"}]}))
    semantic_map = load_semantic_map(root)
    description = describe_entity(semantic_map, "graph:capability_graph:one")
    assert description["neighbours"][0]["target"] == "graph:capability_graph:two"
    assert description["neighbours"][0]["target_known"] is True
    assert "graph:capability_graph:one" in semantic_map.identity_ambiguities
    assert semantic_map.get("graph:capability_graph:one").canonical_entity_id is None


def test_string_graph_nodes_are_accounted_for_instead_of_silently_omitted(tmp_path):
    root = project(tmp_path)
    (root / "registry/graphs/capability_graph.json").write_text(json.dumps({
        "nodes": ["one", "two"],
        "edges": [{"source": "one", "target": "two", "relation": "calls"}]}))
    semantic_map = load_semantic_map(root)
    assert semantic_map.counts["graph_nodes"] == 2
    assert semantic_map.get("graph:capability_graph:one") is not None
    assert describe_entity(semantic_map, "graph:capability_graph:one")["neighbours"][0]["target_known"] is True


def test_graph_identity_binds_only_through_exact_declared_source_kind(tmp_path):
    root = project(tmp_path)
    (root / "registry/graphs/system_asset_graph.json").write_text(json.dumps({
        "nodes": [{"node_id": "worker-one", "asset_type": "model"},
                  {"node_id": "worker-one-title", "asset_type": "model"}], "edges": []}))
    semantic_map = load_semantic_map(root)
    source = semantic_map.get("registry:model:worker-one")
    projected = semantic_map.get("graph:system_asset_graph:worker-one")
    assert projected.canonical_entity_id == source.canonical_entity_id
    assert semantic_map.get(source.canonical_entity_id).source_path == "registry/models.json"
    assert "graph:system_asset_graph:worker-one" not in semantic_map.identity_ambiguities
    assert "graph:system_asset_graph:worker-one-title" in semantic_map.identity_ambiguities


def test_admitted_capabilities_and_skill_metadata_are_not_omitted(tmp_path):
    root = project(tmp_path)
    (root / "registry/capability_map.json").write_text(json.dumps({
        "active_capabilities": [{"id": "inspect-source"}]}))
    (root / "registry/skill_catalog.toml").write_text('[[skills]]\nid = "inspect-source"\nstatus = "active"\n')
    (root / "registry/graphs/capability_graph.json").write_text(json.dumps({
        "nodes": ["inspect-source"], "edges": []}))
    semantic_map = load_semantic_map(root)
    capability = semantic_map.get("registry:capability:inspect-source")
    skill = semantic_map.get("registry:skill:inspect-source")
    assert capability.canonical_entity_id != skill.canonical_entity_id
    assert semantic_map.get("graph:capability_graph:inspect-source").canonical_entity_id == capability.canonical_entity_id


def test_project_graph_uses_declared_roles_and_preserves_conflated_role_ambiguity(tmp_path):
    root = project(tmp_path)
    (root / "registry/skill_catalog.toml").write_text('[[skills]]\nid = "inspect-source"\nstatus = "active"\n')
    path = root / "registry/project_stream_orchestrations.json"
    value = {"orchestrations": [{"orchestration_id": "review", "skills": ["inspect-source"]}]}
    path.write_text(json.dumps(value))
    (root / "registry/graphs/project_stream_dependency_graph.json").write_text(json.dumps({
        "nodes": ["review", "inspect-source"], "edges": []}))
    semantic_map = load_semantic_map(root)
    assert semantic_map.get("graph:project_stream_graph:inspect-source").canonical_entity_id == semantic_map.get("registry:skill:inspect-source").canonical_entity_id
    value["orchestrations"][0]["deferred_capabilities"] = ["inspect-source"]
    path.write_text(json.dumps(value))
    ambiguous = load_semantic_map(root)
    assert ambiguous.get("graph:project_stream_graph:inspect-source").canonical_entity_id is None
    assert "conflates" in ambiguous.identity_ambiguities["graph:project_stream_graph:inspect-source"]


def test_normal_archivist_consumer_preserves_identity_when_source_locator_moves(tmp_path, monkeypatch):
    root = project(tmp_path)
    before = load_semantic_map(root)
    entity = before.get("registry:model:worker-one")
    reference = describe_entity(before, entity.canonical_entity_id)["compact_reference"]
    source = root / "registry/models.json"
    source.rename(root / "registry/renamed-model-catalog.json")
    monkeypatch.setattr(archivist, "REGISTRY_ENTITY_SOURCES", {"registry/renamed-model-catalog.json": "model"})
    after = load_semantic_map(root)
    renamed = after.get(entity.canonical_entity_id)
    assert renamed.canonical_entity_id == entity.canonical_entity_id
    assert renamed.source_path != entity.source_path
    assert describe_entity(after, entity.canonical_entity_id)["compact_reference"] == reference
    assert after.resolve_compact_reference(reference["alias"], table_sha256=reference["table_sha256"]).canonical_entity_id == entity.canonical_entity_id
    assert before.canonical_locators[entity.canonical_entity_id]["location"]["reference"] == "registry/models.json"
    assert after.canonical_locators[entity.canonical_entity_id]["location"]["reference"] == "registry/renamed-model-catalog.json"
    assert before.map_sha256 != after.map_sha256


def test_semantic_contract_ownership_registers_normal_archivist_producer():
    from pathlib import Path
    from scripts.build_contract_ownership_registry import build
    root = Path(__file__).resolve().parents[1]
    records = {Path(item["path"]).name: item for item in build(root)["records"]}
    for name in ("compact-address-record.schema.json", "semantic-entity.schema.json", "locator-record.schema.json", "relation-record.schema.json"):
        assert "runtime/librarian_semantic_map.py" in records[name]["producers"]
        assert "runtime/librarian_semantic_map.py" in records[name]["consumers"]
        assert "tests/test_librarian_semantic_map.py" in records[name]["tests"]
# ---------------------------------------------------------------------------
# Durable canonical identity through the normal Archivist consumer.
#
# The locator snapshot made locator history durable across restarts, but the
# EntityRegistry the map builds was discarded on return. These pin the entity
# side: an accepted canonical identity must survive a restart through
# load_semantic_map, and a stale snapshot must never inject a phantom entity
# or silently retype a live one.
# ---------------------------------------------------------------------------


def test_entity_snapshot_is_exposed_for_caller_owned_persistence(tmp_path):
    root = project(tmp_path)
    semantic_map = load_semantic_map(root)

    image = semantic_map.entity_snapshot_bytes

    assert isinstance(image, bytes) and image
    assert semantic_map.entity_snapshot_sha256() == hashlib.sha256(image).hexdigest()


def test_accepted_canonical_identity_survives_a_restart_through_the_consumer(tmp_path):
    from runtime.semantic_entity import EntityRegistry

    root = project(tmp_path)
    before = load_semantic_map(root)
    identifier = before.get("registry:model:worker-one").canonical_entity_id

    # The consumer publishes an acceptance, then the process ends.
    published = EntityRegistry.from_snapshot_bytes(before.entity_snapshot_bytes)
    assert published.assert_unique_accepted() == ()
    registry = EntityRegistry()
    for record in published.all_entities():
        registry._entities[record.entity_id] = record
        registry._basis_by_id[record.entity_id] = published.identity_tuple(record.entity_id)
    registry.transition(identifier, "accepted", at_utc="2026-10-04T00:00:00+00:00")

    # A fresh build with only the persisted image must carry that acceptance.
    after = load_semantic_map(root, entity_snapshot=registry.snapshot_bytes())

    description = describe_entity(after, "registry:model:worker-one")
    assert description["canonical_entity_id"] == identifier
    assert description["canonical_lifecycle"] == "accepted"
    assert next(
        record for record in after.canonical_entities.values()
        if record["entity_id"] == identifier
    )["lifecycle"]["accepted_utc"] == "2026-10-04T00:00:00+00:00"


def test_recovered_retirement_survives_and_does_not_resurrect(tmp_path):
    from runtime.semantic_entity import EntityRegistry

    root = project(tmp_path)
    before = load_semantic_map(root)
    identifier = before.get("registry:model:worker-one").canonical_entity_id

    published = EntityRegistry.from_snapshot_bytes(before.entity_snapshot_bytes)
    registry = EntityRegistry()
    for record in published.all_entities():
        registry._entities[record.entity_id] = record
        registry._basis_by_id[record.entity_id] = published.identity_tuple(record.entity_id)
    registry.transition(identifier, "accepted", at_utc="2026-10-04T00:00:00+00:00")
    registry.transition(identifier, "retired", at_utc="2026-10-04T01:00:00+00:00",
                        reason="withdrawn by its owning registry")

    after = load_semantic_map(root, entity_snapshot=registry.snapshot_bytes())

    description = describe_entity(after, "registry:model:worker-one")
    assert description["canonical_lifecycle"] == "retired"
    # Retirement is terminal: re-running with the same image cannot revive it.
    again = load_semantic_map(root, entity_snapshot=after.entity_snapshot_bytes)
    assert describe_entity(again, "registry:model:worker-one")["canonical_lifecycle"] == "retired"


def test_stale_entity_snapshot_cannot_inject_a_phantom_entity(tmp_path):
    from runtime.semantic_entity import EntityRegistry, identity_basis_for

    root = project(tmp_path)
    phantom = EntityRegistry().register(
        entity_kind="record",
        identity_basis=identity_basis_for("declared_identifier", "removed:model:ghost"),
        declared_by="a-registry-that-no-longer-exists",
    )
    phantom_registry = EntityRegistry()
    phantom_record = phantom_registry.register(
        entity_kind="record",
        identity_basis=identity_basis_for("declared_identifier", "removed:model:ghost"),
        declared_by="a-registry-that-no-longer-exists",
    )
    phantom_registry.transition(phantom_record.entity_id, "accepted",
                                at_utc="2026-10-04T00:00:00+00:00")

    semantic_map = load_semantic_map(root, entity_snapshot=phantom_registry.snapshot_bytes())

    # The recovered identity is absent from current sources, so it is discarded
    # rather than resurrected as a phantom.
    assert phantom_record.entity_id not in semantic_map.canonical_entities
    assert "removed:model:ghost" not in semantic_map.entities


def test_entity_snapshot_alone_does_not_alter_locator_or_map_identity(tmp_path):
    from runtime.semantic_entity import EntityRegistry

    root = project(tmp_path)
    before = load_semantic_map(root)
    registry = EntityRegistry()
    for record in EntityRegistry.from_snapshot_bytes(before.entity_snapshot_bytes).all_entities():
        registry._entities[record.entity_id] = record

    after = load_semantic_map(root, entity_snapshot=registry.snapshot_bytes())

    # Identity and location are unchanged; only lifecycle could have moved, and
    # here nothing was accepted, so the map is byte-identical.
    assert after.map_sha256 == before.map_sha256
    assert after.locator_snapshot_bytes() == before.locator_snapshot_bytes()
    assert after.entity_snapshot_bytes == before.entity_snapshot_bytes


def test_malformed_entity_snapshot_is_refused_rather_than_partially_applied(tmp_path):
    root = project(tmp_path)
    before = load_semantic_map(root)
    corrupted = bytearray(before.entity_snapshot_bytes)
    corrupted[-2] = corrupted[-2] ^ 0xFF

    with pytest.raises(ValueError):
        load_semantic_map(root, entity_snapshot=bytes(corrupted))# ---------------------------------------------------------------------------
# Retired-entity locator provenance in the normal description path.
#
# The map-level fallback protects canonical_locations, but describe_entity reads
# _canonical_locator_records directly, which excludes retired entities by
# design. That made a tombstone report canonical_locator None at the exact point
# a consumer looks for it, even though the entity still resolves a source_path.
# ---------------------------------------------------------------------------


def _retire(root, identifier, reason):
    from runtime.semantic_entity import EntityRegistry

    before = load_semantic_map(root)
    published = EntityRegistry.from_snapshot_bytes(before.entity_snapshot_bytes)
    registry = EntityRegistry()
    for record in published.all_entities():
        registry._entities[record.entity_id] = record
        registry._basis_by_id[record.entity_id] = published.identity_tuple(record.entity_id)
    registry.transition(identifier, "accepted", at_utc="2026-10-04T00:00:00+00:00")
    registry.transition(identifier, "retired", at_utc="2026-10-04T01:00:00+00:00", reason=reason)
    return load_semantic_map(root, entity_snapshot=registry.snapshot_bytes())


def test_retired_entity_keeps_its_last_known_locator_in_the_normal_description(tmp_path):
    root = project(tmp_path)
    identifier = load_semantic_map(root).get("registry:model:worker-one").canonical_entity_id

    after = _retire(root, identifier, "withdrawn by its owning registry")
    description = describe_entity(after, "registry:model:worker-one")

    assert description["canonical_lifecycle"] == "retired"
    locator = description["canonical_locator"]
    # The tombstone keeps its provenance instead of reporting None.
    assert locator is not None
    assert locator["entity_id"] == identifier
    assert locator["location"]["reference"] == "registry/models.json"
    # It is explicitly marked as not current, so a stale location can never be
    # mistaken for a live one.
    assert locator["current"] is False


def test_live_entity_locator_is_current_and_unmarked(tmp_path):
    root = project(tmp_path)

    description = describe_entity(load_semantic_map(root), "registry:model:worker-one")

    locator = description["canonical_locator"]
    assert description["canonical_lifecycle"] == "proposed"
    assert locator is not None
    assert locator["location"]["reference"] == "registry/models.json"
    # A current locator carries no retired marker at all.
    assert "current" not in locator