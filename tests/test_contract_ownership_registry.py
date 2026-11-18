from pathlib import Path

from scripts.build_contract_ownership_registry import build
from tests.test_studio_operation_mirror_custody import native


ROOT = Path(__file__).resolve().parents[1]


def test_revision_succession_ownership_is_complete_and_deterministic() -> None:
    generated = build(ROOT)
    assert generated == build(ROOT)
    records = {row["path"]: row for row in generated["records"]}
    paths = sorted((ROOT / "contracts/project_revision_succession").glob("*.json"))
    assert len(paths) == 4
    for path in paths:
        record = records[path.relative_to(ROOT).as_posix()]
        assert record["owner"] == "runtime/project_revision_succession.py"
        assert record["enforcement"] == "revision_succession_runtime_boundary"
        assert "runtime/revision_campaign_lifecycle.py" in record["producers"]
        assert "runtime/test_profiles.py" in record["consumers"]
        for field in ("producers", "consumers", "tests"):
            assert record[field]
            assert all((ROOT / item).is_file() for item in record[field])


def test_contract_cli_uses_native_publication_and_settlement(native, monkeypatch) -> None:
    import hashlib
    import json
    from scripts import build_contract_ownership_registry as cli
    from runtime.effect_intent import EffectIntentLedger
    from runtime.scope_lease import ScopeLeaseStore

    root, admission = native
    (root / "contracts").mkdir()
    monkeypatch.setattr(cli, "ROOT", root)
    monkeypatch.setattr("sys.argv", ["contract-owners", "--admission-event-id", admission])
    assert cli.main() == 0
    image = (root / "registry/contract_ownership.json").read_bytes()
    assert json.loads(image) == build(root)
    assert any(row["state"] == "committed" and row["result_sha256"] == hashlib.sha256(image).hexdigest()
               for row in EffectIntentLedger(root)._load()["intents"])
    assert ScopeLeaseStore(root).active(effect="write") == ()


def test_remote_profile_has_actual_runtime_owner_and_packaged_dependencies() -> None:
    import tomllib

    result = build(ROOT)
    record = next(item for item in result["records"]
                  if item["path"] == "contracts/operations/remote-provider-profile.schema.json")
    assert record["owner"] == "runtime/remote_provider_profiles.py"
    assert record["enforcement"] == "signed_remote_profile_runtime_boundary"
    for consumer in ("runtime/remote_provider_profiles.py", "runtime/group_provider_adapters.py",
                     "runtime/remote_model_bridge.py"):
        assert consumer in record["consumers"]
        assert (ROOT / consumer).is_file()
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    resources = manifest["tool"]["setuptools"]["package-data"]["agentic_engineering_os_px"]
    for resource in ("remote_model_contracts.json", "remote_service_protocols.json"):
        assert resource in resources and (ROOT / "runtime" / resource).is_file()


def test_generation_contract_ownership_survives_canonical_regeneration() -> None:
    import json

    generated = build(ROOT)
    published = json.loads((ROOT / "registry/contract_ownership.json").read_text(encoding="utf-8"))
    for name, owner, consumer in (
        ("context-generation-vector", "runtime/context_generation.py", "runtime/projection_gate.py"),
        ("projection-status", "runtime/projection_gate.py", "runtime/librarian_semantic_map.py"),
    ):
        path = f"contracts/{name}.schema.json"
        record = next(item for item in generated["records"] if item["path"] == path)
        assert record["owner"] == owner
        assert consumer in record["consumers"]
        assert "runtime/librarian_semantic_map.py" in record["producers"]
        assert record == next(item for item in published["records"] if item["path"] == path)


def test_semantic_memory_envelope_has_explicit_runtime_ownership() -> None:
    result = build(ROOT)
    record = next(
        item
        for item in result["records"]
        if item["path"] == "contracts/memory/semantic-memory-envelope.schema.json"
    )

    assert record["owner"] == "runtime/semantic_memory.py"
    assert record["producers"] == [
        "runtime/semantic_memory.py",
        "runtime/memory_fabric.py",
        "runtime/memory_intelligence.py",
        "runtime/project_stream_orchestrator.py",
    ]
    assert record["enforcement"] == "memory_lifecycle_runtime_boundary"
    assert "tests/test_contract_runtime.py" in record["tests"]


def test_local_model_runtime_contract_has_explicit_runtime_ownership() -> None:
    result = build(ROOT)
    record = next(
        item
        for item in result["records"]
        if item["path"] == "contracts/operations/local-model-runtime.schema.json"
    )

    assert record["owner"] == "runtime/local_model_runtime.py"
    assert record["producers"] == ["runtime/local_model_runtime.py"]
    assert record["enforcement"] == "local_model_lifecycle_runtime_boundary"
    assert "tests/test_local_model_runtime.py" in record["tests"]


def test_execution_generation_vector_is_a_versioned_compatibility_contract() -> None:
    """2.0 is the compatibility contract for the same surface, not a second owner."""
    result = build(ROOT)
    records = {row["path"]: row for row in result["records"]}
    canonical = records["contracts/context-generation-vector.schema.json"]
    compat = records["contracts/models/execution-generation-vector.schema.json"]

    assert compat["owner"] == canonical["owner"] == "runtime/context_generation.py"
    assert compat["enforcement"] == "versioned_compatibility_contract_shared_runtime_surface"
    assert canonical["enforcement"] == "typed_scoped_archivist_metadata_boundary"
    # One shared runtime producer, with no invented independent runtime path. The
    # canonical 1.0 contract also names the modules that build 1.0 records
    # (dependency_invalidation, librarian_semantic_map); the 2.0 compatibility contract
    # is produced solely by the shared implementation.
    assert compat["producers"] == ["runtime/context_generation.py"]
    assert canonical["producers"][0] == "runtime/context_generation.py"
    # Every producer named for the compatibility contract must be a real, distinct path.
    assert len(set(compat["producers"])) == len(compat["producers"])
    for producer in compat["producers"]:
        assert (ROOT / producer).is_file()
    # The compatibility surface keeps the verified reader, projection_gate included.
    assert "runtime/projection_gate.py" in canonical["consumers"]
    assert "runtime/projection_gate.py" in compat["consumers"]
    # librarian_semantic_map CONSTRUCTS a vector through context_vector_for_dependencies,
    # so it is a producer of the canonical surface, not a consumer of it.
    assert "runtime/librarian_semantic_map.py" in canonical["producers"]
    assert "runtime/librarian_semantic_map.py" not in canonical["consumers"]
    # Exactly one record per schema identity.
    assert [row["path"] for row in result["records"]].count(
        "contracts/models/execution-generation-vector.schema.json") == 1


def test_generation_vector_versions_are_semantically_versioned_not_alias() -> None:
    """2.0 widens the vector to include execution lineage; it is not a version-only alias."""
    import json

    canonical = json.loads((ROOT / "contracts/context-generation-vector.schema.json").read_text(encoding="utf-8"))
    compat = json.loads((ROOT / "contracts/models/execution-generation-vector.schema.json").read_text(encoding="utf-8"))
    assert canonical["properties"]["schema_version"]["const"] == "px.context-generation-vector/1.0"
    assert compat["properties"]["schema_version"]["const"] == "px.context-generation-vector/2.0"
    narrow = canonical["properties"]["vector"]["required"]
    wide = compat["properties"]["vector"]["required"]
    assert set(narrow) < set(wide), "2.0 must strictly extend the 1.0 component set"
    for name in ("model_execution_group_revision", "model_contract_set_revision",
                 "gremlin_revision", "network_policy_revision", "workflow_adapter_revision"):
        assert name in wide and name not in narrow


def test_runtime_accepts_both_generation_versions_and_both_validate_against_own_contract() -> None:
    """The shared runtime emits/reads both, and each version obeys only its own contract."""
    from pathlib import Path

    import pytest

    from runtime.context_generation import (COMPONENTS, EXECUTION_LINEAGE_COMPONENTS,
                                            context_vector)
    from runtime.contracts import validate_instance

    def record(lineage):
        components = {name: "a" * 64 for name in COMPONENTS}
        components.update({name: "b" * 64 for name in lineage})
        return context_vector("prj", "scope", components)
    one, two = record(()), record(EXECUTION_LINEAGE_COMPONENTS)
    assert one.as_mapping()["schema_version"] == "px.context-generation-vector/1.0"
    assert two.as_mapping()["schema_version"] == "px.context-generation-vector/2.0"
    validate_instance(one.as_mapping(), Path(ROOT / "contracts/context-generation-vector.schema.json"))
    validate_instance(two.as_mapping(), Path(ROOT / "contracts/models/execution-generation-vector.schema.json"))
    # The compatibility boundary is discriminating, not permissive.
    with pytest.raises(Exception):
        validate_instance(one.as_mapping(), Path(ROOT / "contracts/models/execution-generation-vector.schema.json"))
    with pytest.raises(Exception):
        validate_instance(two.as_mapping(), Path(ROOT / "contracts/context-generation-vector.schema.json"))
