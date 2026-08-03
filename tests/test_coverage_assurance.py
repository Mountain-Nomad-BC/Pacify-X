from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile

from runtime.coverage_assurance import validate_coverage_evidence
from runtime.release_certification import _verify_coverage_binding


ROOT = Path(__file__).resolve().parents[1]


def _write_fixture(root: Path, *, branch_percent: float = 100.0, exemptions: object = None) -> Path:
    (root / "policies").mkdir(parents=True, exist_ok=True)
    total = 10
    missing = round(total * (100.0 - branch_percent) / 100.0)
    policy = {
        "schema_version": "1.0",
        "branch_required": True,
        "dynamic_context_required": True,
        "classes": {
            "path_boundaries": {
                "minimum_branch_percent": 80,
                "modules": ["runtime/bounded_walk.py"],
            }
        },
        "exemptions": [] if exemptions is None else exemptions,
    }
    (root / "policies/coverage-assurance.json").write_text(json.dumps(policy), encoding="utf-8")
    evidence = {
        "meta": {"branch_coverage": True, "show_contexts": True},
        "files": {
            "runtime/bounded_walk.py": {
                "summary": {"num_branches": total, "missing_branches": missing},
                "contexts": {"1": ["test_fixture"]},
            }
        },
    }
    coverage = root / "coverage.json"
    coverage.write_text(json.dumps(evidence), encoding="utf-8")
    return coverage


def test_python_validation_requires_executed_coverage_not_text_reference() -> None:
    ownership = json.loads((ROOT / "registry/python_surface_ownership.json").read_text(encoding="utf-8"))
    levels = {record["validation_level"] for record in ownership["records"]}
    assert "direct-test-reference" not in levels
    assert "evidence-association" in levels


def test_safety_critical_modules_meet_branch_threshold() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = _write_fixture(root, branch_percent=90)
        assert validate_coverage_evidence(root, evidence)["valid"]
        evidence = _write_fixture(root, branch_percent=70)
        result = validate_coverage_evidence(root, evidence)
        assert not result["valid"]
        assert "aggregate branch coverage" in "\n".join(result["errors"])
        assert "below 80.0%" in "\n".join(result["errors"])


def test_coverage_evidence_is_bound_to_certificate() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        source = _write_fixture(root)
        release_path = root / "evidence/releases/1.0.0/run-1/coverage.json"
        release_path.parent.mkdir(parents=True)
        release_path.write_bytes(source.read_bytes())
        certificate = {
            "coverage_evidence": "evidence/releases/1.0.0/run-1/coverage.json",
            "coverage_evidence_sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        }
        assert _verify_coverage_binding(root, "1.0.0", certificate)["valid"]
        release_path.write_text("{}", encoding="utf-8")
        assert not _verify_coverage_binding(root, "1.0.0", certificate)["valid"]


def test_coverage_exemption_requires_owner_and_reason() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        evidence = _write_fixture(
            root,
            exemptions=[{"module": "runtime/bounded_walk.py", "branches": [7]}],
        )
        result = validate_coverage_evidence(root, evidence)
        assert not result["valid"]
        assert "requires module, owner, reason, and branches" in "\n".join(result["errors"])
