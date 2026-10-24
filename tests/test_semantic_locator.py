from __future__ import annotations

import json
from pathlib import Path

import pytest

"""SEM-002: locator and relation separation.

The properties under test are the two acceptance criteria of the card:
a path edit changes locators but NOT entity identity, and no relation is
allowed to carry a dangling endpoint.
"""

from runtime.semantic_entity import EntityRegistry, identity_basis_for
from runtime.semantic_locator import (
    LOCATOR_ID_PREFIX,
    LOCATOR_KINDS,
    RELATION_ID_PREFIX,
    RELATION_KINDS,
    SCHEMA_LOCATOR,
    SCHEMA_RELATION,
    LocatorRegistry,
    RelationRegistry,
    SemanticLocatorError,
    derive_locator_id,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-02T00:00:00Z"


def _basis(name: str) -> dict[str, object]:
    return identity_basis_for("intrinsic_name", name)


def _world() -> tuple[EntityRegistry, LocatorRegistry, RelationRegistry]:
    entities = EntityRegistry()
    return entities, LocatorRegistry(entities), RelationRegistry(entities)


def _entity(registry: EntityRegistry, kind: str, name: str) -> str:
    return registry.register(
        entity_kind=kind, identity_basis=_basis(name), declared_by="test"
    ).entity_id


def test_line_geometry_creates_distinct_immutable_locator_revision():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "symbol", "run")
    before = locators.set_locator(entity_id=entity_id, locator_kind="line_range", reference="a.py", line_start=1, line_end=2)
    after = locators.set_locator(entity_id=entity_id, locator_kind="line_range", reference="a.py", line_start=3, line_end=4)
    assert before.locator_id != after.locator_id
    assert before.revision == 1 and after.revision == 2
    assert locators.history(entity_id, "line_range") == (before, after)
    assert locators.get(entity_id, "line_range") == after


def test_return_to_old_path_does_not_recycle_locator_identity():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    middle = locators.relocate(entity_id, "b.py")
    last = locators.relocate(entity_id, "a.py")
    assert len({first.locator_id, middle.locator_id, last.locator_id}) == 3
    assert last.entity_id == entity_id
    assert locators.resolve_reference("file", "b.py") == ()
    assert locators.resolve_reference("file", "a.py") == (last,)


def test_relocation_does_not_copy_an_old_observation_as_a_new_fact():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py", observed_utc=NOW, observed_by="original-observer", confidence=1.0)
    moved = locators.relocate(entity_id, "b.py")
    assert moved.observed_utc is None and moved.observed_by is None and moved.confidence is None
    assert locators.history(entity_id, "file")[0] == first


def test_retired_entity_has_no_current_reverse_locator():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    entities.transition(entity_id, "retired", at_utc=NOW, reason="Current owner retirement")
    assert locators.get(entity_id, "file") is None
    assert locators.resolve_reference("file", "a.py") == ()
    assert locators.history(entity_id, "file") == (first,)


@pytest.mark.parametrize("geometry", [
    {"line_start": True, "line_end": 2},
    {"line_start": "1", "line_end": 2},
    {"line_start": 0, "line_end": 2},
    {"line_start": 3, "line_end": 2},
    {"line_start": 1, "line_end": 2147483648},
    {"line_start": 1, "line_end": 2, "symbol": False},
])
def test_invalid_geometry_cannot_bypass_validation_on_current_hit(geometry):
    entities, locators, _ = _world()
    entity_id = _entity(entities, "symbol", "run")
    first = locators.set_locator(entity_id=entity_id, locator_kind="line_range", reference="a.py", line_start=1, line_end=2)
    with pytest.raises(SemanticLocatorError):
        locators.set_locator(entity_id=entity_id, locator_kind="line_range", reference="a.py", **geometry)
    assert locators.history(entity_id, "line_range") == (first,)


def test_history_budget_preserves_prior_records_and_exact_repeats():
    entities = EntityRegistry()
    locators = LocatorRegistry(entities, max_history=2)
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    second = locators.relocate(entity_id, "b.py")
    assert locators.relocate(entity_id, "b.py") is second
    with pytest.raises(SemanticLocatorError, match="budget exhausted"):
        locators.relocate(entity_id, "c.py")
    assert locators.history(entity_id, "file") == (first, second)
    assert locators.resolve_locator(first.locator_id) is None
    assert locators.resolve_locator(second.locator_id) is second


def test_snapshot_recovery_preserves_history_and_revision_continuity(tmp_path):
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py", observed_utc=NOW, observed_by="actual-observer")
    second = locators.relocate(entity_id, "b.py")
    encoded = locators.snapshot_bytes()
    artifact = tmp_path / "locator-snapshot.json"
    artifact.write_bytes(encoded)
    recovered = LocatorRegistry.from_snapshot_bytes(entities, artifact.read_bytes())
    assert recovered.snapshot_bytes() == encoded
    assert recovered.history(entity_id, "file") == (first, second)
    third = recovered.relocate(entity_id, "a.py")
    assert third.revision == 3
    assert len({first.locator_id, second.locator_id, third.locator_id}) == 3


def test_snapshot_recovery_cannot_resurrect_retired_entities():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    first = locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    encoded = locators.snapshot_bytes()
    entities.transition(entity_id, "retired", at_utc=NOW, reason="Owner retirement")
    recovered = LocatorRegistry.from_snapshot_bytes(entities, encoded)
    assert recovered.history(entity_id, "file") == (first,)
    assert recovered.get(entity_id, "file") is None
    assert recovered.resolve_reference("file", "a.py") == ()


def test_snapshot_recovery_rejects_content_change_and_unknown_entity():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    encoded = locators.snapshot_bytes()
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(entities, encoded.replace(b'a.py', b'b.py'))
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(EntityRegistry(), encoded)


@pytest.mark.parametrize("mutation", ["geometry", "revision_gap", "duplicate", "old_schema", "timestamp", "extra_field", "history_limit"])
def test_recomputed_snapshot_digest_cannot_bypass_record_invariants(mutation):
    import hashlib
    from runtime.json_io import bounded_canonical_json_bytes

    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py")
    payload = json.loads(locators.snapshot_bytes())
    payload.pop("content_sha256")
    row = payload["records"][0]
    if mutation == "geometry": row["location"]["reference"] = "b.py"
    elif mutation == "revision_gap": row["revision"] = 2
    elif mutation == "duplicate": payload["records"].append(dict(row))
    elif mutation == "old_schema": row["schema_version"] = "px.semantic-locator/1.0"
    elif mutation == "timestamp": row["observed_utc"] = "2026-10-03T12:00:00"
    elif mutation == "extra_field": row["accepted"] = True
    elif mutation == "history_limit": payload["max_history"] = True
    image = bounded_canonical_json_bytes(payload, max_bytes=16 * 1024 * 1024)
    payload["content_sha256"] = hashlib.sha256(image).hexdigest()
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(entities, json.dumps(payload).encode())
    assert entities.get(entity_id).lifecycle_state == "proposed"


def test_snapshot_recovery_rejects_duplicate_json_and_oversized_input():
    entities = EntityRegistry()
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(entities, b'{"records":[],"records":[]}')
    with pytest.raises(SemanticLocatorError, match="max_bytes"):
        LocatorRegistry.from_snapshot_bytes(entities, b' ' * (16 * 1024 * 1024 + 1))


@pytest.mark.parametrize("reference", ["../outside.py", "/outside.py", "C:/outside.py", "runtime/../outside.py", "runtime\\outside.py", "runtime//outside.py", "runtime/a.py:stream", "runtime/a\x00.py"])
def test_default_locator_policy_rejects_nonportable_or_escaping_paths(reference):
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    with pytest.raises(SemanticLocatorError):
        locators.set_locator(entity_id=entity_id, locator_kind="file", reference=reference)
    assert locators.history(entity_id, "file") == ()


def test_default_locator_policy_does_not_admit_external_namespaces():
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    for kind, reference in (("uri", "https://example.test/engine"), ("external", "capability:engine")):
        with pytest.raises(SemanticLocatorError):
            locators.set_locator(entity_id=entity_id, locator_kind=kind, reference=reference)


def test_current_reference_policy_cannot_be_widened_by_snapshot():
    from runtime.semantic_locator import LocatorReferencePolicy
    entities = EntityRegistry()
    entity_id = _entity(entities, "module", "engine")
    broad = LocatorRegistry(entities)
    broad.set_locator(entity_id=entity_id, locator_kind="file", reference="scripts/engine.py")
    policy = LocatorReferencePolicy(allowed_roots=("runtime",))
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(entities, broad.snapshot_bytes(), reference_policy=policy)
    restricted = LocatorRegistry(entities, reference_policy=policy)
    restricted.set_locator(entity_id=entity_id, locator_kind="file", reference="runtime/engine.py")
    with pytest.raises(SemanticLocatorError):
        restricted.relocate(entity_id, "runtime-other/engine.py")


def test_explicit_external_namespaces_roundtrip_without_becoming_default_authority():
    from runtime.semantic_locator import LocatorReferencePolicy
    entities = EntityRegistry()
    entity_id = _entity(entities, "module", "engine")
    policy = LocatorReferencePolicy(uri_roots=("https://example.test/services",), external_prefixes=("capability:",))
    locators = LocatorRegistry(entities, reference_policy=policy)
    uri = locators.set_locator(entity_id=entity_id, locator_kind="uri", reference="https://example.test/services/engine")
    external = locators.set_locator(entity_id=entity_id, locator_kind="external", reference="capability:engine")
    encoded = locators.snapshot_bytes()
    with pytest.raises(SemanticLocatorError):
        LocatorRegistry.from_snapshot_bytes(entities, encoded)
    recovered = LocatorRegistry.from_snapshot_bytes(entities, encoded, reference_policy=policy)
    assert recovered.resolve_reference("uri", uri.reference) == (uri,)
    assert recovered.resolve_reference("external", external.reference) == (external,)


@pytest.mark.parametrize("reference", [
    "https://example.test.evil/services/engine", "http://example.test/services/engine",
    "https://example.test/services-other/engine", "https://user@example.test/services/engine",
    "https://example.test/services/../private", "https://example.test/services/%2e%2e/private",
    "https://example.test/services/%252e%252e/private", "https://example.test/services//engine",
    "https://example.test/services/a%2fb", "https://example.test:broken/services/engine",
])
def test_uri_namespace_enforces_authority_and_path_boundaries(reference):
    from runtime.semantic_locator import LocatorReferencePolicy
    entities = EntityRegistry()
    entity_id = _entity(entities, "module", "engine")
    locators = LocatorRegistry(entities, reference_policy=LocatorReferencePolicy(uri_roots=("https://example.test/services",)))
    with pytest.raises(SemanticLocatorError):
        locators.set_locator(entity_id=entity_id, locator_kind="uri", reference=reference)
    assert locators.history(entity_id, "uri") == ()


@pytest.mark.parametrize("configuration", [
    {"allowed_roots": ("../runtime",)}, {"allowed_roots": ["runtime"]},
    {"uri_roots": ("https://user@example.test/services",)},
    {"external_prefixes": ("capability",)}, {"allowed_roots": ("runtime", "runtime")},
])
def test_namespace_policy_rejects_invalid_configuration(configuration):
    from runtime.semantic_locator import LocatorReferencePolicy
    with pytest.raises(SemanticLocatorError):
        LocatorReferencePolicy(**configuration)


def test_reverse_resolution_preserves_shared_file_ambiguity():
    entities, locators, _ = _world()
    identifiers = [_entity(entities, "symbol", name) for name in ("one", "two")]
    records = [locators.set_locator(entity_id=identifier, locator_kind="file", reference="shared.py") for identifier in identifiers]
    assert set(locators.resolve_reference("file", "shared.py")) == set(records)


def test_versioned_locator_passes_live_native_contract_and_rejects_missing_geometry():
    from runtime.contracts import ContractValidationError, validate_instance

    entities, locators, _ = _world()
    entity_id = _entity(entities, "symbol", "run")
    record = locators.set_locator(entity_id=entity_id, locator_kind="line_range", reference="a.py", line_start=1, line_end=2)
    payload = record.as_mapping()
    validate_instance(payload, REPO_ROOT / SCHEMA_LOCATOR)
    payload["location"]["line_end"] = None
    with pytest.raises(ContractValidationError):
        validate_instance(payload, REPO_ROOT / SCHEMA_LOCATOR)
    payload = record.as_mapping()
    payload.pop("revision")
    with pytest.raises(ContractValidationError):
        validate_instance(payload, REPO_ROOT / SCHEMA_LOCATOR)


@pytest.mark.parametrize("observation", [
    {"confidence": True}, {"confidence": float("nan")},
    {"confidence": float("inf")}, {"observed_utc": "2026-10-03T12:00:00"},
    {"observed_by": False},
])
def test_invalid_observation_is_not_added_to_history(observation):
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "engine")
    with pytest.raises(SemanticLocatorError):
        locators.set_locator(entity_id=entity_id, locator_kind="file", reference="a.py", **observation)
    assert locators.history(entity_id, "file") == ()


def test_both_contracts_exist_at_the_card_paths() -> None:
    for relative, prefix in ((SCHEMA_LOCATOR, "urn:engineering-loop-bootstrap:contract:semantic:locator-record"),
                             (SCHEMA_RELATION, "urn:engineering-loop-bootstrap:contract:semantic:relation-record")):
        schema_path = REPO_ROOT / relative
        assert schema_path.is_file(), relative
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert schema["$id"] == prefix
    locator_schema = json.loads((REPO_ROOT / SCHEMA_LOCATOR).read_text(encoding="utf-8"))
    assert set(LOCATOR_KINDS) <= set(
        locator_schema["properties"]["locator_kind"]["enum"]
    )
    relation_schema = json.loads((REPO_ROOT / SCHEMA_RELATION).read_text(encoding="utf-8"))
    assert set(RELATION_KINDS) <= set(
        relation_schema["properties"]["relation_kind"]["enum"]
    )


def test_a_path_edit_changes_the_locator_and_never_the_entity_identity() -> None:
    """SEM-002's primary acceptance criterion."""
    entities, locators, _ = _world()
    entity_id = _entity(entities, "module", "semantic_locator")
    before = entities.get(entity_id)

    locators.set_locator(
        entity_id=entity_id, locator_kind="file", reference="runtime/old_name.py"
    )
    first = locators.get(entity_id, "file")
    locators.relocate(entity_id, "runtime/new_name.py")

    second = locators.get(entity_id, "file")
    # The location moved.
    assert first.reference == "runtime/old_name.py"
    assert second.reference == "runtime/new_name.py"
    assert second.locator_id != first.locator_id
    # The identity did not.
    after = entities.get(entity_id)
    assert after.entity_id == before.entity_id
    assert after.identity_basis == before.identity_basis
    # And exactly one current locator exists, so nothing stale survives.
    assert len([item for item in locators.for_entity(entity_id) if item.locator_kind == "file"]) == 1


def test_locator_identity_binds_the_entity_not_the_path() -> None:
    entity_id = "pxe1:" + "a" * 32
    first = derive_locator_id(entity_id, "file", "a.py")
    second = derive_locator_id(entity_id, "file", "b.py")
    assert first.startswith(LOCATOR_ID_PREFIX)
    assert first != second, "a move must produce a distinct locator"


def test_locator_requires_a_live_known_entity() -> None:
    entities, locators, _ = _world()
    with pytest.raises(SemanticLocatorError, match="unknown entity"):
        locators.set_locator(
            entity_id="pxe1:" + "b" * 32, locator_kind="file", reference="x.py"
        )
    entity_id = _entity(entities, "module", "doomed")
    entities.transition(entity_id, "accepted", at_utc=NOW)
    entities.transition(entity_id, "retired", at_utc=NOW, reason="gone")
    with pytest.raises(SemanticLocatorError, match="retired entity"):
        locators.set_locator(entity_id=entity_id, locator_kind="file", reference="x.py")


def test_line_range_locator_requires_a_valid_range() -> None:
    entities, locators, _ = _world()
    entity_id = _entity(entities, "symbol", "fn")
    with pytest.raises(SemanticLocatorError, match="requires line_start and line_end"):
        locators.set_locator(
            entity_id=entity_id, locator_kind="line_range", reference="a.py"
        )
    with pytest.raises(SemanticLocatorError, match="line_start exceeds line_end"):
        locators.set_locator(
            entity_id=entity_id,
            locator_kind="line_range",
            reference="a.py",
            line_start=90,
            line_end=10,
        )
    good = locators.set_locator(
        entity_id=entity_id,
        locator_kind="line_range",
        reference="a.py",
        line_start=10,
        line_end=20,
    )
    assert good.line_start == 10 and good.line_end == 20


def test_relation_refuses_a_dangling_endpoint() -> None:
    """SEM-002's second acceptance criterion."""
    entities, _, relations = _world()
    source = _entity(entities, "module", "consumer")
    with pytest.raises(SemanticLocatorError, match="dangling endpoint"):
        relations.add_relation(
            source_entity_id=source,
            relation_kind="depends_on",
            target_entity_id="pxe1:" + "c" * 32,
        )


def test_relation_refuses_a_retired_endpoint() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "consumer2")
    target = _entity(entities, "module", "provider")
    relations.add_relation(
        source_entity_id=source, relation_kind="depends_on", target_entity_id=target
    )
    entities.transition(target, "accepted", at_utc=NOW)
    entities.transition(target, "retired", at_utc=NOW, reason="removed")
    assert relations.dangling_relations(), "retiring an endpoint must expose the edge"
    with pytest.raises(SemanticLocatorError, match="dangling relation endpoints"):
        relations.assert_no_dangling()
    with pytest.raises(SemanticLocatorError, match="retired"):
        relations.add_relation(
            source_entity_id=source, relation_kind="depends_on", target_entity_id=target
        )


def test_graph_only_relations_may_not_point_outside_the_graph() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "needs_external")
    with pytest.raises(SemanticLocatorError, match="may not dangle outside the graph"):
        relations.add_relation(
            source_entity_id=source,
            relation_kind="depends_on",
            external_target="https://example.invalid",
        )
    # A non-graph relation may target an external resource, but must say what.
    external = relations.add_relation(
        source_entity_id=source,
        relation_kind="references",
        external_target="https://example.invalid/doc",
    )
    assert external.target_entity_id is None
    assert external.external_target == "https://example.invalid/doc"
    with pytest.raises(SemanticLocatorError, match="requires an external_target"):
        relations.add_relation(source_entity_id=source, relation_kind="references")


def test_relation_identity_is_idempotent_and_prefixed() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "src")
    target = _entity(entities, "module", "dst")
    first = relations.add_relation(
        source_entity_id=source, relation_kind="imports", target_entity_id=target
    )
    second = relations.add_relation(
        source_entity_id=source, relation_kind="imports", target_entity_id=target
    )
    assert first.relation_id == second.relation_id
    assert first.relation_id.startswith(RELATION_ID_PREFIX)
    assert len(relations) == 1


def test_distinct_external_targets_are_distinct_relations() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "external-source")
    first = relations.add_relation(source_entity_id=source, relation_kind="references", external_target="urn:source:first")
    second = relations.add_relation(source_entity_id=source, relation_kind="references", external_target="urn:source:second")
    assert first.relation_id != second.relation_id
    assert len(relations) == 2
    assert relations.get(first.relation_id) == first


def test_relation_direction_is_part_of_its_identity() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "direction-source")
    target = _entity(entities, "module", "direction-target")
    directed = relations.add_relation(source_entity_id=source, relation_kind="references", target_entity_id=target)
    undirected = relations.add_relation(source_entity_id=source, relation_kind="references", target_entity_id=target, directed=False)
    assert directed.relation_id != undirected.relation_id
    assert len(relations) == 2


def test_conflicting_relation_declarations_do_not_overwrite_provenance() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "provenance-source")
    first = relations.add_relation(source_entity_id=source, relation_kind="references", external_target="urn:source", declared_by="owner-one")
    with pytest.raises(SemanticLocatorError, match="conflicting"):
        relations.add_relation(source_entity_id=source, relation_kind="references", external_target="urn:source", declared_by="owner-two")
    assert relations.get(first.relation_id).declared_by == "owner-one"


def test_location_edges_cannot_be_asserted_without_locators() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "unbound-location")
    with pytest.raises(SemanticLocatorError, match="derived"):
        relations.add_relation(source_entity_id=source, relation_kind="located_at", external_target="arbitrary/file.py")


def test_relation_rejects_contradictory_or_mistyped_endpoints() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "typed-source")
    target = _entity(entities, "module", "typed-target")
    with pytest.raises(SemanticLocatorError):
        relations.add_relation(source_entity_id=source, relation_kind="references", target_entity_id=target, external_target="urn:other")
    with pytest.raises(SemanticLocatorError):
        relations.add_relation(source_entity_id=source, relation_kind="references", target_entity_id=target, directed="false")
    with pytest.raises(SemanticLocatorError):
        relations.add_relation(source_entity_id=source, relation_kind="references", external_target=42)


def test_self_reference_is_refused_except_for_references() -> None:
    entities, _, relations = _world()
    entity_id = _entity(entities, "symbol", "self")
    with pytest.raises(SemanticLocatorError, match="self-referential"):
        relations.add_relation(
            source_entity_id=entity_id, relation_kind="depends_on", target_entity_id=entity_id
        )
    allowed = relations.add_relation(
        source_entity_id=entity_id, relation_kind="references", target_entity_id=entity_id
    )
    assert allowed.target_entity_id == entity_id


def test_located_at_edges_are_derived_from_locators() -> None:
    entities, locators, relations = _world()
    entity_id = _entity(entities, "module", "located")
    locators.set_locator(entity_id=entity_id, locator_kind="file", reference="runtime/a.py")
    derived = relations.bind_locators(locators)
    assert len(derived) == 1
    edge = derived[0]
    assert edge.relation_kind == "located_at"
    assert edge.external_target == "runtime/a.py"
    assert edge.target_entity_id is None
    # A relocation must move the derived edge, never leave the old one behind.
    locators.relocate(entity_id, "runtime/b.py")
    moved = relations.bind_locators(locators)
    assert moved[0].external_target == "runtime/b.py"


def test_relation_document_reports_dangling_count() -> None:
    entities, _, relations = _world()
    source = _entity(entities, "module", "doc")
    target = _entity(entities, "module", "doctarget")
    relations.add_relation(
        source_entity_id=source, relation_kind="calls", target_entity_id=target
    )
    document = relations.relation_document()
    assert document["relation_count"] == 1
    assert document["dangling_count"] == 0
    entities.transition(target, "accepted", at_utc=NOW)
    entities.transition(target, "retired", at_utc=NOW, reason="gone")
    assert relations.relation_document()["dangling_count"] == 1


def test_invalid_locator_kind_and_reference_fail_closed() -> None:
    with pytest.raises(SemanticLocatorError, match="locator kind is invalid"):
        derive_locator_id("pxe1:" + "d" * 32, "telepathy", "x.py")
    with pytest.raises(SemanticLocatorError, match="non-empty string"):
        derive_locator_id("pxe1:" + "d" * 32, "file", "   ")
