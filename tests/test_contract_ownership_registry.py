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
