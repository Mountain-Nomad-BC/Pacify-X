"""The entity owner must resolve its own contract and round-trip what it publishes.

Regression for a defect where the owner resolved its contract by walking up from
``__file__`` instead of through the framework-root owner. The contract was
missing from the checkout, so publication reported ``PUBLISHED`` and the reload
that followed raised a bare ``FileNotFoundError`` naming the framework's own
schema -- the owner could not read back a registry it had just written.
"""
import json

import pytest

from runtime import semantic_entity as se
from runtime.contracts import ContractValidationError, validate_instance


def _registry():
    registry = se.EntityRegistry()
    registry.register(
        entity_kind="surface",
        identity_basis=se.identity_basis_for("declared_identifier", "probe.one"),
        declared_by="test",
    )
    return registry


def test_contract_resolves_from_the_framework_root():
    path = se.contract_path()
    assert path.is_file()
    assert path.as_posix().endswith(se.SCHEMA_RELATIVE.as_posix())


def test_published_registry_round_trips(tmp_path):
    registry = _registry()
    receipt = se.publish_registry(registry, tmp_path)
    assert receipt["status"] == "PUBLISHED"
    loaded = se.load_published_registry(tmp_path)
    assert loaded is not None
    assert [r.entity_id for r in loaded.all_entities()] == [
        r.entity_id for r in registry.all_entities()
    ]


def test_snapshot_record_satisfies_its_own_contract(tmp_path):
    se.publish_registry(_registry(), tmp_path)
    record = json.loads(_registry().snapshot_bytes())["records"][0]
    validate_instance(record, se.contract_path())


@pytest.mark.parametrize(
    "mutation",
    [
        {"path": "/etc/passwd"},
        {"entity_id": "pxe1:not-a-digest"},
        {"entity_kind": "filesystem"},
        {"lifecycle": {"state": "active"}},
        {"identity_basis": {"basis_kind": "declared_identifier", "content_sha256": "nope"}},
        # `qualifier` is what entity_id is derived from. Omitting it leaves an
        # identity that cannot be re-derived, so the contract must refuse the
        # record rather than accept an unauditable identity.
        {"identity_basis": {"basis_kind": "declared_identifier"}},
        {"identity_basis": {}},
    ],
)
def test_contract_refuses_malformed_records(mutation):
    record = json.loads(_registry().snapshot_bytes())["records"][0]
    record.update(mutation)
    with pytest.raises(ContractValidationError):
        validate_instance(record, se.contract_path())


def test_missing_contract_is_a_domain_error_not_a_path_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(se, "SCHEMA_RELATIVE", se.Path("contracts/semantic/absent.schema.json"))
    with pytest.raises(se.SemanticEntityError, match="not installed with the framework"):
        se.contract_path()
