from pathlib import Path
import shutil
import tempfile

from runtime.evidence_portability import (
    PRODUCT_STRUCTURED_ROOTS,
    STRUCTURED_ROOTS,
    discover_historical_references,
    portability_findings,
    rewrite_reference_literals,
    validate_evidence_portability,
)
from runtime.release_preflight import evidence_portability as release_evidence_portability


ROOT = Path(__file__).parents[1]


def test_all_evidence_locators_are_project_relative() -> None:
    result = validate_evidence_portability(ROOT)
    assert result["valid"], result["errors"]
    assert result["reference_count"] == 0
    assert all(not item["runtime_required"] for item in result["records"])


def test_new_sibling_evidence_reference_fails_independent_release_audit() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    (root / "evidence").mkdir(parents=True)
    (root / "evidence/new.json").write_text(
        '{"source":"../temp/unowned.json"}\n', encoding="utf-8"
    )
    assert not release_evidence_portability(root)["valid"]


def test_generated_portability_registry_is_not_self_ingested() -> None:
    root = Path(tempfile.mkdtemp()) / "framework"
    shutil.copytree(
        ROOT,
        root,
        ignore=shutil.ignore_patterns(
            ".git", ".engineering-bootstrap", "__pycache__", ".pytest_cache"
        ),
    )
    registry = root / "registry/historical_external_references.json"
    registry.write_text(
        '{"reference_count":0,"records":[],"note":"../obsolete"}\n', encoding="utf-8"
    )
    assert validate_evidence_portability(root)["valid"]


def test_immutable_control_capture_families_are_not_runtime_locators(tmp_path) -> None:
    full = tmp_path / "evidence/full-control-proof-20260822/capture.json"
    fault = tmp_path / "evidence/operational-control-fault-20260822/receipt.json"
    full.parent.mkdir(parents=True)
    fault.parent.mkdir(parents=True)
    full.write_text('{"displayed_fixture":"C:\\\\portable\\\\workspace"}\n', encoding="utf-8")
    fault.write_text('{"displayed_fixture":"C:\\\\portable\\\\workspace"}\n', encoding="utf-8")

    assert discover_historical_references(tmp_path) == []


def test_local_adversarial_audit_outputs_are_not_release_locators(tmp_path) -> None:
    report = tmp_path / "evidence/adversarial-audit/current.json"
    report.parent.mkdir(parents=True)
    report.write_text(
        '{"source":"C:\\\\Users\\\\operator\\\\workspace"}\n',
        encoding="utf-8",
    )

    assert discover_historical_references(tmp_path) == []


def test_product_projection_excludes_evidence_without_weakening_audit(
    tmp_path: Path,
) -> None:
    registry = tmp_path / "registry/historical_external_references.json"
    registry.parent.mkdir(parents=True)
    registry.write_text('{"reference_count":0,"records":[]}\n', encoding="utf-8")
    evidence = tmp_path / "evidence/operator-capture.json"
    evidence.parent.mkdir(parents=True)
    evidence.write_text(
        '{"source":"C:\\\\Users\\\\operator\\\\outside.json"}\n',
        encoding="utf-8",
    )

    assert discover_historical_references(tmp_path) == []
    assert discover_historical_references(
        tmp_path, structured_roots=PRODUCT_STRUCTURED_ROOTS
    ) == []
    assert len(
        discover_historical_references(tmp_path, structured_roots=STRUCTURED_ROOTS)
    ) == 1
    assert validate_evidence_portability(tmp_path)["valid"]
    result = release_evidence_portability(tmp_path)
    assert not result["valid"]
    assert result["findings"][0]["path"] == "evidence/operator-capture.json"


def test_portability_detects_unc_path() -> None:
    assert portability_findings(r"\\server\share\file")


def test_portability_detects_file_uri() -> None:
    assert portability_findings("file:///Users/a/file")


def test_portability_detects_wsl_mount_path() -> None:
    assert portability_findings("/mnt/c/work/file")


def test_portability_allowlist_is_explicit() -> None:
    assert not portability_findings("https://example.test/evidence")


def test_shell_parameter_is_not_misclassified_as_a_path() -> None:
    assert not portability_findings("$ARGUMENTS")


def test_lowercase_api_route_is_not_misclassified_as_a_home_directory() -> None:
    assert not portability_findings("/users/policy")


def test_reference_literal_rewrite_preserves_structure() -> None:
    value = {"summary": "see ../common/rules.md", "nested": ["file://", 3]}
    assert rewrite_reference_literals(
        value,
        {"../common/": "source-reference:common/", "file://": "local file URI"},
    ) == {
        "summary": "see source-reference:common/rules.md",
        "nested": ["local file URI", 3],
    }
