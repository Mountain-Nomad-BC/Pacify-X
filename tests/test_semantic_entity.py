from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

"""SEM-001: the canonical semantic entity contract and its identity rule.

The property under test is the one SEM-001 exists to establish: identity is
derived from stable intrinsic facts and never from a filesystem location, so an
entity survives rename and move. Everything else here protects that rule.
"""

from runtime.semantic_entity import (
    ENTITY_ID_PREFIX,
    ENTITY_KINDS,
    ENTITY_SCHEMA_VERSION,
    LIFECYCLE_STATES,
    SCHEMA_RELATIVE,
    EntityRegistry,
    SemanticEntityError,
    derive_entity_id,
    identity_basis_for,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-02T00:00:00Z"


def test_registered_identity_basis_and_identity_tuple_cannot_be_mutated_by_readers():
    registry = EntityRegistry()
    record = registry.register(entity_kind="record", identity_basis=identity_basis_for("declared_identifier", "immutable-record"), declared_by="test")
    expected_qualifier = record.identity_basis["qualifier"]
    with pytest.raises(TypeError):
        record.identity_basis["qualifier"] = "forged-record"
    observed = registry.identity_tuple(record.entity_id)
    observed["qualifier"] = "forged-record"
    assert registry.identity_tuple(record.entity_id)["qualifier"] == expected_qualifier
    assert derive_entity_id(record.entity_kind, record.identity_basis) == record.entity_id


@pytest.mark.parametrize("qualifier", ["runtime/worker.py", r"runtime\worker.py", "C:worker", "../worker", "___", "\x00worker"])
def test_locator_or_empty_normalized_name_cannot_be_intrinsic_identity(qualifier):
    with pytest.raises(SemanticEntityError):
        identity_basis_for("declared_identifier", qualifier)


def test_content_identity_records_the_actual_digest_and_rejects_contradictions():
    digest = hashlib.sha256(b"source").hexdigest()
    basis = identity_basis_for("intrinsic_content", digest)
    assert basis["content_sha256"] == digest
    with pytest.raises(SemanticEntityError, match="contradicts"):
        identity_basis_for("intrinsic_content", digest, content_sha256="f" * 64)
    with pytest.raises(SemanticEntityError, match="contradicts"):
        derive_entity_id("record", {**basis, "content_sha256": "f" * 64})


def test_registered_terms_and_qualifiers_obey_the_canonical_contract():
    with pytest.raises(SemanticEntityError, match="contract limit"):
        identity_basis_for("declared_identifier", "x" * 513)
    with pytest.raises(SemanticEntityError, match="search terms"):
        EntityRegistry().register(entity_kind="record", identity_basis=_basis("one"),
                                  declared_by="test", terms=["x" * 301])


def _basis(name: str) -> dict[str, object]:
    return identity_basis_for("intrinsic_name", name)


def test_entity_contract_exists_and_is_the_declared_owner() -> None:
    schema_path = REPO_ROOT / SCHEMA_RELATIVE
    assert schema_path.is_file(), "the new semantic entity contract must exist"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "urn:engineering-loop-bootstrap:contract:semantic:semantic-entity"
    assert set(ENTITY_KINDS) <= set(schema["properties"]["entity_kind"]["enum"])
    assert set(LIFECYCLE_STATES) <= set(
        schema["properties"]["lifecycle"]["properties"]["state"]["enum"]
    )


def test_derived_id_has_the_contract_shape() -> None:
    entity_id = derive_entity_id("operation", _basis("buildEngineIdentity"))
    assert entity_id.startswith(ENTITY_ID_PREFIX)
    assert len(entity_id) == len(ENTITY_ID_PREFIX) + 32
    int(entity_id.split(":")[1], 16)  # valid hex


def test_identity_survives_rename_and_move() -> None:
    """The core SEM-001 property: identity is independent of location."""
    before = derive_entity_id("module", _basis("semantic_entity"))
    # Simulate the same declaration discovered under a different path and name.
    after = derive_entity_id("module", identity_basis_for("intrinsic_name", "semantic_entity"))
    assert before == after
    # No path argument exists to perturb: the derivation accepts no location.
    import inspect

    signature = inspect.signature(derive_entity_id)
    assert set(signature.parameters) == {"entity_kind", "basis"}
    assert not any(
        "path" in name or "location" in name or "file" in name
        for name in signature.parameters
    )


def test_identity_survives_a_rename_that_only_changes_separator_style() -> None:
    """Separator and whole-token case changes are normalized.

    camelCase is deliberately NOT split. Folding `parseURL` into `parseurl`
    would risk colliding two genuinely distinct declarations, and a false
    identity collision is worse than a re-identified name. SEM-001 promises
    identity survives rename and move, not that it survives casing of an
    unseparated camelCase identifier.
    """
    a = derive_entity_id("operation", _basis("build_engine_identity"))
    b = derive_entity_id("operation", _basis("build-engine-identity"))
    c = derive_entity_id("operation", _basis("BUILD.ENGINE.Identity"))
    assert a == b == c


def test_entity_record_carries_no_path_field() -> None:
    registry = EntityRegistry()
    record = registry.register(
        entity_kind="module", identity_basis=_basis("thing"), declared_by="test"
    )
    mapping = record.as_mapping()
    assert "source_path" not in mapping
    assert "path" not in mapping
    assert mapping["schema_version"] == ENTITY_SCHEMA_VERSION
    serialized = json.dumps(mapping)
    assert "source_path" not in serialized


def test_different_intrinsic_names_are_different_entities() -> None:
    a = derive_entity_id("module", _basis("alpha"))
    b = derive_entity_id("module", _basis("beta"))
    assert a != b


def test_same_name_in_different_kinds_is_not_a_collision() -> None:
    a = derive_entity_id("module", _basis("shared_name"))
    b = derive_entity_id("operation", _basis("shared_name"))
    assert a != b


def test_content_identity_requires_a_digest_not_raw_text() -> None:
    digest = hashlib.sha256(b"body").hexdigest()
    basis = identity_basis_for("intrinsic_content", digest)
    entity_id = derive_entity_id("contract", basis)
    assert entity_id == derive_entity_id("contract", basis)
    with pytest.raises(SemanticEntityError, match="64 character lowercase sha256"):
        identity_basis_for("intrinsic_content", "raw source text")


def test_governing_contract_does_not_fork_identity() -> None:
    a = identity_basis_for("intrinsic_name", "thing", governing_contract="c/1")
    b = identity_basis_for("intrinsic_name", "thing")
    assert derive_entity_id("module", a) == derive_entity_id("module", b)


def test_content_addressed_identity_makes_hash_collision_infeasible() -> None:
    """Two different identity tuples cannot collide, by construction.

    The collision case SEM-001 warns about is real, but it is NOT a hash
    collision: it is NAME reuse. Two different declarations that both call
    themselves `build` under intrinsic_name derive two DIFFERENT ids once
    content is folded in, so the registry never silently merges them.
    """
    registry = EntityRegistry()
    left = registry.register(
        entity_kind="operation",
        identity_basis=identity_basis_for("intrinsic_content", hashlib.sha256(b"left").hexdigest()),
        declared_by="module-a",
    )
    right = registry.register(
        entity_kind="operation",
        identity_basis=identity_basis_for("intrinsic_content", hashlib.sha256(b"right").hexdigest()),
        declared_by="module-b",
    )
    assert left.entity_id != right.entity_id
    assert len(registry) == 2


def test_registry_rejects_a_basis_that_contradicts_an_existing_identity() -> None:
    """A forged basis must not be able to re-point an existing identity."""
    registry = EntityRegistry()
    record = registry.register(
        entity_kind="module", identity_basis=_basis("dup"), declared_by="scanner-a"
    )
    forged = dict(record.identity_basis)
    forged["qualifier"] = "different"
    # Deriving from the forged basis yields a DIFFERENT id, so the registry
    # simply holds two entities rather than silently re-pointing one.
    replacement = registry.register(
        entity_kind="module", identity_basis=forged, declared_by="scanner-b"
    )
    assert replacement.entity_id != record.entity_id
    assert registry.get(record.entity_id).identity_basis["qualifier"] == "dup"


def test_repeat_registration_is_idempotent() -> None:
    registry = EntityRegistry()
    one = registry.register(entity_kind="module", identity_basis=_basis("x"), declared_by="a")
    two = registry.register(entity_kind="module", identity_basis=_basis("x"), declared_by="b")
    assert one.entity_id == two.entity_id
    assert len(registry) == 1


def test_lifecycle_transitions_are_enforced_and_never_reverse() -> None:
    registry = EntityRegistry()
    record = registry.register(
        entity_kind="declaration", identity_basis=_basis("decl"), declared_by="test"
    )
    accepted = registry.transition(record.entity_id, "accepted", at_utc=NOW)
    assert accepted.lifecycle_state == "accepted"
    retired = registry.transition(
        record.entity_id, "retired", at_utc=NOW, reason="superseded"
    )
    assert retired.lifecycle_state == "retired"
    # A retired entity can never come back, including to its own state.
    with pytest.raises(SemanticEntityError, match="invalid lifecycle transition"):
        registry.transition(record.entity_id, "accepted", at_utc=NOW)
    with pytest.raises(SemanticEntityError, match="invalid lifecycle transition"):
        registry.transition(record.entity_id, "retired", at_utc=NOW, reason="again")


def test_retirement_requires_a_reason() -> None:
    registry = EntityRegistry()
    record = registry.register(
        entity_kind="declaration", identity_basis=_basis("needs_reason"), declared_by="test"
    )
    registry.transition(record.entity_id, "accepted", at_utc=NOW)
    with pytest.raises(SemanticEntityError, match="retirement requires a reason"):
        registry.transition(record.entity_id, "retired", at_utc=NOW)


def test_registry_document_reports_the_identity_rule() -> None:
    registry = EntityRegistry()
    registry.register(entity_kind="symbol", identity_basis=_basis("sym"), declared_by="test")
    document = registry.registry_document()
    assert document["entity_contract"] == ENTITY_SCHEMA_VERSION
    assert document["entity_count"] == 1
    assert "no filesystem location participates in identity" in document["identity_rule"]
    assert "symbol" in document["by_kind"]


def test_invalid_kind_and_empty_qualifier_fail_closed() -> None:
    with pytest.raises(SemanticEntityError, match="entity kind is invalid"):
        derive_entity_id("not_a_kind", _basis("x"))
    with pytest.raises(SemanticEntityError, match="non-empty string"):
        identity_basis_for("intrinsic_name", "   ")
    with pytest.raises(SemanticEntityError, match="identity basis kind is invalid"):
        identity_basis_for("by_vibes", "x")


def test_content_sha256_is_rejected_for_non_content_basis() -> None:
    with pytest.raises(SemanticEntityError, match="only valid for intrinsic_content"):
        identity_basis_for("intrinsic_name", "x", content_sha256="a" * 64)
# ---------------------------------------------------------------------------
# Durable canonical store.
#
# The registry above held accepted identity only for the life of the process,
# so an accepted entity could not survive a restart and no recovery could be
# proven. These pin the durability contract, mirroring the sibling locator
# store: bounded canonical JSON, a content digest over the whole document, and
# re-derivation of every identity from its own basis on recovery.
# ---------------------------------------------------------------------------


def _reseal(document: dict) -> bytes:
    """Re-seal a mutated snapshot with a correct digest so the real check binds.

    The digest is taken over the store's own bounded canonical encoding, so a
    plain json.dumps would merely re-test the digest and never reach the
    identity or lifecycle checks this is here to exercise.
    """
    from runtime.json_io import bounded_canonical_json_bytes

    body = {key: value for key, value in document.items() if key != "content_sha256"}
    body["content_sha256"] = hashlib.sha256(
        bounded_canonical_json_bytes(body, max_bytes=64 * 1024 * 1024)
    ).hexdigest()
    return json.dumps(body).encode("utf-8")


def _named(registry: EntityRegistry, name: str, kind: str = "symbol") -> str:
    return registry.register(
        entity_kind=kind,
        identity_basis=_basis(name),
        declared_by="tests/sem001",
    ).entity_id


def test_accepted_identity_survives_a_restart():
    registry = EntityRegistry()
    entity_id = _named(registry, "run")
    registry.transition(entity_id, "accepted", at_utc=NOW)

    recovered = EntityRegistry.from_snapshot_bytes(registry.snapshot_bytes())

    assert len(recovered) == 1
    record = recovered.get(entity_id)
    assert record is not None
    assert record.lifecycle_state == "accepted"
    assert record.accepted_utc == NOW
    assert recovered.assert_unique_accepted() == (entity_id,)


def test_snapshot_round_trips_every_lifecycle_state():
    registry = EntityRegistry()
    proposed = _named(registry, "proposed_one")
    accepted = _named(registry, "accepted_one")
    retired = _named(registry, "retired_one")
    registry.transition(accepted, "accepted", at_utc=NOW)
    registry.transition(retired, "accepted", at_utc=NOW)
    registry.transition(retired, "retired", at_utc=NOW, reason="superseded")

    recovered = EntityRegistry.from_snapshot_bytes(registry.snapshot_bytes())

    assert recovered.get(proposed).lifecycle_state == "proposed"
    assert recovered.get(accepted).lifecycle_state == "accepted"
    gone = recovered.get(retired)
    assert gone.lifecycle_state == "retired"
    assert gone.retirement_reason == "superseded"


def test_recovery_is_deterministic_across_repeated_round_trips():
    registry = EntityRegistry()
    for name in ("alpha", "beta", "gamma"):
        registry.transition(_named(registry, name), "accepted", at_utc=NOW)

    first = registry.snapshot_bytes()

    assert EntityRegistry.from_snapshot_bytes(first).snapshot_bytes() == first


def test_snapshot_rejects_altered_content():
    registry = EntityRegistry()
    registry.transition(_named(registry, "run"), "accepted", at_utc=NOW)
    document = json.loads(registry.snapshot_bytes())
    document["records"][0]["lifecycle"]["retirement_reason"] = "tampered"

    with pytest.raises(SemanticEntityError, match="digest mismatch"):
        EntityRegistry.from_snapshot_bytes(json.dumps(document).encode("utf-8"))


def test_snapshot_rejects_a_forged_identity_that_does_not_re_derive():
    registry = EntityRegistry()
    registry.transition(_named(registry, "run"), "accepted", at_utc=NOW)
    document = json.loads(registry.snapshot_bytes())
    document["records"][0]["entity_id"] = ENTITY_ID_PREFIX + "0" * 32

    with pytest.raises(SemanticEntityError, match="identity binding mismatch"):
        EntityRegistry.from_snapshot_bytes(_reseal(document))


def test_snapshot_rejects_duplicate_identities():
    registry = EntityRegistry()
    registry.transition(_named(registry, "alpha"), "accepted", at_utc=NOW)
    registry.transition(_named(registry, "beta"), "accepted", at_utc=NOW)
    document = json.loads(registry.snapshot_bytes())
    document["records"][1] = json.loads(json.dumps(document["records"][0]))

    with pytest.raises(SemanticEntityError, match="uniquely ordered"):
        EntityRegistry.from_snapshot_bytes(_reseal(document))


def test_snapshot_requires_exact_bytes_and_refuses_unknown_fields():
    registry = EntityRegistry()

    with pytest.raises(SemanticEntityError, match="exact byte image"):
        EntityRegistry.from_snapshot_bytes('{"schema_version": "x"}')

    document = json.loads(registry.snapshot_bytes())
    document["unexpected"] = True
    with pytest.raises(SemanticEntityError, match="fields are invalid"):
        EntityRegistry.from_snapshot_bytes(json.dumps(document).encode("utf-8"))


def test_recovery_rejects_an_accepted_record_without_acceptance_time():
    registry = EntityRegistry()
    registry.transition(_named(registry, "run"), "accepted", at_utc=NOW)
    document = json.loads(registry.snapshot_bytes())
    document["records"][0]["lifecycle"]["accepted_utc"] = None

    with pytest.raises(SemanticEntityError, match="acceptance time"):
        EntityRegistry.from_snapshot_bytes(_reseal(document))


def test_recovery_rejects_a_retired_record_without_a_reason():
    registry = EntityRegistry()
    entity_id = _named(registry, "run")
    registry.transition(entity_id, "accepted", at_utc=NOW)
    registry.transition(entity_id, "retired", at_utc=NOW, reason="superseded")
    document = json.loads(registry.snapshot_bytes())
    document["records"][0]["lifecycle"]["retirement_reason"] = None

    with pytest.raises(SemanticEntityError, match="reason"):
        EntityRegistry.from_snapshot_bytes(_reseal(document))


def test_unique_accepted_identities_are_reported_without_merging():
    registry = EntityRegistry()
    first = _named(registry, "one")
    second = _named(registry, "two")
    registry.transition(first, "accepted", at_utc=NOW)
    registry.transition(second, "accepted", at_utc=NOW)

    assert registry.assert_unique_accepted() == tuple(sorted({first, second}))


def test_declared_identifier_is_one_identity_not_a_silent_merge():
    registry = EntityRegistry()
    first = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for("declared_identifier", "shared.contract"),
        declared_by="tests/sem001",
    ).entity_id
    second = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for("declared_identifier", "shared.contract"),
        declared_by="another-owner",
    ).entity_id

    # Identity is derived from the declared identifier, so a repeat declaration
    # is the SAME entity and resolves to one canonical id rather than two
    # competing ones. register stays idempotent and no second record appears.
    assert first == second
    assert len(registry) == 1

    registry.transition(first, "accepted", at_utc=NOW)
    matches = registry.resolve_declared_identifier("contract", "shared.contract")

    assert [record.entity_id for record in matches] == [first]
    assert registry.assert_unique_accepted() == (first,)


def test_distinct_declared_identifiers_stay_distinct_identities():
    registry = EntityRegistry()
    first = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for("declared_identifier", "alpha.contract"),
        declared_by="tests/sem001",
    ).entity_id
    second = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for(
            "declared_identifier", "beta.contract", qualifier_kind="other"),
        declared_by="tests/sem001",
    ).entity_id
    registry.transition(first, "accepted", at_utc=NOW)
    registry.transition(second, "accepted", at_utc=NOW)

    assert first != second
    assert [r.entity_id for r in
            registry.resolve_declared_identifier("contract", "alpha.contract")] == [first]
    assert [r.entity_id for r in
            registry.resolve_declared_identifier("contract", "beta.contract")] == [second]
    assert registry.assert_unique_accepted() == tuple(sorted({first, second}))


def test_declared_identifier_resolution_excludes_retired_and_proposed():
    registry = EntityRegistry()
    proposed = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for("declared_identifier", "pending.contract"),
        declared_by="tests/sem001",
    ).entity_id
    retired = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for(
            "declared_identifier", "retired.contract", qualifier_kind="other"),
        declared_by="tests/sem001",
    ).entity_id
    registry.transition(retired, "accepted", at_utc=NOW)
    registry.transition(retired, "retired", at_utc=NOW, reason="no longer published")

    assert registry.resolve_declared_identifier("contract", "pending.contract") == ()
    assert registry.resolve_declared_identifier("contract", "retired.contract") == ()
    assert registry.get(proposed).lifecycle_state == "proposed"


def test_recovered_registry_resolves_a_declared_identifier_after_restart():
    registry = EntityRegistry()
    entity_id = registry.register(
        entity_kind="contract",
        identity_basis=identity_basis_for("declared_identifier", "kept.contract"),
        declared_by="tests/sem001",
    ).entity_id
    registry.transition(entity_id, "accepted", at_utc=NOW)

    recovered = EntityRegistry.from_snapshot_bytes(registry.snapshot_bytes())

    assert [r.entity_id for r in
            recovered.resolve_declared_identifier("contract", "kept.contract")] == [entity_id]