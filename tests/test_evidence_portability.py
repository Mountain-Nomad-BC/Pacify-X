from pathlib import Path
import shutil
import tempfile

from runtime.evidence_portability import validate_evidence_portability


ROOT = Path(__file__).parents[1]


def test_all_evidence_locators_are_project_relative() -> None:
    result = validate_evidence_portability(ROOT)
    assert result["valid"], result["errors"]
    assert result["reference_count"] == 0
    assert all(not item["runtime_required"] for item in result["records"])


def test_new_sibling_reference_fails_until_disposition_registry_is_rebuilt() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    (root / "evidence/new.json").write_text('{"source":"../temp/unowned.json"}\n', encoding="utf-8")
    assert not validate_evidence_portability(root)["valid"]


def test_generated_portability_registry_is_not_self_ingested() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    registry = root / "registry/historical_external_references.json"
    registry.write_text('{"reference_count":0,"records":[],"note":"../obsolete"}\n', encoding="utf-8")
    assert validate_evidence_portability(root)["valid"]
