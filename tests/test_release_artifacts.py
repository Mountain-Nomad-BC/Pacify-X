from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from runtime.release_artifacts import classify_tree, verify_frozen_product


ROOT = Path(__file__).parents[1]


def _minimal_tree() -> Path:
    root = Path(tempfile.mkdtemp()) / "framework"
    (root / "policies").mkdir(parents=True)
    shutil.copy2(
        ROOT / "policies/release-artifact-policy.json",
        root / "policies/release-artifact-policy.json",
    )
    (root / "runtime").mkdir()
    (root / "runtime/module.py").write_text("VALUE = 1\n", encoding="utf-8")
    return root


def test_product_digest_is_deterministic_and_detects_mutation() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    second = classify_tree(root)
    assert first["valid"] and first["product_digest"] == second["product_digest"]
    (root / "runtime/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    assert not verify_frozen_product(root, first)["valid"]


def test_unclassified_root_file_fails_closed() -> None:
    root = _minimal_tree()
    (root / "mystery.bin").write_bytes(b"unknown")
    result = classify_tree(root)
    assert not result["valid"]
    assert any("unclassified" in item for item in result["errors"])


def test_executable_payload_cannot_hide_in_evidence() -> None:
    root = _minimal_tree()
    (root / "evidence").mkdir()
    (root / "evidence/hidden.py").write_text("print('hidden')\n", encoding="utf-8")
    result = classify_tree(root)
    assert not result["valid"]
    assert any("evidence payload" in item for item in result["errors"])


def test_only_evidence_change_does_not_change_product_digest() -> None:
    root = _minimal_tree()
    (root / "evidence").mkdir()
    evidence = root / "evidence/result.json"
    evidence.write_text("{}\n", encoding="utf-8")
    first = classify_tree(root)
    evidence.write_text('{"changed":true}\n', encoding="utf-8")
    second = classify_tree(root)
    assert first["product_digest"] == second["product_digest"]


def test_junit_xml_is_an_admitted_non_executable_evidence_format() -> None:
    root = _minimal_tree()
    report = root / "evidence/release-runs/example/full-tests.junit.xml"
    report.parent.mkdir(parents=True)
    report.write_text(
        '<testsuites tests="1" failures="0" errors="0" skipped="0" />\n',
        encoding="utf-8",
    )
    result = classify_tree(root)
    assert result["valid"], result["errors"]


def test_setuptools_egg_info_is_generated_intermediate_not_product() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    metadata = root / "engineering_loop_bootstrap.egg-info/PKG-INFO"
    metadata.parent.mkdir()
    metadata.write_text("Metadata-Version: 2.4\n", encoding="utf-8")
    second = classify_tree(root)
    record = next(
        item for item in second["records"] if item["path"].endswith("PKG-INFO")
    )
    assert second["valid"], second["errors"]
    assert record["classification"] == "generated_intermediate"
    assert first["product_digest"] == second["product_digest"]


def test_git_metadata_is_generated_intermediate_not_product() -> None:
    root = _minimal_tree()
    first = classify_tree(root)
    metadata = root / ".git/objects/example"
    metadata.parent.mkdir(parents=True)
    metadata.write_text("git metadata\n", encoding="utf-8")
    second = classify_tree(root)
    record = next(
        item for item in second["records"] if item["path"] == ".git/objects/example"
    )
    assert second["valid"], second["errors"]
    assert record["classification"] == "generated_intermediate"
    assert first["product_digest"] == second["product_digest"]
