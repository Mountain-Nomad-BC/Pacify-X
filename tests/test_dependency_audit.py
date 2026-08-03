import copy
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
    assert result["release_dependency_count"] == 6


def test_dependency_inventory_is_deterministic_and_has_no_runtime_yaml_dependency():
    first = build(ROOT)
    assert json.dumps(first, sort_keys=True) == json.dumps(build(ROOT), sort_keys=True)
    yaml_record = next(item for item in first["records"] if item["module"] == "yaml")
    assert yaml_record["classification"] == "test_only"
    assert all(path.startswith("tests/") for path in yaml_record["paths"])
