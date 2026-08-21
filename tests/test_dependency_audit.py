import json
from pathlib import Path

from runtime.dependency_audit import validate_dependency_closure
from scripts.build_python_dependency_ownership import build


ROOT = Path(__file__).resolve().parents[1]


def test_packaged_imports_are_fully_classified_and_declared():
    result = validate_dependency_closure(ROOT)
    assert result["valid"], result["errors"]
    assert result["unclassified"] == 0
    assert result["runtime_dependency_count"] == 0
    locked = {
        line.split("==", 1)[0].casefold()
        for line in (ROOT / "requirements-release.lock")
        .read_text(encoding="utf-8")
        .splitlines()
        if line and not line.startswith("#") and "==" in line
    }
    assert result["release_dependency_count"] == len(locked) == 13
    assert result["build_requirements"] == ["setuptools==83.0.0"]
    assert result["lock_hash_counts"]["coverage"] >= 12
    assert result["lock_hash_counts"]["pyyaml"] >= 12
    assert result["lock_hash_counts"]["ruff"] >= 3


def test_dependency_inventory_is_deterministic_and_gates_runtime_yaml():
    first = build(ROOT)
    assert json.dumps(first, sort_keys=True) == json.dumps(build(ROOT), sort_keys=True)
    yaml_record = next(item for item in first["records"] if item["module"] == "yaml")
    assert yaml_record["classification"] == "optional_gated"
    assert "runtime/project_intelligence.py" in yaml_record["paths"]
