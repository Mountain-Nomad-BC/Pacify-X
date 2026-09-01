from pathlib import Path

from scripts.build_contract_ownership_registry import build


ROOT = Path(__file__).resolve().parents[1]


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
